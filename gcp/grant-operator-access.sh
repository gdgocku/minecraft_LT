#!/usr/bin/env bash
# Create a LEAST-PRIVILEGE service account so a stand-in operator can run
# vm-up.sh / vm-down.sh on THEIR machine, without access to the owner's
# personal gcloud login.
#
# Run this ONCE, today, while the owner is around. Then hand the generated key
# file to the stand-in over a private channel and rehearse vm-up/vm-down on
# their machine the same day. Revoke with ./revoke-operator-access.sh after the
# event.
set -euo pipefail

cd "$(dirname "$0")"
source ./config.sh

PROJECT="$(gcloud config get-value project 2>/dev/null)"
SA_NAME="mc-lt-operator"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
KEY_FILE="${KEY_FILE:-./mc-lt-operator-key.json}"

echo "Project:         ${PROJECT}"
echo "Service account: ${SA_EMAIL}"
echo "Key file:        ${KEY_FILE}"
echo

# 1. Create the service account (idempotent)
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Minecraft LT stand-in operator"
  # SA creation is eventually consistent: the add-iam-policy-binding calls below
  # can race ahead and fail with "does not exist". Wait until it's visible.
  echo "Waiting for the service account to propagate..."
  for _ in $(seq 1 12); do
    gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1 && break
    sleep 5
  done
fi

# 2. Project-level roles, kept as tight as the scripts allow:
#    - compute.instanceAdmin.v1 : create / delete / describe the VM, and set the
#                                 SSH metadata that `gcloud compute ssh` needs
#    - iam.serviceAccountUser   : attach the default compute SA when creating the
#                                 VM (required because vm-up.sh passes --scopes)
#    - compute.viewer           : lets vm-up.sh's `firewall-rules describe` succeed
#                                 so it SKIPS creation (allow-minecraft already
#                                 exists) — read-only, no firewall-write granted
for ROLE in roles/compute.instanceAdmin.v1 roles/iam.serviceAccountUser roles/compute.viewer; do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" --role="${ROLE}" --condition=None >/dev/null
done

# 3. Bucket-level role: read/write ONLY gs://minecraft_lt (vm-up uploads the ops
#    scripts; restore/verify reads). Scoped to the bucket, not project storage.
gcloud storage buckets add-iam-policy-binding "${BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/storage.objectAdmin >/dev/null

# 4. Issue a JSON key to hand to the stand-in
gcloud iam service-accounts keys create "${KEY_FILE}" --iam-account="${SA_EMAIL}"

cat <<EOF

Done. Next steps (do these TODAY, while you can still fix permission issues):

  1. Hand ${KEY_FILE} to the stand-in over a PRIVATE channel (not git, not a
     public chat). It is git-ignored so it won't be committed.

  2. On THEIR machine (with gcloud + this repo):
       gcloud auth activate-service-account --key-file=mc-lt-operator-key.json
       gcloud config set project ${PROJECT}

  3. Rehearse the full loop on their machine:
       cd gcp && ./vm-up.sh          # wait a few min, then connect to mc.issan.dev
       # join Minecraft, open https://mc.issan.dev, confirm slides work
       ./vm-down.sh                  # confirm teardown works too

After the event: ./revoke-operator-access.sh
EOF
