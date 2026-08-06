# OpenARM 机械臂电机通信工作站重设计

## 1. 目标边界

本版本工作站只聚焦两类能力：

1. 配置 Damiao 电机 CAN ID / Master ID / 通信参数
2. 检测整条机械臂 8 个电机的通信状态与参数一致性

明确不包含：

- 动作测试
- MIT/速度/位置控制调试
- 零位自动标定
- 摩擦参数识别

这不是一个“调电机跑起来”的工具，而是一个“通信建站 + ID 配置 + 整臂通信验收”的工站软件。


## 2. 技术调研结论

### 2.1 OpenARM 官网当前流程

依据 OpenARM 官网截至 2026-04-15 的公开文档：

- Step 1 明确要求先配置 `Sender CAN ID` 和 `Receiver (Master) ID`
- Step 2 使用 Linux `SocketCAN`
- Step 4 的核心是：
  - 设置电机波特率
  - 校验电机通信
  - 必要时将设置刷写到 Flash

OpenARM 当前公开的标准关节 ID 映射为：

| Joint | Sender CAN ID | Receiver / Master ID |
|------|----------------|----------------------|
| J1 | 0x01 | 0x11 |
| J2 | 0x02 | 0x12 |
| J3 | 0x03 | 0x13 |
| J4 | 0x04 | 0x14 |
| J5 | 0x05 | 0x15 |
| J6 | 0x06 | 0x16 |
| J7 | 0x07 | 0x17 |
| J8 | 0x08 | 0x18 |

OpenARM 官方还明确给出通信校验命令：

- `openarm-can-motor-check 1 17 can0`

其期望输出至少包括：

- receiver ID
- baudrate
- status

这说明 OpenARM 官方的软件思路并不是“可视化控制电机动作”，而是“先完成 ID 和总线层配置，再做通信验证”。

### 2.2 OpenARM 官方软件结构

官网 `CAN Library` 文档说明，OpenARM 通讯采用三层结构：

- 高层 `can/socket`
- 中层 `damiao_motor`
- 底层 `canbus`

关键点是：

- 通讯接口基于 Linux `SocketCAN`
- 重点是注册电机类型、发送 ID、接收 ID
- 参数查询和状态监控是正式支持的路径

这意味着你们的工站软件应优先围绕：

- bus 接入
- 8 关节 profile
- 参数查询
- 批量通信校验

而不是继续围绕单电机动作控制来设计。

### 2.3 Damiao 官方/社区公开说明

依据 Seeed 的 Damiao 电机 Wiki：

- `CAN_ID` 是驱动器接收 CAN 命令的帧 ID
- `Master ID` 是驱动器发送反馈的帧 ID
- 最佳实践是 `MasterID = CAN_ID + 0x10`
- `Master ID` 不应设置为 `0x00`
- 使用调试工具时，标准流程是：
  - `Read Param`
  - 修改 CAN ID / Master ID / 控制模式等参数
  - `Write Param`

Wiki 还说明：

- `CAN Timeout` 是 32 位整数，单位为 50 微秒周期
- `can_br` 属于电机内部参数
- 参数存在写入次数限制，不应频繁刷写

### 2.4 当前仓库与目标不匹配的地方

当前仓库虽然已经引入了：

- `serial_bridge`
- `socketcan`
- 单电机建站
- 整臂扫描

但主流程仍然混合了“通信工站”和“动作调试台”两种定位，典型表现是：

- 前端仍保留 `零位`
- 前端仍保留 `safe_mit_ping`
- `single_commissioning` 仍以“写参数 + 零位 + 测试”为主
- `arm_verification` 才是接近目标的功能

因此，新的重设计应当把“通信工站”从“动作调试”中彻底分离出来。


## 3. 新的软件定位

建议将产品重新定义为：

`OpenARM Arm Communication Workstation`

中文建议名称：

`OpenARM 机械臂电机通信工作站`

一句话定义：

一套用于配置 Damiao 电机 CAN 身份参数，并对 OpenARM 8 关节总线通信、参数一致性和整臂接线状态进行验收的本地工站软件。


## 4. 新工作站只保留 3 类任务

### 4.1 单电机 ID 配置

目标：

- 识别当前电机
- 读取现有 `ESC_ID / MST_ID / can_br / CTRL_MODE / sw_ver / SN`
- 写入新的 `ESC_ID / MST_ID / can_br`
- 回读确认
- 可选 `save_flash`

适用场景：

- 新电机入库
- 更换电机
- 返修件重新分配 Joint

### 4.2 单电机通信校验

目标：

- 不写参数
- 只读取并确认：
  - `ESC_ID`
  - `MST_ID`
  - `can_br`
  - `CTRL_MODE`
  - `status`
  - 温度信息

