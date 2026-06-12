#!/usr/bin/env bash
# VM startup script: restore everything from the bucket and start services.
# Runs as root on first boot (and every boot).
set -euo pipefail
exec > /var/log/minecraft-startup.log 2>&1

BUCKET="gs://minecraft_lt"
BASE="/opt/minecraft"

apt-get update -qq
apt-get install -y -qq python3 python3-pil screen poppler-utils > /dev/null

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

echo "==> Startup complete: $(date -Is)"
