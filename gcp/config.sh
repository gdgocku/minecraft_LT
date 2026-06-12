# Shared configuration for GCP scripts. Source this from the other scripts.

BUCKET="gs://minecraft_lt"
VM_NAME="${VM_NAME:-minecraft-lt}"
ZONE="${ZONE:-asia-northeast1-b}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-2}"   # 2 vCPU / 8GB
IMAGE_FAMILY="debian-12"
IMAGE_PROJECT="debian-cloud"
BOOT_DISK_SIZE="20GB"
# Spot VMs are ~60-90% cheaper; can be preempted (world is backed up every 10 min)
PROVISIONING="${PROVISIONING:-spot}"
