#!/usr/bin/env bash
# Revoke the stand-in operator's access after the event. Deleting the service
# account invalidates every key issued from it, so a leaked key.json becomes
# useless even if it was never deleted on the other side.
set -euo pipefail

cd "$(dirname "$0")"
source ./config.sh

PROJECT="$(gcloud config get-value project 2>/dev/null)"
SA_NAME="mc-lt-operator"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

for ROLE in roles/compute.instanceAdmin.v1 roles/iam.serviceAccountUser roles/compute.viewer; do
  gcloud projects remove-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" --role="${ROLE}" --condition=None >/dev/null 2>&1 || true
done
gcloud storage buckets remove-iam-policy-binding "${BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/storage.objectAdmin >/dev/null 2>&1 || true
gcloud iam service-accounts delete "${SA_EMAIL}" --quiet || true

echo "Revoked: ${SA_EMAIL} deleted, all its keys invalidated, bindings removed."
echo "Also delete the local key file you handed out, and ask the stand-in to delete theirs."
