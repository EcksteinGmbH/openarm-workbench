# OpenARM x 达妙 电机测试工作站 V3 Spec

更新时间：2026-04-24  
状态：Proposed

## 1. Summary

本 spec 将当前仓库正式定义为一套融合：

- 达妙 Linux 上位机电机配置能力
- OpenARM 整臂扫描与验收能力
- 现场故障扫描与问题监测能力

的 Linux 本地 Web 工作站。

V3 的目标不是简单复刻达妙上位机，也不是只保留当前仓库的 OpenARM 扫描逻辑，而是把两者合成一套更适合 OpenARM 产线、返修和验收工位的统一工具。

V3 仍保留当前工作台的单屏约束：

- `1920x1080`
- 浏览器缩放 `100%`
- 不允许页面级纵向滚动
- 不同层级功能必须通过主 Tab / 子 Tab 切换

## 2. Design Inputs

### 2.1 OpenARM canonical truth

V3 以 OpenARM 官方链路作为机械臂真值来源：

- `J1`, `J2` -> `DM-J8009P-2EC`
- `J3` -> `DM-J4340P-2EC`
- `J4` -> `DM-J4340-2EC`
- `J5`, `J6`, `J7`, `J8` -> `DM-J4310-2EC`

标准 ID 映射：

- `ESC_ID`: `0x01 .. 0x08`
- `MST_ID`: `0x11 .. 0x18`

默认 profile：

- [openarm_v1.yaml](/home/ubuntu/Projects/OpenARM/profiles/openarm/openarm_v1.yaml)

### 2.2 Damiao Linux tool reference

V3 将达妙 Linux `AppImage` 作为功能分区和字段能力的重要参考来源。

已确认可见的上位机能力包括：

- 串口 / CAN 双连接模式
- CAN 发收与抓包页
- 参数配置页
- 电机参数、控制参数、驱动参数、通信参数分组
- `ESC_ID` / `MST_ID` / `canBaud` / `CTRL_MODE`
- `ReadAllParam` / `WriteAllParam`
- 校准 / 零位入口
- 调试 / 日志 / CANOpen / PDO Mapping / 固件升级

参考解包位置：

- [tmp/dmtool_appimage](/home/ubuntu/Projects/OpenARM/tmp/dmtool_appimage)
- [ui_mainwindow.h](/home/ubuntu/Projects/OpenARM/tmp/dmtool_appimage/squashfs-root/serial-port-assistant_autogen/include/ui_mainwindow.h)

### 2.3 Product positioning

V3 的产品定位是：

`OpenARM 机械臂测试工作站`

一句话定义：

一套 Linux 本地工位软件，用于电机 ID 配置、参数配置、CAN 接口管理、整臂扫描、故障定位、验收放行和报告输出。

## 3. Product Goals

V3 必须完成以下目标：

1. 在 Linux 下替代达妙上位机中与 OpenARM 工位直接相关的核心配置能力。
2. 将 OpenARM 的整臂扫描、ID 盘点和放行验收纳入统一流程。
3. 单独提供一页“问题扫描监测”，用于现场快速判断掉线、错配、过温、参数异常和保存失败等问题。
4. 将操作流程收敛为工位式单主按钮流，降低操作员学习成本。

## 4. Non-Goals

V3 不包含：

- ROS2 正式控制站
- 长时间自动巡检
- 连续轨迹控制
- 双臂协同控制
- MES / ERP 集成
- 完整复刻达妙上位机中的所有 CANOpen / PDO 高级工程功能

说明：

- V3 会保留未来扩展位，但默认工位 UI 不暴露这些高级工程页。

## 5. Functional Scope

### 5.1 必须具备

- 系统 CAN 接口识别与配置
- 单电机 ID 配置
- 单电机波特率配置
- 单电机运行模式配置
- 单电机参数读取、写入、回读、保存
- 单电机零位校准
- 单电机低风险动作测试
- 整臂电机 ID 扫描
- 整臂参数与模式一致性扫描
- 整臂验收放行
- 问题扫描监测页
- HTML / JSON 工件报告

### 5.2 可保留但不作为主流程

- 手工 CAN 发帧
- 手工 CAN 抓包
- CANOpen / PDO Mapping
- 固件升级入口

说明：

- 这些能力只允许进入 `工程模式`，不进入标准工作流。

## 6. Task Model

V3 标准任务固定为 6 类。

### 6.1 `can_interface_setup`

目标：

- 识别 `can0 / can1`
- 识别 `gs_usb / DM-USB2FDCAN`
- 配置 `CAN 2.0 / CAN FD`
- 设置 `bitrate / dbitrate`
- `up / down` 通道

### 6.2 `single_id_config`

目标：

