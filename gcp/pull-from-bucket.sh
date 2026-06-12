#!/usr/bin/env bash
# Pull the latest world/state from the bucket back into the local repo
# (e.g. to play locally or inspect the world after a GCP session).
set -euo pipefail

cd "$(dirname "$0")"
source ./config.sh
REPO_ROOT="$(cd .. && pwd)"

if gcloud storage objects describe "${BUCKET}/server-world.tar.gz" >/dev/null 2>&1; then
  rm -rf "${REPO_ROOT}/servers/minecraft_LT/world"
  gcloud storage cp "${BUCKET}/server-world.tar.gz" - | \
    tar -C "${REPO_ROOT}/servers/minecraft_LT" -xzf -
fi

for d in plugins config; do
  gcloud storage rsync --recursive \
    "${BUCKET}/server/${d}" "${REPO_ROOT}/servers/minecraft_LT/${d}"
done
gcloud storage rsync --recursive \
  "${BUCKET}/slideshow/slides" "${REPO_ROOT}/slideshow-endpoint/slides"

echo "Local copy updated from ${BUCKET}."
