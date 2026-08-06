#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/Projects/OpenARM/tmp/dmtool_v2_1_5_3/squashfs-root"

if [[ ! -x "${ROOT}/serial-port-assistant" ]]; then
  echo "DMTool extracted binary not found: ${ROOT}/serial-port-assistant" >&2
  echo "Run: '/home/ubuntu/下载/DMTool v2.1.5.3-x86_64.AppImage' --appimage-extract" >&2
  exit 1
fi

export LD_LIBRARY_PATH="${ROOT}:${ROOT}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export QT_PLUGIN_PATH="${ROOT}/plugins"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

exec "${ROOT}/serial-port-assistant"