适用场景：

- 刷写后确认
- 排查某个关节不在线

### 4.3 整臂 8 电机通信扫描

目标：

- 以 `openarm_v1` profile 为准
- 扫描整条总线上的节点
- 对账 8 个关节是否全部存在
- 检查是否存在：
  - 缺失关节
  - ID 重复
  - Master ID 不匹配
  - 波特率不匹配
  - 非预期节点
  - 故障状态节点

输出：

- scan summary
- 每关节结果表
- HTML 验收报告


## 5. 重新设计后的信息架构

工作站顶层不再以“控制面板”组织，而应以“任务型页面”组织。

仍然保持单屏、Tab 切换，但只保留与通信相关的内容。

### 主 Tab

1. `任务`
2. `连接`
3. `识别`
4. `配置`
5. `扫描报告`

### 删除的旧概念

应从主工作流中移除：

- 零位
- MIT 测试
- 速度模式
- 位置模式
- Enable/Disable 按钮暴露给普通操作员

这些如果保留，也只能放在“工程模式”里，且默认隐藏。


## 6. 推荐的页面设计

### 6.1 任务页

只允许选择三种任务：

- `单电机 ID 配置`
- `单电机通信校验`
- `整臂 8 电机通信扫描`

同时选择：

- transport
  - `Damiao Debug Tool / Serial Bridge`
  - `SocketCAN`
- profile
  - 默认 `openarm_v1`

### 6.2 连接页

分成两个连接模板：

#### Serial Bridge

- 串口设备
- 串口波特率
- 驱动在线状态

#### SocketCAN

- `can0/can1/...`
- 当前 interface bitrate
- interface UP/DOWN
- `candump` 可用性提示

### 6.3 识别页

针对不同任务显示不同信息：

#### 单电机任务

- 当前可识别节点
- 当前 `ESC_ID`
- 当前 `MST_ID`
- 当前 `can_br`
- 当前状态

#### 整臂任务

- J1~J8 固定矩阵
- 每个格子显示：
  - 期望 ESC_ID
  - 实测 ESC_ID
  - 实测 MST_ID
  - 在线/离线
  - OK / Fault / Unexpected

### 6.4 配置页

仅对 `单电机 ID 配置` 任务开放。

分成三块：

1. 当前参数
2. 目标参数
3. 回读结果

目标参数只允许编辑：

- `ESC_ID`
- `MST_ID`
- `can_br`
- `CTRL_MODE`（仅需要时）
- `TIMEOUT`

默认不允许编辑：

- PMAX
- VMAX
- TMAX
- 动力学参数

### 6.5 扫描报告页

聚焦“验收”而非“调试”：

- 总体通过 / 失败
- 缺失关节列表
- 非预期节点列表
- 波特率不匹配列表
- Master ID 不匹配列表
- 逐 Joint 结果表
- 导出报告


## 7. 推荐的能力矩阵

### Serial Bridge

适合做：

- 单电机识别
- 读参数
- 写 `ESC_ID / MST_ID / can_br`
- `save_flash`

不推荐做：

- 整臂 8 电机总线盘点

原因：

- 官方 ID 配置流程更接近单机配置
- 串口桥更适合“刷一颗、验一颗”

### SocketCAN

适合做：

- 单电机通信校验
- 整臂 8 电机扫描
- 参数读取
- `openarm-can-motor-check` 风格校验

V1 中建议默认不在 SocketCAN 上提供写 ID 功能，除非进入工程模式。

这样可以避免：

- 批量误刷 ID
- 总线上多节点误改参数
- 生产现场误操作


## 8. 新的 Job 模型

建议把当前 job 类型改为下面三种：

### `single_id_config`

状态流：

- `draft`
- `device_connected`
- `identified`
- `target_loaded`
- `params_written`
- `params_verified`
- `flash_saved`
- `passed`
- `failed`

### `single_comm_check`

状态流：

- `draft`
- `device_connected`
- `identified`
- `params_read`
- `checked`
- `passed`
- `failed`

### `arm_comm_scan`

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


## 9. 新的验收规则

### 9.1 单电机 ID 配置通过条件

必须满足：

- 目标 `ESC_ID` 回读一致
- 目标 `MST_ID` 回读一致
- 目标 `can_br` 回读一致
- 若执行 `save_flash`，重启后再次读取仍一致

### 9.2 单电机通信校验通过条件

必须满足：

- 电机在线
- `ESC_ID` 存在
- `MST_ID` 存在
- `status` 非故障
- 温度低于阈值

### 9.3 整臂扫描通过条件

必须满足：

