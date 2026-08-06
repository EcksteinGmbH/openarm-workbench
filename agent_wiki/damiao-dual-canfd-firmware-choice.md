---
title: Damiao Dual CANFD Firmware Choice
category: reference
tags:
  - damiao
  - firmware
  - usb2canfd-dual
  - dmtool
  - socketcan
sources:
  - /home/ubuntu/Projects/达妙上位机/firmware-notes/firmware-choice.md:7
  - /home/ubuntu/Projects/达妙上位机/firmware-notes/firmware-choice.md:23
  - /home/ubuntu/Projects/达妙上位机/firmware-notes/firmware-choice.md:37
  - /home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:85
  - /home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:91
confidence: high
---

# Damiao Dual CANFD Firmware Choice

Damiao 双路 CANFD 调试器用于 DMTool 上位机时选 `dm_usb2canfd_dual_app_1007.enc`，用于 Linux SocketCAN 时选 `dm_usb2canfd_dual_gsusb_1004.enc`。

## Firmware Split

Use the app firmware for DMTool:

```text
USB2CANFD_Dual/固件/出厂固件/dm_usb2canfd_dual_app_1007.enc
```

It is appropriate for:

- DMTool 上位机
- USB/FDCAN 设备刷新
- 参数调试
- CAN 分析仪
- 固件升级

Use the gs_usb firmware for Linux SocketCAN:

```text
USB2CANFD_Dual/固件/socketcan/dm_usb2canfd_dual_gsusb_1004.enc
```

It is appropriate for:

- `can0` / `can1`
- `candump`
- `cansend`
- `python-can`
- OpenARM SocketCAN workflow

## Practical Consequence

同一个硬件刷不同固件后在 Linux 下表现不同：`app` 固件偏向 DMTool 通过 USB/FDCAN 直接访问，`gsusb` 固件偏向 Linux 网络接口 `can0` / `can1`。判断问题时先确定当前枚举模式，再决定是排查 DMTool USB 权限还是 SocketCAN 接口状态。

## Provenance

### sources

- `/home/ubuntu/Projects/达妙上位机/firmware-notes/firmware-choice.md:7`
- `/home/ubuntu/Projects/达妙上位机/firmware-notes/firmware-choice.md:23`
- `/home/ubuntu/Projects/达妙上位机/firmware-notes/firmware-choice.md:37`
- `/home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:85`
- `/home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:91`

### evidence

- The firmware-choice note records the exact app firmware path and gs_usb firmware path.
- The conversation record preserves the selection rationale: DMTool USB/FDCAN page uses app firmware; Linux `can0` / `can1` / `candump` / `python-can` uses gs_usb firmware.

### related_tasks

- None

