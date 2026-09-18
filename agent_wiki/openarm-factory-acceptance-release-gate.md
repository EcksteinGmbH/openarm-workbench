---
title: OpenARM Factory Acceptance Release Gate
category: decision
tags:
  - openarm
  - factory-acceptance
  - release-gate
  - sign-off
  - demo
  - zero-calibration
sources:
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:18
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:63
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:79
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:239
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:263
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.html:123
  - artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.html:377
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:11
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:57
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:73
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:233
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:257
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:265
  - artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.html:77
  - agent_wiki/openarm-arm-can20-comm-scan.md:31
confidence: high
---

# OpenARM Factory Acceptance Release Gate

OpenARM 整臂客户出厂报告只有在 release gate 为 PASS、无 blocking/unresolved warnings、覆盖静态扫描/电机参数/动态零位/官方 Demo，并完成签核后，才应作为客户交付版；只读 CAN2.0 通信扫描不能替代动态整臂验收。

## Release Criteria

- 报告类型应是 `factory_acceptance_report`，对象应绑定整臂序列号、机型和 BOM profile。
- `release_decision` / final conclusion 必须为 `PASS`，且 blocking items 为空；如果 warning 存在，报告不能裸发，必须记录复核处置或重跑生成无 unresolved warning 的最终版。
- 总线健康项应覆盖 `can0`、CAN 2.0、1 Mbps、`ERROR-ACTIVE` 和 CAN 错误计数为 0。
- 静态整臂验收应覆盖 profile 扫描、缺失节点、ID 不匹配、重复 `ESC_ID`、逐关节状态反馈、控制参数和 raw frame/readback evidence。
- 动态验收应至少覆盖官方动态零位、post-zero recovery 或 power-cycle verification、官方 Step 5 Demo、Demo final samples 和 safe disable。
- 客户正式包应保留报告 PDF，同时保留 JSON/HTML 或 evidence hash，使报告结论可以回溯到机器可读数据。

## Sign-Off Policy

- `Test Operator` 签核表示测试按记录执行。
- `Project Lead` / reviewer 签核表示 release gate、warning、动态零位和 Demo 结果已复核。
- `Quality Approval` 为空时，报告可作为工程验收证据，但客户最终交付包应补质量批准签名，或在交付记录中明确质量批准由外部流程覆盖。
- 如果客户要求单电机追溯，而报告只按整臂序列号和关节标签追溯，应在交付说明中写明边界；这不阻塞整臂追溯制的出厂报告，但不能冒充电机内部 SN 追溯。

## Boundary With CAN2.0 Scan

[[openarm-arm-can20-comm-scan]] 定义的整臂 `CAN2.0` 扫描是只读通信盘点，只做 `ESC_ID / MST_ID / 状态` 对账与报告落盘。它可以作为 factory acceptance 的静态前置证据，但不能单独证明运动方向、力矩控制、gripper command、动态零位或 safe disable。

## Provenance

### sources

- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:18`
- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:63`
- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:79`
- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:239`
- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.json:263`
- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.html:123`
- `artifacts/reports/OAL26051101_right_arm_20260511/20260511_095417_3f9c34d85a56.html:377`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:11`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:57`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:73`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:233`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:257`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.json:265`
- `artifacts/reports/OAL26051101_left_arm_20260512/OpenARM_Leader_Left_Arm_Factory_Test_Report_20260512.html:77`
- `agent_wiki/openarm-arm-can20-comm-scan.md:31`

### evidence

- Right-arm final report records `release_ready=true`, `release_decision=PASS`, no blocking items, no warnings, CAN health before/after Demo, official dynamic zero calibration, clean official Step 5 Demo, and sign-off tables.
- Left-arm report records `release_decision=PASS`, static scan/zero/low-gain enable/demo PASS, CAN health PASS, evidence hashes, and sign-off tables.
- Existing CAN scan wiki records that CAN2.0 communication scan is a read-only inventory process, so dynamic factory acceptance must remain a separate release criterion.

### related_tasks

- None
