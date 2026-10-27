---
task: openarm2-factory-canfd
title: OpenArm 2.0 出厂工作站 CAN-FD 真机闭环
summary: >-
  以官方拓扑和 CAN-FD 1M/5M 运行模式完成 OpenArm 2.0 出厂工作站，先做可回退的 R-J1 试点，再继续整臂验收和客户报告。
app: workstation
status: paused
progress: 60
priority: high
next_action: user_and_codex
created: 2026-10-23
updated: 2026-10-23
---

# OpenArm 2.0 出厂工作站 CAN-FD 真机闭环

## 范围

- 当前只完善 OpenArm 2.0；OpenArm 1.0 路径和历史证据冻结，收到 1.0 订单后另行优化。
- 目标臂为右臂 `OAF26093001`，目标总线 `can0`，J1-J8 使用 ESC `0x01-0x08`、MST `0x11-0x18`。
- 目标运行模式为 CAN-FD：仲裁速率 1 Mbps、数据速率 5 Mbps、BRS。
- 所有出厂结论必须来自同一整臂、同一侧、同一 Profile 的真机证据。

## 当前工作

- **阶段**: 已暂停；等待 R-J1 单电机可回退 CAN-FD 试点。
- **下一步**: 用户只连接并上电 R-J1 后，由 Codex 协助按“经典 CAN 1M 基线读取 → `change_baud 5M --save` → 断电重上电 → CAN-FD 1M/5M 下真实 FD+BRS 读参与通信复核 → 切回 1M → 再断电复核”执行并记录。
- **阻塞**: 需要用户下次准备好隔离的 R-J1、供电、急停和人工断电重上电；试点通过前不得对整臂写入 5M。

## 本轮已完成

- 工作站版本更新到 `0.33.0-openarm2-official-topology-fd-session`。
- OpenArm 2.0 拓扑改为官方布局：右臂 `can0`、左臂 `can1`，两侧分别使用 ID 1-8；1.0 历史布局保持不变。
- CAN-FD 会话已从 Web 请求贯通到 `DamiaoSocketCANDriver(fd=True)`，经典会话与 FD 会话不会错误复用。
- 官方 `openarm_can 1.4.0` CLI 已构建并由 `tools/openarm-can-cli` 包装调用。
- 自动化验证完成：`292 passed`；前端脚本检查、Python 编译检查和 diff 检查均通过。
- 真机 `OAF26093001` 已有：建档、连接自检、经典 CAN 静态验收、TIMEOUT 参数标准化、经典 CAN 低增益使能检查通过；放行状态保持 `HOLD`。

## 已确认的 CAN 工艺决定

- 官方推荐/默认 CAN-FD 指最终运行接口，不表示所有配置帧都必须是 CAN-FD 帧。
- 官方 ID 默认教程使用 UART；`openarm-can-cli change_id` 和 `change_baud` 使用经典 CAN 标准配置帧。
- 已完成的经典 CAN 1M 静态结果保留为“切换前基线”，不重做、不覆盖。
- 切换 5M 并重上电后，必须增加一轮 CAN-FD 1M/5M 的关键静态复核；只把接口设为 FD 后发送经典帧，不足以证明 5 Mbps 数据阶段和 BRS。
- 之前经典 CAN 下通过的低增益使能检查保留为安全证据；最终放行前还要在 CAN-FD 下复测一次。

## 安全边界

- R-J1 试点前只接一颗电机，先确认接口和当前 `can_br=4`，禁止直接对整臂执行切换。
- 每次 `--save` 后必须断电重上电；Flash 写入不得循环或反复尝试。
- 试点必须先证明 5M 下可通信并能恢复到 1M，才允许解锁整臂 CAN-FD 步骤。
- 下次开始先检查工作区、工作站版本、`can0` 状态和 R-J1 实际接线，不根据本页假定硬件仍保持连接。

## 相关证据

- 方案与顺序：`docs/ARM_WORKSTATION_V5_DUAL_VERSION_PLAN.md`
- 官方摘录：`docs/official/setup-tutorial.md`
- 运行态交接：`agent_wiki/runtime/handoff-single-motor-commissioning-20260917.md`
- Context manifest：`docs/context-manifest.yaml`

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 固定 2.0 官方双总线拓扑，打通工作站 FD 会话；确认“经典前测 + FD 终测”两阶段证据模型，并暂停等待 R-J1 真机试点 |
