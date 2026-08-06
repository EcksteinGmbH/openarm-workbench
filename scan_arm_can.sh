#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHANNEL="${OPENARM_CAN_CHANNEL:-can0}"
BITRATE="${OPENARM_CAN_BITRATE:-1000000}"
PROFILE="${OPENARM_CAN_PROFILE:-openarm_v1}"
OUTPUT_DIR="${OPENARM_SCAN_OUTPUT_DIR:-$ROOT_DIR/artifacts/can_scan}"

if [[ $# -gt 0 ]]; then
  exec python3 -m src.arm_can_scan_cli "$@"
fi

exec python3 -m src.arm_can_scan_cli \
  --channel "$CHANNEL" \
  --bitrate "$BITRATE" \
  --profile "$PROFILE" \
  --output-dir "$OUTPUT_DIR"
