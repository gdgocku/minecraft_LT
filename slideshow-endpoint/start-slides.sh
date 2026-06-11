#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

exec python3 slideshow_endpoint.py \
  --host 0.0.0.0 \
  --port 8765 \
  --slides-dir slides \
  --init-samples
