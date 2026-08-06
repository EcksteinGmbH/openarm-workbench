#!/usr/bin/env bash
set -euo pipefail

RULE_FILE="/etc/udev/rules.d/99-dm-fdcan.rules"
APPIMAGE="/home/ubuntu/下载/DMTool v2.1.5.3-x86_64.AppImage"

echo "Configuring DMTool USB2FDCAN permissions..."

sudo tee "${RULE_FILE}" >/dev/null <<'RULES'
# Damiao DM-USB2FDCAN official VID/PID from DM-Tools README.
SUBSYSTEM=="usb", ATTR{idVendor}=="34b7", ATTR{idProduct}=="6877", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="34b7", ATTR{idProduct}=="6877", MODE="0666", GROUP="plugdev"

# DM-USB2FDCAN gsusb/candleLight-compatible firmware observed on this machine.
SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666", GROUP="plugdev", TAG+="uaccess"
RULES

sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG plugdev "$USER"

chmod +x "${APPIMAGE}"

echo
echo "Done. If DMTool still cannot see the USB2FDCAN device, unplug and replug the adapter,"
echo "or log out and log back in so group membership is refreshed."
echo
echo "Run DMTool with:"
echo "\"${APPIMAGE}\""
