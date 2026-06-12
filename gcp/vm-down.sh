#!/usr/bin/env bash
# Save world state to the bucket, then delete the VM (and its disk) entirely.
set -euo pipefail

cd "$(dirname "$0")"
source ./config.sh

echo "==> Final backup to bucket"
gcloud compute ssh "${VM_NAME}" --zone="${ZONE}" --command \
  'sudo systemctl stop minecraft' || \
  echo "WARNING: could not stop server cleanly; continuing with delete"

echo "==> Deleting VM ${VM_NAME} (boot disk included)"
gcloud compute instances delete "${VM_NAME}" --zone="${ZONE}" --quiet

echo "Done. Recreate any time with ./vm-up.sh"
