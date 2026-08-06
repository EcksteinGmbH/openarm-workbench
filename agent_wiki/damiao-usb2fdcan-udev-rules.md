---
title: Damiao USB2FDCAN Udev Rules
category: environment
tags:
  - damiao
  - udev
  - usb2fdcan
  - permissions
sources:
  - /home/ubuntu/Projects/达妙上位机/tools/setup_dmtool_usb2fdcan.sh:10
  - /home/ubuntu/Projects/达妙上位机/tools/setup_dmtool_usb2fdcan.sh:14
  - /home/ubuntu/Projects/达妙上位机/tools/setup_dmtool_usb2fdcan.sh:18
  - /home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:53
  - /home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:60
confidence: high
---

# Damiao USB2FDCAN Udev Rules

This workstation needs udev permissions for `34b7:6877`, `34b7:6632`, and `1d50:606f` to cover Damiao's documented USB2FDCAN VID/PID, the observed DMTool app firmware PID, and the observed gs_usb firmware PID.

## Rule Set

The durable setup script writes `/etc/udev/rules.d/99-dm-fdcan.rules` with:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="34b7", ATTR{idProduct}=="6877", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="34b7", ATTR{idProduct}=="6877", MODE="0666", GROUP="plugdev"

SUBSYSTEM=="usb", ATTR{idVendor}=="34b7", ATTR{idProduct}=="6632", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="34b7", ATTR{idProduct}=="6632", MODE="0666", GROUP="plugdev", TAG+="uaccess"

SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666", GROUP="plugdev", TAG+="uaccess"
```

After updating rules, reload udev, trigger it, ensure the user is in `plugdev`, then unplug and replug the adapter:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG plugdev "$USER"
```

## When To Apply

Apply these rules when DMTool sees the device during refresh but fails to open it, or when `/dev/bus/usb/...` shows restrictive ownership such as `root:root 664`. The failure is permissions-related, not a serial-port-number problem.

## Provenance

### sources

- `/home/ubuntu/Projects/达妙上位机/tools/setup_dmtool_usb2fdcan.sh:10`
- `/home/ubuntu/Projects/达妙上位机/tools/setup_dmtool_usb2fdcan.sh:14`
- `/home/ubuntu/Projects/达妙上位机/tools/setup_dmtool_usb2fdcan.sh:18`
- `/home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:53`
- `/home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:60`

### evidence

- The setup script encodes all three VID/PID combinations as executable local configuration.
- The conversation record preserves that the official README documented `34b7:6877`, while local gs_usb firmware was observed as `1d50:606f`.
- Later device diagnostics added the observed app-firmware PID `34b7:6632`.

### related_tasks

- None

