# OpenARM 机械臂电机通信测试工作站 V1 Spec

## 1. 文档目的

本 spec 用于把当前仓库从“Damiao 电机调试页面”收敛为一套面向 OpenARM 装配与验收流程的通信测试工作站。

V1 的重点不是让电机跑起来，而是高效、稳定、可追溯地完成：

- 单电机 CAN 身份参数配置
- 单电机通信校验
- 整臂 8 电机通信扫描与对账
- 结果归档与报告输出

本 spec 兼顾两个目标：

- 给开发实现提供明确边界和接口约束
- 给产线/实验室使用提供统一流程定义


## 2. 背景与调研结论

### 2.1 OpenARM 官方流程

依据 OpenARM 当前公开文档，官方推荐流程实际上分成两段：

#### 阶段 A：ID 设置

- 设备：`Damiao USB CAN Debugger`
- 系统：`Windows`
- 软件：达妙调试助手 / 调试上位机

#### 阶段 B：后续建站与控制

- 设备：`SocketCAN-compatible interface device`
- 系统：`Ubuntu 22.04/24.04` 或其他支持 SocketCAN 的 Linux

在 Linux 侧，后续关键步骤是：

1. 配置 `SocketCAN`
2. 测试基本通信
3. 设置 `can_br`
4. 设置零位
5. 运行通信校验

OpenARM 当前公开的 Joint 映射为：

| Joint | ESC / Sender ID | MST / Receiver ID |
|------|------------------|-------------------|
| J1 | `0x01` | `0x11` |
| J2 | `0x02` | `0x12` |
| J3 | `0x03` | `0x13` |
| J4 | `0x04` | `0x14` |
| J5 | `0x05` | `0x15` |
| J6 | `0x06` | `0x16` |
| J7 | `0x07` | `0x17` |
| J8 | `0x08` | `0x18` |

OpenARM 的通信检查命令 `openarm-can-motor-check 1 17 can0` 也说明官方关注点是：

- ID 是否正确
- baudrate 是否一致
- 节点状态是否正常

### 2.2 OpenARM 当前官方电机型号

依据 OpenARM BOM 页面，当前电机型号与 Joint 的关系为：

| Joint | Official Model |
|------|----------------|
| J1, J2 | `DM-J8009P-2EC` |
| J3 | `DM-J4340P-2EC` |
| J4 | `DM-J4340-2EC` |
| J5, J6, J7, J8 | `DM-J4310-2EC` |

V1 的 profile 应优先保留这些官方商品型号，而不是只保留底层驱动抽象型号。

### 2.3 Damiao SDK / 通讯说明

Damiao 文档与 SDK 能力显示，初始化和通信检查真正需要的是：

- `read_motor_param()`
- `change_motor_param()`
- `save_motor_param()`
- `refresh_motor_status()`

其中关键寄存器包括：

- `ESC_ID`
- `MST_ID`
- `CTRL_MODE`
- `TIMEOUT`
- `can_br`
- `sw_ver`
- `sub_ver`
- `SN`

已知约束：

- `Master ID` 不应为 `0x00`
- 推荐 `MST_ID = ESC_ID + 0x10`
- 参数写入后必须回读校验
- Flash 写入次数有限，不应把“保存”设计成高频动作

### 2.4 当前仓库现状

当前仓库已经具备以下基础：

- `serial_bridge` 下的单电机识别与参数写入
- `socketcan` 下的整臂扫描基础
- profile 化的 OpenARM Joint 模板
- 工件落盘与 HTML 报告

但当前界面与任务模型仍带有较强的“动作调试台”特征，导致通信测试主流程不够聚焦。


## 3. 产品定位

### 3.1 V1 产品名称

建议名称：

`OpenARM Arm Communication Workstation`

中文名称：

`OpenARM 机械臂电机通信测试工作站`

### 3.2 一句话定义

一套用于配置 Damiao 电机 CAN 身份参数，并对 OpenARM 8 个关节执行总线盘点、参数一致性校验和通信验收报告输出的本地工站软件。

### 3.3 V1 的关键词

- 配 ID
- 查在线
- 查一致性
- 出报告

### 3.4 V1 非目标

以下能力不进入 V1 主流程：

- MIT / 位置 / 速度动作测试
- 零位自动化
- 轨迹控制
- 电机参数整定
- MES / 数据库联动
- Windows 打包

动作测试能力允许保留为后续工程模式扩展，但不作为当前交付验收项。

### 3.5 工程模式边界

为避免和当前代码能力完全脱节，V1 允许保留现有 `/zero`、`/test`、MIT 等接口，但必须遵守以下约束：

