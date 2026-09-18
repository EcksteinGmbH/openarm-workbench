---
title: Damiao SocketCAN Frame Classification
category: debugging
tags:
  - damiao
  - socketcan
  - can2.0
  - frame-parser
  - status-feedback
sources:
  - src/damiao_motor_driver.py:286
  - src/damiao_motor_driver.py:300
  - src/damiao_motor_driver.py:326
  - src/damiao_motor_driver.py:333
  - src/damiao_motor_driver.py:628
  - src/damiao_motor_driver.py:639
  - tests/test_workstation.py:395
  - tests/test_workstation.py:409
  - tests/test_workstation.py:440
  - docs/WORKSTATION_CHANGELOG.md:231
  - docs/WORKSTATION_CHANGELOG.md:232
  - docs/WORKSTATION_CHANGELOG.md:233
  - docs/WORKSTATION_CHANGELOG.md:237
confidence: high
---

# Damiao SocketCAN Frame Classification

Damiao SocketCAN 帧的 payload 第三字节等于 `0x33` 或 `0x55` 并不足以判定参数帧；前两个字节还必须解析为已注册电机 ID，否则合法状态帧会被误判并导致位置、温度或故障状态丢失。

## Classification Rule

- `_looks_like_param_payload()` 先检查帧长和第三字节 marker，再把 payload 前两个字节按 little-endian 解析为 `slave_id`；只有该 ID 存在于 `motors_map` 时才返回参数帧。
- `_drain()` 对通过上述完整判定的帧调用 `_process_param_payload()`，其他 8-byte 帧进入 `_process_status_payload()`。
- 状态帧的位置编码天然可能让第三个 payload 字节碰巧等于 `0x33` 或 `0x55`，因此不能只靠 marker 分流。

## Known Regression Shape

- L-J4 状态帧 `0C5F557FF8001F1C` 的第三字节是 `0x55`，但前两个字节会解析为 `0x5F0C`，不是已注册 slave ID；它必须作为状态帧解析。
- 正确解析后应保留非零 position、MOS/rotor 温度和 `last_status_frame`；旧误判表现通常是这些反馈保持为零或缺失。
- 状态码和 fault 必须从第一个 payload 字节读取，不能从位置字节推导。
- L-J8 的 `ESC_ID=0x10` 超过 4-bit ID 范围；当首字节完整匹配已配置 slave ID 时，解析器保留 `0x10` 并按静态反馈处理为 DISABLED，避免把高 nibble 误当 ENABLED 状态。

## Troubleshooting

- 如果某个关节在线且有原始帧，但位置或温度持续为零，先保存 `data_hex` 并检查是否命中 `0x33/0x55` 碰撞形态。
- 修复分流逻辑时同时运行 L-J4 marker-collision、首字节 fault 和 L-J8 `0x10` ID 回归测试；单独测试参数读取不足以覆盖状态帧路径。
- 本页描述的是帧解析边界；整臂只读通信扫描的作业语义见 [[openarm-arm-can20-comm-scan]]。

## Provenance

### sources

- `src/damiao_motor_driver.py:286`
- `src/damiao_motor_driver.py:300`
- `src/damiao_motor_driver.py:326`
- `src/damiao_motor_driver.py:333`
- `src/damiao_motor_driver.py:628`
- `src/damiao_motor_driver.py:639`
- `tests/test_workstation.py:395`
- `tests/test_workstation.py:409`
- `tests/test_workstation.py:440`
- `docs/WORKSTATION_CHANGELOG.md:231`
- `docs/WORKSTATION_CHANGELOG.md:232`
- `docs/WORKSTATION_CHANGELOG.md:233`
- `docs/WORKSTATION_CHANGELOG.md:237`

### evidence

- Parser code requires both the `0x33/0x55` marker and a known little-endian `slave_id` before classifying a payload as a parameter frame.
- Regression tests verify that `0C5F557FF8001F1C` is retained as a status frame with nonzero position and temperatures, and that real fault status comes from the first byte.
- `0.6.3-single-id-safety` records the live L-J4 failure shape, the three focused passing tests, and continued support for L-J8 IDs `0x10/0x20`.

### related_tasks

- None
