#!/usr/bin/env bash
# One-time (or whenever local files change): push the local server + slideshow
# endpoint into the bucket. VMs are then created purely from the bucket.
set -euo pipefail

cd "$(dirname "$0")"
source ./config.sh
REPO_ROOT="$(cd .. && pwd)"

echo "==> Uploading world archive to ${BUCKET}/server-world.tar.gz"
tar -C "${REPO_ROOT}/servers/minecraft_LT" -czf - world | \
  gcloud storage cp - "${BUCKET}/server-world.tar.gz"

echo "==> Syncing Minecraft server to ${BUCKET}/server/"
gcloud storage rsync --recursive --delete-unmatched-destination-objects \
  --exclude='^(world/|logs/|cache/|\.console_history)' \
  "${REPO_ROOT}/servers/minecraft_LT" "${BUCKET}/server"

echo "==> Syncing slideshow endpoint to ${BUCKET}/slideshow/"
gcloud storage rsync --recursive --delete-unmatched-destination-objects \
  --exclude='^(__pycache__/)' \
  "${REPO_ROOT}/slideshow-endpoint" "${BUCKET}/slideshow"

echo "==> Uploading ops scripts (strip CR so a CRLF checkout can't break VM boot)"
sed 's/\r$//' ./startup-script.sh | gcloud storage cp - "${BUCKET}/ops/startup-script.sh"
sed 's/\r$//' ./save-to-bucket.sh | gcloud storage cp - "${BUCKET}/ops/save-to-bucket.sh"

echo "Done."
