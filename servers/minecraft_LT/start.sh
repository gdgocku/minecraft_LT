#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

JAVA_BIN="${JAVA_BIN:-./runtime/jdk-25.0.3+9/bin/java}"
if [[ ! -x "$JAVA_BIN" ]]; then
  JAVA_BIN="java"
fi

JAVA_OPTS=(
  "-Xms${MC_XMS:-1G}"
  "-Xmx${MC_XMX:-2G}"
  "-XX:+UseG1GC"
  "-XX:+ParallelRefProcEnabled"
  "-XX:MaxGCPauseMillis=200"
  "-XX:+UnlockExperimentalVMOptions"
  "-XX:+DisableExplicitGC"
  "-XX:+AlwaysPreTouch"
)

exec "$JAVA_BIN" "${JAVA_OPTS[@]}" -jar paper.jar nogui