- 识别单电机
- 修改 `ESC_ID`
- 修改 `MST_ID`
- 修改 `can_br`
- 修改 `CTRL_MODE`
- 修改 `TIMEOUT`
- 回读校验
- 保存 Flash

### 6.3 `single_param_config`

目标：

- 读取完整参数
- 修改运行参数
- 修改控制参数
- 修改通信参数
- 回读校验
- 保存 Flash

说明：

- 该任务对齐达妙上位机中“参数页”的能力，但在工位模式下只开放白名单字段。

### 6.4 `single_motor_commissioning`

目标：

- 绑定 OpenARM 目标 Joint
- 完成建站参数写入
- 保存 Flash
- 零位
- 低风险测试

### 6.5 `arm_bus_scan`

目标：

- 扫描整条手臂总线上的全部电机
- 输出在线、缺失、意外、重复 ID
- 输出每个 Joint 的 `ESC_ID / MST_ID / can_br / CTRL_MODE / 状态`

### 6.6 `arm_acceptance`

目标：

- 按 OpenARM profile 对整臂做一致性验收
- 生成 `PASS / HOLD`
- 输出 blocking reasons

## 7. UI Information Architecture

### 7.1 Top-level tabs

V3 顶层主 Tab 固定为：

- `任务`
- `连接`
- `识别`
- `执行`
- `监测`
- `报告`

### 7.2 Tab responsibilities

#### `任务`

负责：

- 选择任务类型
- 选择 transport
- 选择 profile
- 选择目标 Joint
- 启用专家模式

#### `连接`

负责：

- 查看 USB-CAN 识别结果
- 配置 Linux CAN 通道
- 建立 `serial_bridge / socketcan` 连接

#### `识别`

负责：

- 单电机识别
- 总线 ID 盘点
- 整臂任务预扫描
- 当前参数与目标参数对照

#### `执行`

负责：

- 按主流程执行当前任务
- 对单电机任务显示 `ID / 参数 / 保存 / 零位 / 测试`
- 对整臂任务只显示扫描 / 验收相关命令

#### `监测`

负责：

- 问题扫描
- 风险分组
- 故障归类
- 现场排障建议

#### `报告`

负责：

- 任务摘要
- per-motor / per-joint 明细
- 参数改动记录
- blocking reasons
- 工件目录

## 8. Interaction Model

### 8.1 Single-primary-action workflow

V3 所有核心页必须采用统一的“下一步主按钮”模式：

- 连接页：只提示一个下一步
- 识别页：只提示一个下一步
- 执行页：只提示一个下一步

标准要求：

- 当前不能执行的流程命令从主视图中隐藏
- 不允许长期显示一排不可点击按钮
- 主流程按钮必须给出：
  - 当前步骤名称
  - 执行目的
  - 是否可执行

### 8.2 Engineering tools separation

工程工具必须与标准流程分离：

- 标准流程：默认可见
- 工程工具：折叠区或单独模式

工程工具包括：

- 手工 CAN 发帧
- CAN 抓包
- CANOpen / PDO
- 固件升级
- 自定义参数写入

## 9. Parameter Model

### 9.1 Standard editable fields

标准工位模式下允许修改的字段白名单：

- `ESC_ID`
- `MST_ID`
- `CTRL_MODE`
- `TIMEOUT`
- `can_br`
- `PMAX`
- `VMAX`
- `TMAX`
- `KT_Value`
- `Gr`

### 9.2 Read-only fields

默认只读字段：

- `SN`
- `sw_ver`
- `sub_ver`
- `Flux`
- `Rs`
- `Ls`
- `Inertia`
- 其他硬件固化参数

### 9.3 Expert mode

专家模式允许：

- 打开更多参数字段
- 允许手工输入当前 ID
- 允许跳过 OpenARM Joint 绑定

约束：

- 必须填写原因
- 所有覆盖项必须记录到报告

## 10. Problem Scan Monitor Page

### 10.1 Goal

该页面用于吸收客户反馈中最常见的现场问题，给出一眼可见的故障分组和排障建议。

### 10.2 Page layout

页面固定为三栏：

- 左侧：问题分类与过滤器
- 中间：节点 / Joint 诊断矩阵
- 右侧：当前选中问题的解释与建议动作

### 10.3 Built-in issue categories

V3 首版必须内置以下问题分类：

- `offline_node`
- `duplicate_esc_id`
- `unexpected_node`
- `mst_id_mismatch`
- `can_br_mismatch`
- `ctrl_mode_mismatch`
- `param_read_failed`
- `save_flash_failed`
- `motor_fault`
- `mos_overtemp`
- `rotor_overtemp`
- `zero_failed`
- `test_failed`

### 10.4 Diagnostic output

每个问题项必须输出：

