---
title: Damiao USB2FDCAN Is Not A Serial Device
category: debugging
tags:
  - damiao
  - dmtool
  - usb2fdcan
  - serial
  - socketcan
sources:
  - /home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:5
  - /home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:16
  - /home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:24
  - /home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:32
  - /home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:16
  - /home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:67
confidence: high
---

# Damiao USB2FDCAN Is Not A Serial Device

Damiao DM-USB2FDCAN 在 Linux 下不会总是生成 `/dev/ttyUSB*` 或 `/dev/ttyACM*`，因此 DMTool 里“打开串口”失败通常说明走错入口，应改用 USB/FDCAN 或 SocketCAN 路径。

## Observed Behavior

- 本机串口枚举为空：`/dev/ttyUSB*`、`/dev/ttyACM*`、`/dev/serial/by-id/*` 均不存在，`python3 -m serial.tools.list_ports -v` 返回 `no ports found`。
- 同一只 DM-USB2FDCAN 在不同固件下曾枚举为 `1d50:606f OpenMoko ... CAN adapter` 或 `34b7:6632 DaMiao-Tech DM-USB2FDCAN`。
- `1d50:606f` gs_usb 固件路径下，Linux 生成的是 `can0` / `can1`，不是串口设备。
- DMTool 启动日志曾出现 `found DM-FDCAN,cnt=1`，说明上位机可通过 USB/FDCAN 入口识别设备，即使串口列表为空。

## Troubleshooting Rule

当用户反馈“达妙上位机打开串口失败”时，先查：

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/*
python3 -m serial.tools.list_ports -v
lsusb
ip -details link show type can
```

如果没有 tty 节点但有 DM-USB2FDCAN USB 设备或 `can0` / `can1`，不要继续排查串口号；引导用户使用 DMTool 的 FDCAN / USB 设备刷新入口，或使用 SocketCAN 工具链。

## Provenance

### sources

- `/home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:5`
- `/home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:16`
- `/home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:24`
- `/home/ubuntu/Projects/达妙上位机/docs/device-diagnostics.md:32`
- `/home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:16`
- `/home/ubuntu/Projects/达妙上位机/docs/conversation-record.md:67`

### evidence

- 本机诊断记录明确保存了串口枚举为空和 `pyserial` 无端口的输出。
- 同一记录保存了 DM-USB2FDCAN 在 gs_usb 固件下生成 `can0` / `can1` 的事实。
- DMTool 解包启动日志被记录为 `found DM-FDCAN,cnt=1`，证明 USB/FDCAN 入口可识别该设备。

### related_tasks

- None

