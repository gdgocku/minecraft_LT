#!/usr/bin/env bash
# VM startup script: restore everything from the bucket and start services.
# Runs as root on first boot (and every boot).
set -euo pipefail
exec > /var/log/minecraft-startup.log 2>&1

BUCKET="gs://minecraft_lt"
BASE="/opt/minecraft"

apt-get update -qq
apt-get install -y -qq python3 python3-pil screen poppler-utils \
  debian-keyring debian-archive-keyring apt-transport-https curl > /dev/null

# Caddy (reverse proxy for HTTPS; .dev domains are HSTS-preloaded so the
# slideshow UI must be served over TLS)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
    gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy > /dev/null
fi

mkdir -p "${BASE}"

echo "==> Restoring server from ${BUCKET}"
mkdir -p "${BASE}/server" "${BASE}/slideshow"
gcloud storage rsync --recursive --exclude='^world/' "${BUCKET}/server" "${BASE}/server"
# World travels as one archive (much faster than per-file rsync); fall back to
# the legacy per-file layout if the archive doesn't exist yet.
if gcloud storage objects describe "${BUCKET}/server-world.tar.gz" >/dev/null 2>&1; then
  rm -rf "${BASE}/server/world"
  gcloud storage cp "${BUCKET}/server-world.tar.gz" - | tar -C "${BASE}/server" -xzf -
else
  gcloud storage rsync --recursive "${BUCKET}/server/world" "${BASE}/server/world"
fi
gcloud storage rsync --recursive "${BUCKET}/slideshow" "${BASE}/slideshow"
gcloud storage cp "${BUCKET}/ops/save-to-bucket.sh" /usr/local/bin/save-to-bucket.sh

# Normalize line endings: if server/slideshow files were uploaded from a CRLF
# (Windows) checkout, CRLF in start.sh / start-slides.sh would break the systemd
# ExecStart. Strip CR from all shell scripts before use.
find "${BASE}/server" "${BASE}/slideshow" -name '*.sh' -exec sed -i 's/\r$//' {} + 2>/dev/null || true

chmod +x "${BASE}/server/start.sh" "${BASE}/slideshow/start-slides.sh" \
         /usr/local/bin/save-to-bucket.sh
chmod -R u+x "${BASE}/server/runtime" 2>/dev/null || true
find "${BASE}/server/runtime" -path '*/bin/*' -exec chmod +x {} + 2>/dev/null || true

# --- Minecraft service (stdin via FIFO so save-to-bucket can issue commands)
cat > /etc/systemd/system/minecraft.service <<'EOF'
[Unit]
Description=Minecraft Paper server
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/minecraft/server
Environment=MC_XMS=2G MC_XMX=6G
ExecStartPre=/bin/bash -c 'rm -f /run/minecraft.stdin && mkfifo /run/minecraft.stdin'
# <> opens the FIFO read-write so the server doesn't block waiting for a writer
ExecStart=/bin/bash -c 'exec ./start.sh 0<> /run/minecraft.stdin'
ExecStop=/bin/bash -c 'echo stop > /run/minecraft.stdin; sleep 15'
ExecStopPost=/usr/local/bin/save-to-bucket.sh
ExecStopPost=/usr/bin/rm -f /run/minecraft.stdin
Restart=on-failure
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
EOF

# --- Slideshow endpoint
cat > /etc/systemd/system/slideshow.service <<'EOF'
[Unit]
Description=Slideshow HTTP endpoint
After=network-online.target

[Service]
WorkingDirectory=/opt/minecraft/slideshow
ExecStart=/usr/bin/python3 slideshow_endpoint.py --host 0.0.0.0 --port 8765 --slides-dir slides
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# --- Periodic backup every 10 minutes (covers spot preemption)
cat > /etc/systemd/system/mc-backup.service <<'EOF'
[Unit]
Description=Backup Minecraft state to GCS

[Service]
Type=oneshot
ExecStart=/usr/local/bin/save-to-bucket.sh
EOF

cat > /etc/systemd/system/mc-backup.timer <<'EOF'
[Unit]
Description=Backup Minecraft state to GCS every 10 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now minecraft slideshow mc-backup.timer

# --- Point mc.issan.dev at this VM (DNS-only record, no proxy = no latency).
# Credentials live in the private bucket: ops/cloudflare.env defines CF_TOKEN.
if gcloud storage cp "${BUCKET}/ops/cloudflare.env" /run/cloudflare.env 2>/dev/null; then
  source /run/cloudflare.env
  HOSTNAME_FQDN="mc.issan.dev"
  MYIP=$(curl -s -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip')
  ZONE_ID=$(curl -s -H "Authorization: Bearer ${CF_TOKEN}" \
    'https://api.cloudflare.com/client/v4/zones?name=issan.dev' | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["result"][0]["id"])')
  RECORD_ID=$(curl -s -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?type=A&name=${HOSTNAME_FQDN}" | \
    python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print(r[0]["id"] if r else "")')
  BODY=$(printf '{"type":"A","name":"%s","content":"%s","ttl":60,"proxied":false}' "${HOSTNAME_FQDN}" "${MYIP}")
  if [ -n "${RECORD_ID}" ]; then
    curl -s -X PUT -H "Authorization: Bearer ${CF_TOKEN}" -H 'Content-Type: application/json' \
      "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RECORD_ID}" -d "${BODY}" > /dev/null
  else
    curl -s -X POST -H "Authorization: Bearer ${CF_TOKEN}" -H 'Content-Type: application/json' \
      "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" -d "${BODY}" > /dev/null
  fi
  rm -f /run/cloudflare.env
  echo "==> DNS: ${HOSTNAME_FQDN} -> ${MYIP}"
else
  echo "==> No cloudflare.env in bucket; skipping DNS update"
fi

# --- HTTPS for the slideshow UI via Caddy + Let's Encrypt.
# Certs are persisted in the bucket so VM recreation doesn't re-issue
# (Let's Encrypt limits duplicate certs to 5/week).
mkdir -p /var/lib/caddy
if gcloud storage objects describe "${BUCKET}/ops/caddy-data.tar.gz" >/dev/null 2>&1; then
  gcloud storage cp "${BUCKET}/ops/caddy-data.tar.gz" - | tar -C /var/lib/caddy -xzf -
  chown -R caddy:caddy /var/lib/caddy
fi
cat > /etc/caddy/Caddyfile <<'EOF'
mc.issan.dev {
    reverse_proxy localhost:8765
}
EOF
systemctl restart caddy

echo "==> Startup complete: $(date -Is)"
