#!/usr/bin/env bash
# Runs ON THE VM: flush the world to disk and rsync mutable state back to the
# bucket. Called by the backup timer, by shutdown, and by vm-down.sh.
set -euo pipefail

BUCKET="gs://minecraft_lt"
SERVER_DIR="/opt/minecraft/server"

# Ask the running server to flush the world (ignore failures if it's down)
if systemctl is-active --quiet minecraft; then
  echo 'save-all flush' > /run/minecraft.stdin 2>/dev/null || true
  sleep 5
fi

# The world is thousands of small files; GCS per-object overhead makes rsync
# crawl, so ship it as a single compressed archive instead.
tar -C "${SERVER_DIR}" -czf - world | gcloud storage cp - "${BUCKET}/server-world.tar.gz"

# Only mutable state goes back; jars/runtime/libraries never change on the VM
for d in plugins config; do
  [ -d "${SERVER_DIR}/${d}" ] || continue
  gcloud storage rsync --recursive --delete-unmatched-destination-objects \
    "${SERVER_DIR}/${d}" "${BUCKET}/server/${d}"
done
for f in server.properties ops.json whitelist.json usercache.json \
         banned-players.json banned-ips.json; do
  [ -f "${SERVER_DIR}/${f}" ] && gcloud storage cp "${SERVER_DIR}/${f}" "${BUCKET}/server/${f}"
done

# Slides uploaded via the endpoint while the VM was up
if [ -d /opt/minecraft/slideshow/slides ]; then
  gcloud storage rsync --recursive \
    /opt/minecraft/slideshow/slides "${BUCKET}/slideshow/slides"
fi

# Persist Let's Encrypt certs so a new VM doesn't hit issuance rate limits
if [ -d /var/lib/caddy/.local ]; then
  tar -C /var/lib/caddy -czf - .local | gcloud storage cp - "${BUCKET}/ops/caddy-data.tar.gz"
fi

echo "Backup to ${BUCKET} complete: $(date -Is)"
