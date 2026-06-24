#!/usr/bin/env bash
# Create a fresh VM that restores itself from the bucket and starts serving.
set -euo pipefail

cd "$(dirname "$0")"
source ./config.sh

# Always upload the latest ops scripts so the VM boots with current logic.
# Strip CR first: a Windows / Git Bash checkout is usually CRLF, and a CRLF
# startup-script can't be executed by the VM (the shebang breaks) so nothing
# gets restored. Piping through sed guarantees LF regardless of the operator OS.
sed 's/\r$//' ./startup-script.sh | gcloud storage cp - "${BUCKET}/ops/startup-script.sh"
sed 's/\r$//' ./save-to-bucket.sh | gcloud storage cp - "${BUCKET}/ops/save-to-bucket.sh"

SPOT_FLAGS=()
if [ "${PROVISIONING}" = "spot" ]; then
  SPOT_FLAGS=(--provisioning-model=SPOT --instance-termination-action=DELETE)
fi

gcloud compute instances create "${VM_NAME}" \
  --zone="${ZONE}" \
  --machine-type="${MACHINE_TYPE}" \
  --image-family="${IMAGE_FAMILY}" \
  --image-project="${IMAGE_PROJECT}" \
  --boot-disk-size="${BOOT_DISK_SIZE}" \
  --scopes=storage-rw \
  --tags=minecraft \
  "${SPOT_FLAGS[@]}" \
  --metadata=startup-script-url="${BUCKET}/ops/startup-script.sh"

# Firewall rules are idempotent; create them if missing
gcloud compute firewall-rules describe allow-minecraft >/dev/null 2>&1 || \
  gcloud compute firewall-rules create allow-minecraft \
    --allow=tcp:25565,tcp:8765 --target-tags=minecraft

IP=$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo
echo "VM created. Restore takes a few minutes (watch: gcloud compute ssh ${VM_NAME} --zone=${ZONE} -- tail -f /var/log/minecraft-startup.log)"
echo "  Minecraft:  ${IP}:25565"
echo "  Slideshow:  http://${IP}:8765"