- J1~J8 全部存在
- 无重复 `ESC_ID`
- 所有关节 `MST_ID == ESC_ID + 0x10`
- 所有关节 `can_br` 与 profile 期望一致
- 无 unexpected node
- 无 fault 状态节点


## 10. 推荐的 API 重构

当前 API 过于围绕旧版“控制电机”设计。建议改为通信工站导向：

### 设备

- `POST /api/device/connect`
- `POST /api/device/disconnect`
- `POST /api/device/scan`
- `GET /api/device/interface-status`

### Job

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/load-target`
- `POST /api/jobs/{job_id}/write-comm-params`
- `POST /api/jobs/{job_id}/verify-comm-params`
- `POST /api/jobs/{job_id}/save-flash`
- `POST /api/jobs/{job_id}/run-comm-check`
- `POST /api/jobs/{job_id}/run-arm-scan`
- `GET /api/jobs/{job_id}/report`

### 不建议继续暴露为普通操作接口

- `/zero`
- `/test`
- `/control/mit`
- `/control/velocity`
- `/control/position_velocity`


## 11. profile 设计建议

当前 `openarm_v1.yaml` 里混入了：

- `requires_zero`
- `test_profile`

这不适合新的通信工站目标。

建议改为通信 profile：

```yaml
profile_id: openarm_v1
name: OpenARM V1
mode: communication_only
joints:
  - joint_name: J1
    motor_type: DM8009
    target_esc_id: 1
    target_mst_id: 17
    target_can_br: 1000000
    expected_ctrl_mode: MIT
    expected_bus: can0
```

建议删除：

- `requires_zero`
- `test_profile`

建议新增：

- `required_online`
- `allow_write`
- `expected_status`


## 12. 当前代码最值得优先调整的地方

### 12.1 从前端移除动作导向 UI

当前前端仍有：

- `零位`
- `safe_mit_ping`
- 参数保存后继续动作测试

这与新的“通信优先”目标冲突，应从默认界面移除。

### 12.2 拆分当前 `single_commissioning`

当前 `single_commissioning` 混合了：

- 通信参数写入
- Flash 保存
- 零位
- 动作测试

建议拆成：

- `single_id_config`
- `single_comm_check`

### 12.3 强化整臂扫描为主功能

当前 `arm_verification` 已经接近目标，但还需要进一步变成首页主任务：

- 更明显的 J1~J8 总览
- 更明确的 mismatch 分类
- 更强的 unexpected node 展示

### 12.4 引入“工位模式”

建议首页直接让用户选：

- `单机刷写工位`
- `整臂扫描工位`

而不是先理解 transport 和 job 状态机。


## 13. 推荐的最终产品结构

### 模式 A：单机刷写工位

最少步骤：

1. 连接 Serial Bridge
2. 识别当前电机
3. 选择目标 Joint
4. 写 CAN ID / Master ID / can_br
5. 回读校验
6. 保存 Flash
7. 输出单机配置报告

### 模式 B：整臂扫描工位

最少步骤：

1. 连接 SocketCAN
2. 选择 `openarm_v1`
3. 扫描总线
4. 生成 8 关节通信结果矩阵
5. 导出验收报告


## 14. 结论

基于 OpenARM 官网和 Damiao 公开资料，当前这套软件最合理的方向不是继续做“能让电机动起来的调试台”，而是收敛成一个“通信建站工具”。

最应该优先投入的不是动作控制，而是：

1. 单电机 CAN ID / Master ID 配置闭环
2. 整臂 8 电机通信扫描与对账
3. profile 化的 OpenARM 关节配置
4. 报告化验收

也就是说，V1 的关键词应该是：

`配 ID`
`查在线`
`查一致性`
`出报告`

而不是：

`零位`
`MIT`
`跑动作`


## 15. 参考资料

- OpenARM Setup Guide: https://docs.openarm.dev/software/setup
- OpenARM Motor ID Configuration: https://docs.openarm.dev/software/setup/motor-id/
- OpenARM SocketCAN Setup: https://docs.openarm.dev/software/setup/can-setup/
- OpenARM Motor Configuration: https://docs.openarm.dev/software/setup/motor-config/
- OpenARM CAN Library: https://docs.openarm.dev/software/can/
- Damiao Series Wiki: https://wiki.seeedstudio.com/damiao_series/
- 当前 Damiao SDK 源码: [external/qt5_damiao_motor_friction_detection/DM_CAN.py](/home/ubuntu/Projects/OpenARM/external/qt5_damiao_motor_friction_detection/DM_CAN.py)
- 当前工站核心实现: [src/workstation.py](/home/ubuntu/Projects/OpenARM/src/workstation.py)