- 默认 UI 不显示这些入口
- 默认 `allowed_actions` 不向普通任务暴露这些动作
- 相关能力统一标记为 `engineering_mode`
- `engineering_mode` 不进入本 spec 的验收范围

换言之，V1 的正式状态机和验收规则只覆盖通信流程，不覆盖动作流程。


## 4. V1 用户与工位场景

### 4.1 目标用户

- 装配线操作员
- 研发调试工程师
- 售后返修工程师

### 4.2 工位分类

#### A. 单电机 ID 配置工位

特点：

- 一次只接 1 颗电机
- 重点是配置 `ESC_ID / MST_ID / can_br`
- 推荐 transport：`serial_bridge`

#### B. 单电机通信复核工位

特点：

- 不写参数
- 只读取、校验、出结论
- 可用于刷写后复核或问题定位
- 同一时刻只接 1 颗电机；若总线上存在多颗电机，必须切换专家模式并显式指定 `current_id`

#### C. 整臂 8 电机通信扫描工位

特点：

- 整条机械臂已经装配完成
- 各关节应已具备正确 ID
- 推荐 transport：`socketcan`
- 目标是整臂通信验收，不做动作控制


## 5. V1 任务模型

V1 统一定义 3 类任务：

### 5.1 `single_id_config`

目标：

- 识别当前电机
- 读取当前通信参数
- 绑定目标 Joint
- 写入目标 `ESC_ID / MST_ID / can_br / CTRL_MODE / TIMEOUT`
- 回读校验
- 可选保存 Flash
- 执行保存后通信复核

### 5.2 `single_comm_check`

目标：

- 识别当前电机
- 读取关键寄存器与状态
- 判断在线性、状态和温度是否正常
- 输出通过/失败结论

选机规则必须固定为：

- 标准模式下：扫描结果必须且只能有 1 个候选节点
- 若扫描到 0 个节点：任务直接失败，提示检查接线/供电/总线
- 若扫描到多个节点：任务直接失败，提示进入专家模式并手工指定 `current_id`
- 专家模式下：必须提供 `current_id`

### 5.3 `arm_comm_scan`

目标：

- 按 `openarm_v1` profile 对 J1~J8 逐关节检查
- 校验 ESC/MST ID、`can_br`、`CTRL_MODE`、节点状态
- 识别 unexpected node、missing joint、duplicate ID
- 输出整臂通信报告


## 6. UI 与信息架构

### 6.1 单屏约束

主页面必须满足：

- 在 `1920x1080`、浏览器缩放 100% 下不出现页面级纵向滚动
- 所有主流程功能在一个屏幕内完成
- 不同层级功能通过 Tab 切换，不使用长页面堆叠
- 不允许依赖“向下滚动页面”来完成主要操作
- 若信息超出当前区域，允许在局部面板内滚动，但不允许浏览器页面整体滚动

这是一条硬性约束，不是视觉建议。

### 6.2 主 Tab

顶层固定 5 个 Tab：

1. `任务`
2. `连接`
3. `识别`
4. `执行`
5. `报告`

### 6.2.1 分层切换规则

- 顶层功能只能通过主 Tab 切换
- 次级功能只能通过二级 Tab、segmented control 或等价的页签控件切换
- 不允许使用长表单折叠堆叠成单页
- 不允许通过页面跳转把主流程拆成多个独立页面

### 6.3 页面布局

固定三栏布局：

- 左侧：任务步骤与工位假设
- 中间：当前主操作区
- 右侧：实时状态与事件日志

布局要求：

- 左右侧栏高度固定，内容超出时仅栏内滚动
- 中间主操作区按当前 Tab 切换，不触发页面整体重排
- Tab 切换时不允许出现明显布局抖动或页面溢出

### 6.4 任务页

必须支持：

- 选择任务类型
- 选择 transport
- 选择 profile
- 选择目标 Joint
- 启用专家模式

行为要求：

- `single_id_config` 显示目标 Joint
- `single_comm_check` 不显示目标 Joint
- `arm_comm_scan` 固定以整臂 profile 为准

### 6.5 连接页

#### `serial_bridge`

显示：

- 串口名
- 串口波特率
- driver 连接状态
- capability 摘要

#### `socketcan`

显示：

- `channel`
- `bitrate`
- capability 摘要

### 6.6 识别页

#### 单电机任务

显示：

- 当前候选节点
- 实测 `ESC_ID`
- 实测 `MST_ID`
- 实测 `can_br`
- 当前状态

#### 整臂任务

显示：

- J1~J8 结果矩阵
- 扫描摘要卡片
- per-joint issue 列表

