---
title: OpenARM Arm CAN2.0 Communication Scan Contract
category: pattern
tags:
  - openarm
  - socketcan
  - can2.0
  - arm-scan
  - factory-cli
  - damiao
sources:
  - src/workstation.py:83
  - src/workstation.py:87
  - src/workstation.py:104
  - src/workstation.py:110
  - src/workstation.py:116
  - src/workstation.py:1090
  - src/workstation.py:1097
  - src/workstation.py:1445
  - src/workstation.py:5957
  - src/arm_can_scan_cli.py:94
  - src/arm_can_scan_cli.py:166
  - scan_arm_can.sh:1
  - tests/test_arm_can_scan_cli.py:93
  - README.md:145
confidence: high
---

# OpenARM Arm CAN2.0 Communication Scan Contract

OpenARM 的整臂 `CAN2.0` 扫描在 `socketcan` 主链路下是只读通信盘点流程，只做 `ESC_ID / MST_ID / 状态` 对账与报告落盘，不把“整臂扫描”当成动作测试。

## Contract

- UI/外部兼容入口仍允许使用 `arm_verification`，但内部 canonical job type 已映射为 `arm_comm_scan`，所以后续代码和文档应优先把它视为“通信扫描”，不是“复检动作测试”。
- `socketcan` transport 在产品配置里明确标为 `SocketCAN (CAN2.0)`，对应的 job label 是“机械臂通信扫描”。
- 通信扫描默认 inventory 范围是 `0x01..0x20`，并可按 profile 收窄到期望 `ESC_ID` 集合。
- 产线前置确认里已经把该步骤定义为“只做通信复核，不作为动作测试”，这条约束应保持在 CLI、Web 和 SOP 三处一致。

## Runtime Behavior

- 整臂扫描入口是 `WorkstationService._run_arm_comm_scan()`。
- 默认 `allow_motion=False`，summary 中会把 `command_check_mode` 固定成 `safe_readonly`，且 `command_test_total / passed / failed` 都置为 `0`。
- 通过条件来自总线盘点和一致性检查，而不是动作响应：缺失节点、重复 `ESC_ID`、意外节点、ID/模式/波特率不匹配、健康状态异常都会让扫描失败。
- 该扫描会把结果写入 job 的 `scan_summary`，用于后续报告、验收和出货 checklist。

## CLI Contract

- 产线 CLI 是 `python3 -m src.arm_can_scan_cli`，默认参数为 `--channel can0 --bitrate 1000000 --profile openarm_v1`。
- shell wrapper `./scan_arm_can.sh` 只是这个 CLI 的薄包装；无参数时读取 `OPENARM_CAN_CHANNEL`、`OPENARM_CAN_BITRATE`、`OPENARM_CAN_PROFILE`、`OPENARM_SCAN_OUTPUT_DIR`，有参数时原样透传给 Python CLI。
- CLI 必落盘 `scan_summary.json` 和 `joint_results.csv`；存在意外节点时额外生成 `unexpected_nodes.csv`，同时复制工站生成的 `report.html`、`job.json`、`events.jsonl`。
- CLI 退出码约定是 `0=PASS`、`2=FAIL`，方便产线脚本和上层编排器直接按进程结果判定是否放行。

## Maintenance Notes

- 如果未来需要把扫描链路切到外部 `dmcan` 实现，优先保持 CLI 入口、输出文件名和退出码不变，把底层驱动替换限制在 `WorkstationService` 或适配层内部。
- 如果未来新增“带动作的整臂验收”，应继续把它放在独立 job type，而不是让 `arm_comm_scan` 变成“有时只读、有时动作”的双语义入口。

## Provenance

### sources

- `src/workstation.py:83`
- `src/workstation.py:87`
- `src/workstation.py:104`
- `src/workstation.py:110`
- `src/workstation.py:116`
- `src/workstation.py:1090`
- `src/workstation.py:1097`
- `src/workstation.py:1445`
- `src/workstation.py:5957`
- `src/arm_can_scan_cli.py:94`
- `src/arm_can_scan_cli.py:166`
- `scan_arm_can.sh:1`
- `tests/test_arm_can_scan_cli.py:93`
- `README.md:145`

### evidence

- `MOTOR_CHECK_CONFIRMATIONS["no_motion_expected"]` 明确把通信扫描定义成“只做通信复核，不作为动作测试”。
- `LEGACY_JOB_TYPE_ALIASES` / `PUBLIC_JOB_TYPE_ALIASES` 把用户可见的 `arm_verification` 兼容到内部 `arm_comm_scan`。
- `_run_arm_comm_scan(..., allow_motion=False)` 会把 command check 结果固定为 `safe_readonly` 模式并仅执行总线盘点、一致性检查和结果汇总。
- `src.arm_can_scan_cli` 会调用 `scan_device(..., "arm_verification")` 和 `create_job(..., "arm_verification")`，但最终产出的是只读扫描报告与 CSV/JSON 工件。
- `tests/test_arm_can_scan_cli.py` 已验证 CLI 能生成 `scan_summary.json`、`joint_results.csv` 和 `report.html`。

### related_tasks

- None
