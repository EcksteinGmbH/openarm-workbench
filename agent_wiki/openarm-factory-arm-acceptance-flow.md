---
title: OpenARM Factory Arm Acceptance Flow
category: decision
tags:
  - openarm
  - factory-flow
  - damiao
  - commissioning
  - calibration
  - timeout
  - zero-calibration
  - demo
sources:
  - src/workstation.py:1119
  - src/workstation.py:1121
  - src/workstation.py:1124
  - src/workstation.py:1125
  - src/workstation.py:1126
  - src/workstation.py:1127
  - src/workstation.py:1146
  - src/workstation.py:1148
  - src/workstation.py:1149
  - src/workstation.py:3908
  - src/workstation.py:3937
  - src/workstation.py:3983
  - src/workstation.py:3986
  - src/workstation.py:3994
  - src/workstation.py:4009
  - docs/WORKSTATION_CHANGELOG.md:17
  - docs/WORKSTATION_CHANGELOG.md:23
  - docs/WORKSTATION_CHANGELOG.md:26
  - docs/WORKSTATION_CHANGELOG.md:228
  - docs/WORKSTATION_CHANGELOG.md:229
  - docs/WORKSTATION_CHANGELOG.md:230
  - docs/WORKSTATION_CHANGELOG.md:245
  - docs/WORKSTATION_CHANGELOG.md:246
  - docs/DAMIAO_CALIBRATION_POLICY.md:38
  - docs/DAMIAO_CALIBRATION_POLICY.md:42
  - docs/DAMIAO_CALIBRATION_POLICY.md:44
  - docs/DAMIAO_CALIBRATION_POLICY.md:54
  - docs/DAMIAO_CALIBRATION_POLICY.md:70
confidence: high
---

# OpenARM Factory Arm Acceptance Flow

OpenARM 组装整臂出厂测试应按“静态通信验收 -> 按 Profile 标准化 TIMEOUT -> 官方动态零位 -> 恢复初始姿态 -> 官方 Demo -> 正式报告”的顺序执行，单电机 ID 调试阶段不默认写 operational TIMEOUT 或保存整臂零点。

## Factory Sequence

- 单电机 ID 调试阶段只处理通信身份和必要基础参数；`single_motor_timeout_write_default` 为 `False`，不把 operational TIMEOUT 写入作为 loose-motor 默认动作。
- 整臂阶段先做静态通信验收，确认期望 `ESC_ID / MST_ID / CTRL_MODE / can_br / TIMEOUT`、状态读取和故障状态。
- TIMEOUT 标准化属于 `whole_arm_factory_acceptance_before_dynamic_zero_and_demo` 阶段，并且模式是 `profile_per_joint`。
- 当前工站配置把右臂和左臂 J1-J8 都定义为 `TIMEOUT=5000`；后续判断应读取 Profile 和 commissioning policy，而不是硬编码旧的 `1000`。
- 官方动态零位是整臂零点保存阶段；完成后恢复初始姿态，再执行官方 Demo 和正式报告生成。

## Single-Motor Service Boundary

- loose-motor ID 建站默认只写通信身份所需的 `ESC_ID / MST_ID / CTRL_MODE / can_br`；`Gr / KT_Value / PMAX / VMAX / TMAX` 只读并记录，除非另有获批的参数维护任务。
- `TIMEOUT` 在单电机阶段默认只读；当前 operational `TIMEOUT=5000` 应在装配完成后的整臂验收阶段按 Profile 写入和复核。
- 电机编码器校准和输出轴编码器校准属于达妙上位机或批准夹具执行的供应商维护操作，不得自动并入 CAN ID 建站。
- loose motor 没有最终装配机械基准，因此默认不得保存整臂 operational zero；OpenARM 零位只在装配整臂的官方动态零位流程中保存。
- 工站对 vendor maintenance 的职责是启动工具并保存人工记录；`automatic_encoder_calibration=False`，不能把“已记录”冒充“工站已自动执行并验证”。

## Safety Contract

- `arm_timeout_standardization()` 要求显式确认已经完成静态扫描、当前处于整臂验收阶段并且急停/断电可用。
- TIMEOUT 标准化按关节执行 `disable -> read TIMEOUT -> write TIMEOUT -> readback -> save Flash -> readback`。
- 该动作明确 `motion_command_sent=False`，不发送运动控制命令，但它会保存参数到 Flash，所以仍属于需要人工确认的参数写入动作。
- 每个关节只有在无 issues 且 `after_save == target_timeout` 时才标记通过。

## Maintenance Notes

- 如果未来达妙或 OpenARM 官方重新定义不同关节的 TIMEOUT，优先更新 Profile 和 `commissioning_policy.whole_arm_timeout_policy`，不要在 UI、报告或脚本里另写常量。
- 如果工作站出现“右臂和左臂 TIMEOUT 规则不一致”，先检查 `docs/WORKSTATION_CHANGELOG.md` 中最近 TIMEOUT 版本段和 `src/workstation.py` 的 `commissioning_policy` 是否一致。
- 通信扫描契约见 [[openarm-arm-can20-comm-scan]]；通信扫描仍然是只读验收，不应被混入动态 Demo 行为。

## Provenance

### sources

- `src/workstation.py:1119`
- `src/workstation.py:1121`
- `src/workstation.py:1124`
- `src/workstation.py:1125`
- `src/workstation.py:1126`
- `src/workstation.py:1127`
- `src/workstation.py:1146`
- `src/workstation.py:1148`
- `src/workstation.py:1149`
- `src/workstation.py:3908`
- `src/workstation.py:3937`
- `src/workstation.py:3983`
- `src/workstation.py:3986`
- `src/workstation.py:3994`
- `src/workstation.py:4009`
- `docs/WORKSTATION_CHANGELOG.md:17`
- `docs/WORKSTATION_CHANGELOG.md:23`
- `docs/WORKSTATION_CHANGELOG.md:26`
- `docs/WORKSTATION_CHANGELOG.md:228`
- `docs/WORKSTATION_CHANGELOG.md:229`
- `docs/WORKSTATION_CHANGELOG.md:230`
- `docs/WORKSTATION_CHANGELOG.md:245`
- `docs/WORKSTATION_CHANGELOG.md:246`
- `docs/DAMIAO_CALIBRATION_POLICY.md:38`
- `docs/DAMIAO_CALIBRATION_POLICY.md:42`
- `docs/DAMIAO_CALIBRATION_POLICY.md:44`
- `docs/DAMIAO_CALIBRATION_POLICY.md:54`
- `docs/DAMIAO_CALIBRATION_POLICY.md:70`

### evidence

- `/api/config` 的 `commissioning_policy` 声明单电机阶段不默认写 TIMEOUT、不默认保存单电机零点，整臂 TIMEOUT 标准化发生在动态零位和 Demo 之前。
- `arm_timeout_standardization()` 从 Profile 读取每个 joint 的 `target_timeout`，执行写入、回读、保存 Flash、再次回读，并用 `after_save == target_timeout` 判定通过。
- `0.6.16-left-timeout-unification` 更新日志记录左臂已统一到与右臂相同的 J1-J8 `TIMEOUT=5000` 策略，并通过 no-motion readback 验证。
- `commissioning_policy` 和 `vendor_tools` 明确编码器校准、单电机零位、单电机 TIMEOUT 写入均不是默认动作，vendor maintenance 只保存人工执行记录。
- 校准政策和 `0.6.3-single-id-safety` 把通信身份配置、供应商编码器维护、整臂 operational zero 与 TIMEOUT 标准化划分为不同阶段。

### related_tasks

- None