### 6.7 执行页

执行页的目标是“通信流程操作”，不是“动作控制台”。

二级 Tab 固定为：

- `配置`
- `校验`
- `工程`
- `扫描`

行为要求：

- `single_id_config` 显示 `配置 + 校验 + 扫描`
- `single_comm_check` 只显示 `扫描`
- `arm_comm_scan` 只显示 `扫描`
- `工程` 默认为隐藏/只读保留位，不进入 V1 验收
- 若启用工程模式，必须出现明确的非产线警示文案

执行页空间约束：

- 二级 Tab 内容必须在当前屏幕内完成展示
- 单个二级 Tab 不得依赖页面滚动来暴露主按钮
- 主动作按钮必须始终位于当前可见区域内

### 6.8 报告页

必须显示：

- 总体通过/失败
- 当前 job 元信息
- 失败原因
- 工件目录与文件列表

对于整臂扫描，必须额外显示：

- `missing joints`
- `unexpected ids`
- `duplicate esc ids`
- `bitrate mismatches`
- `ctrl mode mismatches`
- `motor faults`


## 7. Profile 规范

### 7.1 默认 profile

V1 默认 profile 为 `openarm_v1`。

默认映射必须与 OpenARM BOM 保持一致：

- `J1`, `J2` -> `DM-J8009P-2EC`
- `J3` -> `DM-J4340P-2EC`
- `J4` -> `DM-J4340-2EC`
- `J5`, `J6`, `J7`, `J8` -> `DM-J4310-2EC`

### 7.2 Joint 字段

每个 Joint 至少包含：

- `joint_name`
- `motor_type`
- `target_esc_id`
- `target_mst_id`
- `target_ctrl_mode`
- `target_timeout`
- `target_can_br`
- `expected_ctrl_mode`
- `expected_status`
- `required_online`
- `allow_write`
- `expected_bus`

### 7.2.1 字段语义

- `expected_status`：允许判定为“正常在线”的状态集合，V1 默认允许 `DISABLED` 和 `ENABLED`
- `required_online`：该 Joint 是否必须在线；V1 对 J1~J8 固定为 `true`
- `allow_write`：该 Joint 是否允许在标准模式下写入通信参数；V1 默认只对 `single_id_config` 生效

### 7.3 标准模式限制

标准模式下：

- 不允许修改 `motor_type`
- 不允许修改 `PMAX / VMAX / TMAX`
- 只能选择既定 Joint 模板

### 7.4 专家模式限制

专家模式下允许修改：

- `target_esc_id`
- `target_mst_id`
- `target_ctrl_mode`
- `target_timeout`
- `target_can_br`

专家模式的修改必须记录在 job 工件中。

### 7.5 profile 兼容与迁移规则

为兼容当前仓库中的旧 profile 字段，V1 采用以下策略：

- `requires_zero`：标记为 `deprecated`，V1 主流程忽略
- `test_profile`：标记为 `deprecated`，V1 主流程忽略
- 若 profile 同时存在 `expected_ctrl_mode` 与 `target_ctrl_mode`：
  - 配置阶段使用 `target_ctrl_mode`
  - 校验阶段优先使用 `expected_ctrl_mode`
- 若缺失 `expected_ctrl_mode`，则回退到 `target_ctrl_mode`

实现要求：

- 新代码不得再把 `requires_zero` / `test_profile` 作为 V1 主流程判定依据
- profile loader 必须能兼容读取旧字段，但报告中应标记其为 legacy 字段


## 8. 状态机

### 8.1 `single_id_config`

状态流：

- `draft`
- `device_connected`
- `profile_selected`
- `params_written`
- `params_verified`
- `params_saved`
- `checked`
- `passed`
- `failed`

### 8.2 `single_comm_check`

状态流：

- `draft`
- `device_connected`
- `identified`
- `checked`
- `passed`
- `failed`

### 8.3 `arm_comm_scan`

状态流：

- `draft`
- `device_connected`
- `profile_loaded`
- `bus_scanning`
- `inventory_built`
- `consistency_checked`
- `reported`
- `passed`
- `failed`

### 8.4 状态机与工程模式关系

- `zeroed`
- `tested`

以上状态允许继续存在于工程模式内部实现中，但不属于 V1 通信流程状态机。


## 9. 功能行为规范

### 9.1 设备连接

#### `POST /api/device/connect`

输入：

- `transport`
- `connection`

输出：

- `device_session_id`
- `capabilities`
- `connection_state`

### 9.2 设备扫描

#### `POST /api/device/scan`

输入：

- `device_session_id`
- `job_type`
- `profile_id`
- `current_id`
- `expert_mode`

