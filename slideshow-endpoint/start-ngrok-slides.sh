#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

NGROK_BIN="${NGROK_BIN:-../servers/minecraft_LT/runtime/ngrok}"
if [[ ! -x "$NGROK_BIN" ]]; then
  NGROK_BIN="ngrok"
fi

exec "$NGROK_BIN" http 8765