- `severity`
- `joint_or_node`
- `detected_value`
- `expected_value`
- `probable_cause`
- `recommended_action`

### 10.5 Severity model

严重级别固定为：

- `critical`
- `warning`
- `info`

默认判定：

- 掉线、重复 ID、保存失败、严重故障 -> `critical`
- 参数不一致、模式错误、波特率错误 -> `warning`
- 非阻断提示 -> `info`

## 11. API Contract

### 11.1 Existing APIs retained

保留现有接口族：

- `/api/system/can-interfaces*`
- `/api/device/*`
- `/api/jobs/*`

### 11.2 New task endpoints

V3 新增或明确化以下任务动作：

- `POST /api/jobs/{job_id}/run-id-config`
- `POST /api/jobs/{job_id}/run-param-config`
- `POST /api/jobs/{job_id}/run-bus-scan`
- `POST /api/jobs/{job_id}/run-acceptance`
- `POST /api/jobs/{job_id}/run-problem-scan`

### 11.3 Monitor endpoints

新增：

- `GET /api/jobs/{job_id}/issues`
- `GET /api/jobs/{job_id}/issues/summary`

响应固定包含：

- `issues[]`
- `summary`
- `severity_counts`

## 12. State Machine

### 12.1 Shared states

统一状态集合：

- `draft`
- `device_connected`
- `identified`
- `profile_selected`
- `params_written`
- `params_verified`
- `params_saved`
- `zeroed`
- `tested`
- `inventory_ready`
- `acceptance_ready`
- `reported`
- `passed`
- `failed`
- `cancelled`

### 12.2 Single motor flow

标准单电机建站流转：

`device_connected -> identified -> profile_selected -> params_written -> params_verified -> params_saved -> zeroed -> tested -> reported -> passed`

### 12.3 Arm flow

标准整臂扫描流转：

`device_connected -> inventory_ready -> acceptance_ready -> reported -> passed`

### 12.4 Failure rules

以下情况必须进入 `failed`：

- 参数回读不一致
- 保存 Flash 失败
- 零位失败
- 测试失败
- 整臂出现 blocking reason
- 设备通信中断

## 13. Report Artifacts

每个 job 固定输出到：

- `artifacts/jobs/{timestamp}_{job_id}/`

必须包含：

- `job.json`
- `motors/{slot_or_joint}.json`
- `events.jsonl`
- `report.html`
- `issues.json`

`issues.json` 为 V3 新增工件，用于问题监测页与后续统计分析。

## 14. Acceptance Criteria

### 14.1 Functional acceptance

必须满足：

- 能在 Linux 下识别 `DM-USB2FDCAN / gs_usb`
- 能修改单电机 `ESC_ID / MST_ID / can_br / CTRL_MODE`
- 能完成参数回读与保存
- 能完成单电机零位和低风险测试
- 能扫描整条手臂的全部电机
- 能显示每个 Joint 的模式和参数摘要
- 能生成整臂 `PASS / HOLD`
- 能在监测页里输出问题分类和建议动作

### 14.2 UX acceptance

必须满足：

- `1920x1080` 下单屏完成
- 不允许页面级滚动
- 当前不可执行的流程命令不得在主流程区长期显示
- 连接页、识别页、执行页都必须有单一“下一步”主按钮

### 14.3 Safety acceptance

必须满足：

- 所有高风险动作都有确认对话框
- 专家模式改动全部留痕
- 保存 Flash 前必须回读校验
- 零位和测试前必须检查状态与温度

## 15. Implementation Plan

### P0. Spec freeze

- 冻结字段白名单
- 冻结监测页问题分类
- 冻结标准工位 UI 结构

### P1. 达妙配置能力并入

- 新增单独的 `ID` 和 `参数` 执行流
- 对齐达妙上位机参数分组
- 完成 `single_param_config`

### P2. OpenARM 整臂扫描增强

- 完成整臂参数摘要表
- 输出每个 Joint 的 `ESC_ID / MST_ID / can_br / CTRL_MODE`
- 优化整臂验收 blocking reasons

### P3. 问题扫描监测页

- 输出结构化问题分类
- 支持 severity 过滤
- 支持建议动作侧边栏

### P4. 工程模式隔离

- 将 CANOpen / PDO / 抓包 / 手工发帧收口到工程模式

## 16. Open Questions

以下项目需要后续结合客户问题反馈继续收敛：

- 问题监测页的最终问题分类优先级
- 是否需要加入“保存次数风险提示”
- 是否需要加入“参数与 OpenARM BOM 不匹配”专项告警
- 是否需要加入“适配器异常 / 通道异常”专项建议

在未收到更多客户反馈前，V3 以本 spec 的内置问题分类作为默认实现基线。