输出：

- `candidates`
- `conflicts`
- `summary`
- `scan_mode`

行为要求：

- `single_id_config` / `single_comm_check` 使用单电机扫描
- `arm_comm_scan` 使用整臂 profile 扫描

扫描结果有效期约束：

- `scan` 结果属于 session 级快照
- 创建 job 后，job 只允许基于最近一次同类型扫描结果继续执行
- 若以下条件之一发生变化，job 必须失效并要求重新扫描：
  - transport 断开重连
  - profile 变更
  - 专家模式 `current_id` 变更
  - 扫描完成后检测到总线节点数量变化

失效处理规则：

- 不直接把 job 标记为 `failed`
- 但必须阻止后续执行动作
- UI 必须明确提示“扫描结果已失效，请重新扫描”
- 重新扫描成功后允许继续创建新 job；旧 job 保留为历史记录

### 9.3 创建任务

#### `POST /api/jobs`

输入：

- `job_type`
- `device_session_id`
- `profile_id`
- `target_joint`
- `expert_mode`

输出：

- `job_id`
- `status`
- `allowed_actions`

前置条件：

- 必须先完成对应任务类型的扫描
- `single_comm_check` 若为专家模式，必须提供 `current_id`

### 9.4 单电机目标加载

#### `POST /api/jobs/{job_id}/apply-profile`

只允许用于：

- `single_id_config`

输出：

- `target_config`
- `current_snapshot`

### 9.5 写入通信参数

#### `POST /api/jobs/{job_id}/write-params`

只允许用于：

- `single_id_config`

前置条件：

- transport 支持写参数
- 已选择目标 Joint

### 9.6 回读校验

#### `POST /api/jobs/{job_id}/verify-params`

前置条件：

- `write_params` 已完成

必须校验：

- `ESC_ID`
- `MST_ID`
- `CTRL_MODE`
- `TIMEOUT`
- `can_br`

### 9.7 保存 Flash

#### `POST /api/jobs/{job_id}/save-flash`

只允许用于：

- `single_id_config`

前置条件：

- 已通过回读校验
- transport 支持保存
- 当前参数与上次持久化参数存在差异
- 操作者已完成二次确认

保存约束：

- 若当前目标参数与回读参数完全一致，则禁止执行 `save_flash`
- 每次 `save_flash` 必须写入审计日志
- “上次持久化参数” 的比较基线定义为：
  - 默认使用本次任务开始时首次读取到的参数快照 `initial_persisted_params`
  - 若任务中未读取到完整快照，则禁止 `save_flash`
  - 不依赖外部数据库作为 V1 的唯一真值来源
- 审计信息至少包含：
  - 操作时间
  - job_id
  - 目标 `ESC_ID`
  - 目标 `MST_ID`
  - 目标 `can_br`
  - 是否发生实际写入

### 9.8 单电机通信校验

#### `POST /api/jobs/{job_id}/run-comm-check`

允许用于：

- `single_id_config`
- `single_comm_check`

校验内容：

- `ESC_ID`
- `MST_ID`
- `CTRL_MODE`
- `can_br`
- `status`
- `t_mos`
- `t_rotor`

行为要求：

- `single_id_config` 的“保存后复核”与 `single_comm_check` 共用同一套判定逻辑
- `single_comm_check` 不得发送动作控制帧

### 9.9 整臂通信扫描

#### `POST /api/jobs/{job_id}/run-arm-scan`

只允许用于：

- `arm_comm_scan`

校验内容：

- J1~J8 是否全部 present
- `MST_ID == target_mst_id`
- `can_br == target_can_br`
- `CTRL_MODE == expected_ctrl_mode`
- 节点状态是否 healthy
- 是否存在 unexpected node
- 是否存在 duplicate ESC_ID

行为要求：

- 必须按 J1 -> J8 顺序生成结果
- 单个 Joint 失败不得中断剩余 Joint 扫描
- 最终结论由全量结果汇总得到

### 9.10 报告输出

#### `GET /api/jobs/{job_id}/report`

输出：

- `artifact_dir`
- `files`


## 10. Capability 矩阵

### 10.1 `serial_bridge`

V1 支持：

- 单电机扫描
- 参数读取
- 参数写入
- 保存 Flash
- 单电机通信复核

V1 不作为首选：

- 整臂 8 电机盘点

### 10.2 `socketcan`

V1 支持：

- 单电机扫描
- 单电机通信校验
- 整臂 8 电机通信扫描
- 参数读取

V1 默认不支持：

- 批量写 ID
- 保存 Flash


## 11. 验收规则

### 11.1 `single_id_config` 通过条件

必须满足：

- `ESC_ID` 回读一致
- `MST_ID` 回读一致
- `CTRL_MODE` 回读一致
- `TIMEOUT` 回读一致
- `can_br` 回读一致
- 若执行 `save_flash`，保存步骤返回成功
- 保存后通信复核通过
- 任务全程未触发重新扫描要求

### 11.2 `single_comm_check` 通过条件

必须满足：

- 节点在线
- `ESC_ID` 存在
- `MST_ID` 存在
- 无故障状态
- `t_mos < 60`
- `t_rotor < 80`

### 11.3 `arm_comm_scan` 通过条件

必须满足：

- J1~J8 全部在线
- 无 `missing joint`
- 无 `unexpected node`
- 无 `duplicate esc id`
- 无 `MST_ID` 不匹配
- 无 `can_br` 不匹配
- 无 `CTRL_MODE` 不匹配
- 无故障节点


## 12. 工件与可追溯性

每个 job 必须落盘到独立目录：

`artifacts/jobs/{timestamp}_{job_id}/`

必须生成：

- `job.json`
- `events.jsonl`
- `report.html`
- `motors/*.json`

对于整臂任务，每个 Joint 必须单独有工件文件。

### 12.1 `job.json`

包含：

- job 元信息
- 最终状态
- profile
- target joint
- failure reason

### 12.2 `events.jsonl`

包含：

- 时间戳
- severity
- step
- message

若发生 `save_flash`，还必须额外记录：

- `before_params`
- `after_params`
- `write_required`

### 12.3 `report.html`

至少包含：

- job 信息
- 结果总览
- per-motor / per-joint 结果表
- issue 列表


## 13. 错误处理规范

### 13.1 API 错误码

- `400`: 参数不合法 / 状态机前置条件不满足
- `404`: session 或 job 不存在
- `409`: transport capability 不支持
- `502`: 设备通信失败 / 运行时失败

### 13.2 失败处理

任何一步失败时：

- job 进入 `failed`
- 写入 `failure_reason`
- 追加事件日志
- 保留已生成工件


## 14. 开发实施计划

### P0. 规格收敛

目标：

- 固化 V1 的任务边界
- 固化 profile 字段
- 固化 UI 信息架构

输出：

- 本 spec

### P1. 主流程收敛

目标：

- 把默认 UI 彻底调整为通信优先
- 将 `single_id_config / single_comm_check / arm_comm_scan` 设为主入口
- 保持旧别名兼容
- 将动作能力从默认流程中移除，仅保留为 `engineering_mode`

完成标准：

- 操作员不需要接触动作测试即可完成通信流程

### P2. 扫描能力增强

目标：

- 完善整臂扫描摘要
- 增加更明确的 per-joint issue 分类
- 优化报告页和结果矩阵

完成标准：

- 扫描结果可直接用于装配线判定

### P3. 工程模式隔离

目标：

- 将动作测试、零位、MIT 等能力收纳到工程模式
- 与产线默认工作流隔离

完成标准：

- 普通操作员默认看不到动作控制入口


## 15. 测试计划

### 15.1 单元测试

必须覆盖：

- job 类型状态流
- profile 绑定
- 单电机扫描结果
- 整臂扫描摘要
- `bitrate mismatch`
- `unexpected node`
- `duplicate esc id`

### 15.2 API 测试

必须覆盖：

- `/api/device/connect`
- `/api/device/scan`
- `/api/jobs`
- `/apply-profile`
- `/write-params`
- `/verify-params`
- `/save-flash`
- `/run-comm-check`
- `/run-arm-scan`
- `/report`

### 15.3 UI 验收

必须覆盖：

- `1920x1080` 单屏无页面滚动
- 5 个主 Tab 正常切换
- 主 Tab 与二级 Tab 均能完成层级切换，不依赖页面跳转
- 主要操作按钮在各自 Tab 中始终可见
- 整臂扫描矩阵可视化正确
- 报告页可查看工件


## 16. Open Questions

当前仍需在后续阶段确认的问题：

1. `socketcan` 是否需要开放“单电机写 ID”工程模式
2. `expected_status` 是否需要区分装配态和验收态
3. 是否需要直接兼容 OpenARM 官方 CLI 输出格式
4. 报告是否需要导出 CSV / PDF


## 17. 本版结论

V1 的核心不是“把电机调起来”，而是“把通信工艺标准化”。

因此本工作站的默认主流程应当围绕：

- 识别
- 配 ID
- 查在线
- 查一致性
- 出报告

动作测试能力可以保留，但必须从主流程中退居二线。
