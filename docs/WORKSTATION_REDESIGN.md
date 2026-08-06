# OpenARM Damiao 电机初始化工作站重设计

## 1. 背景与目标

本仓库当前已经具备了一个可用的 Damiao 电机串口调试原型，但它更接近“单电机控制演示工具”，还不是一套适合 OpenARM 生产/装配/调试流水线使用的初始化工作站。

对于 OpenARM 而言，电机初始化不是单个动作，而是一条标准化工艺链：

1. 识别并连接电机
2. 配置电机 ID / Master ID
3. 设置通信参数并持久化
4. 读取关键寄存器核对型号与版本
5. 执行零位初始化
6. 执行最小安全动作测试
7. 记录结果并生成可追溯档案

工作站软件的目标应当是：

- 支撑 OpenARM 关节装配和换件初始化
- 降低人工输入与误操作
- 将“改 ID / 初始化 / 测试 / 存档”做成标准向导
- 同时兼容当前仓库的串口桥方案与 OpenARM 后续的 SocketCAN 工作流


## 2. 调研结论

### 2.1 OpenARM 的目标流程

根据 OpenARM 文档，电机建站流程明确包括：

- 先配置 Sender CAN ID 与 Receiver/Master ID
- 再配置波特率
- 然后做零位标定
- 最后做通信校验

OpenARM 当前公开的标准 ID 映射是：

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

这说明工作站软件不能只停留在“手工输入一个 ID 后发控制命令”，而要支持“按关节角色自动配置参数模板”。

### 2.2 Damiao SDK 的真实能力

从仓库内集成的 SDK 原始代码看，Damiao SDK 不只支持基础控制，还支持初始化所需的核心参数操作能力：

- `read_motor_param()` 读取寄存器
- `change_motor_param()` 写寄存器
- `save_motor_param()` 保存到 Flash
- `refresh_motor_status()` 主动刷新状态
- `switchControlMode()` 切控制模式并校验返回值

关键寄存器包括：

- `MST_ID` 主机反馈 ID
- `ESC_ID` 电机接收 ID
- `CTRL_MODE` 控制模式
- `TIMEOUT` 通信超时
- `Gr` 减速比
- `PMAX / VMAX / TMAX`
- `Damp / Inertia`
- `sw_ver / hw_ver / SN`

这意味着“电机初始化工作站”完全可以基于 SDK 做成参数化、可校验、可保存、可追踪的正式工站，而不是只做一个网页遥控器。

### 2.3 当前仓库现状

当前主实现是 [src/damiao_motor_driver.py](/home/ubuntu/Projects/OpenARM/src/damiao_motor_driver.py)，但它只保留了 SDK 的一部分能力：

- 已有：连接串口、使能/失能、零位、MIT/速度/位置速度控制、反馈解析
- 缺失：读参数、写参数、保存参数、状态刷新、参数写入校验、批量流程控制

Web 层 [web/app.py](/home/ubuntu/Projects/OpenARM/web/app.py) 也主要围绕“手动控制”展开，没有面向初始化工站的流程能力：

- 没有“扫描/识别当前电机”
- 没有“按 Joint 自动分配 ID”
- 没有“写参数后保存到 Flash”
- 没有“初始化记录单”
- 没有“测试结果判定”
- 没有“批量工艺状态机”


## 3. 当前方案的关键问题

### 3.1 产品定位错位

当前界面更像开发调试台，不像流水线工站。流水线需要的是：

- 固定步骤
- 明确成功/失败判定
- 少输入
- 有防呆
- 有记录

而现在的页面是：

- 手工填串口
- 手工填电机型号
- 手工填 SlaveID / MasterID
- 手工点多个按钮

这会把流程正确性过度依赖操作者经验。

### 3.2 初始化关键能力未接入

虽然代码里保留了 `DM_variable` 枚举，但主驱动没有把下列能力实现出来：

- 读取当前 `ESC_ID / MST_ID`
- 修改 `ESC_ID / MST_ID`
- 保存参数到 Flash
- 读取 `sw_ver / SN / PMAX / VMAX / TMAX`
- 主动刷新状态

结果就是当前仓库并不能真正完成“改 ID 并固化”的核心任务。

### 3.3 默认值存在流程风险

当前 `Motor` 默认 `MasterID = 0`。但 Damiao 与 OpenARM 资料都明确建议不要把 `Master ID` 设为 `0x00`，并建议使用 `CAN_ID + 0x10`。

对于 OpenARM，这一点尤其重要，因为它直接影响回包路由与多电机联调。

### 3.4 没有面向 OpenARM 的角色模型

OpenARM 实际不是“若干独立电机”，而是“J1~J8 的角色化关节集合”。工站软件必须知道：

- 这个电机要被初始化成哪个 Joint
- 这个 Joint 对应什么型号
- 这个 Joint 对应什么 ID
- 是否属于 left/right arm
- 是否是 gripper

没有角色模型，就无法做模板化初始化，也无法做批量校验。

### 3.5 缺少安全与审计能力

初始化工站至少需要具备：

- 上电后等待时间提示
- 温度/错误状态阻断
- 零位动作风险提示
- 测试动作限幅
- 写入次数提醒
- 操作日志与结果归档

这些能力现在基本没有形成闭环。


## 4. 重新设计的产品定义

### 4.1 新产品名称建议

建议将该软件重新定位为：

`OpenARM Motor Commissioning Station`

中文可称：

`OpenARM 电机建站与初始化工作站`

它应覆盖三类场景：

1. 单电机入库/换件初始化
2. 单臂装配建站
3. 整机联调前的批量校验

### 4.2 一句话定义

一套面向 OpenARM 装配与维护流程的 Damiao 电机工站软件，用于完成电机识别、参数配置、ID 写入、零位初始化、安全测试与记录归档。


## 5. 推荐的用户流程

### 5.1 流程 A：单电机快速建站

适合新电机、返修电机、现场换件。

步骤：

1. 连接工装与电机
2. 软件自动识别通信后端
3. 扫描当前电机信息
4. 读取当前 `ESC_ID / MST_ID / 版本 / SN / 型号`
5. 选择目标角色，例如 `J4`
6. 软件自动带出目标模板：
   - 目标电机型号
   - 目标 `ESC_ID`
   - 目标 `MST_ID`
   - 目标控制模式
   - 目标超时与限值
7. 点击“写入并校验”
8. 点击“保存到 Flash”
9. 执行零位初始化
10. 执行最小动作测试
11. 生成初始化报告

### 5.2 流程 B：整臂批量建站

适合装配线。

步骤：

1. 选择工位配置：`leader/follower`、`left/right arm`
2. 软件加载该工位的关节模板
3. 逐个接入电机
4. 每完成一个电机后自动进入下一个 Joint
5. 所有 Joint 完成后，执行整臂通信巡检
6. 输出整臂初始化记录单

### 5.3 流程 C：返修复检

适合售后或实验室维护。

步骤：

1. 输入序列号或扫描二维码
2. 读取数据库中历史配置
3. 自动对比当前参数与目标参数
4. 显示差异项
5. 支持一键修正
6. 重新执行测试并归档


## 6. 功能架构重设计

建议采用“流程层 + 设备层 + 存档层”的三层结构。

### 6.1 流程层

负责业务编排，不直接操作底层帧：

- 初始化向导
- Joint 模板管理
- 工位任务编排
- 结果判定
- 报告生成

建议核心对象：

- `CommissioningWorkflow`
- `JobProfile`
- `JointTemplate`
- `CommissioningResult`

### 6.2 设备层

负责统一驱动接口，屏蔽“串口桥”和“SocketCAN”差异。

建议抽象：

- `MotorTransport`
- `SerialBridgeTransport`
- `SocketCANTransport`
- `DamiaoProtocolService`

协议层 API 建议统一为：

- `discover()`
- `read_param(id, rid)`
- `write_param(id, rid, value)`
- `save_params(id)`
- `refresh_status(id)`
- `enable(id)`
- `disable(id)`
- `set_zero(id)`
- `mit_test(id, param)`

这样后续即使 OpenARM 控制侧转向 `openarm_can`，工站业务层也无需重写。

### 6.3 存档层

负责留痕和追溯。

建议至少记录：

- 操作者
- 时间
- 工位编号
- 电机序列号
- 原始参数快照
- 目标参数快照
- 写入结果
- 零位结果
- 测试结果
- 异常与备注

存储建议：

- 本地优先：SQLite
- 可选导出：CSV / JSON / PDF


## 7. UI 重新设计

### 7.1 页面结构

当前“一个页面堆全部按钮”的形式不适合工站。建议改为 5 个主页面：

1. 设备连接页
2. 电机识别页
3. 参数配置页
4. 初始化与测试页
5. 结果报告页

### 7.2 首页只做三件事

首页应只保留：

- 选择通信后端
- 选择工位任务
- 开始建站

而不是把所有控制能力直接暴露给操作者。

### 7.3 参数页必须区分三类信息

1. 当前值
2. 目标值
3. 写入后回读值

这会极大降低误写和误判。

### 7.4 测试页应分层

- 安全检查
- 零位动作
- 低风险 MIT 测试
- 状态监控
- 通过/失败判定

每一步都要给出明确的前置条件与中止条件。


## 8. 面向 OpenARM 的模板系统

这是新设计里最重要的部分之一。

### 8.1 建议引入 `profiles/openarm/`

例如：

- `profiles/openarm/right_arm.yaml`
- `profiles/openarm/left_arm.yaml`
- `profiles/openarm/follower_right.yaml`

模板字段建议包括：

- `joint_name`
- `motor_type`
- `target_esc_id`
- `target_master_id`
- `target_control_mode`
- `target_timeout`
- `target_baudrate`
- `requires_zero_calibration`
- `test_profile`
- `limits`

### 8.2 模板示例

```yaml
joint_name: J4
motor_type: DM4340
target_esc_id: 0x04
target_master_id: 0x14
target_control_mode: MIT
target_timeout: 20000
requires_zero_calibration: true
test_profile: slow_mit_ping
limits:
  max_abs_position: 0.3
  max_abs_velocity: 0.5
  max_abs_torque: 1.0
```

### 8.3 模板优先级

工站流程中应优先使用模板，而不是允许操作者自由输入所有寄存器。

自由输入仅在“专家模式”开放。


## 9. 推荐的测试策略

### 9.1 初始化测试不应等于功能调试

初始化工站的测试目标不是“让电机转得很漂亮”，而是最小风险地确认：

- 通信正常
- ID 正确
- 参数写入生效
- 零位可执行
- 基本响应正常
- 没有过温/过载/异常状态

### 9.2 建议测试分级

#### Level 0：只读检查

- 读取 `SN`
- 读取 `sw_ver / hw_ver`
- 读取 `ESC_ID / MST_ID / CTRL_MODE`
- 刷新状态

#### Level 1：静态动作

- enable
- refresh
- disable

#### Level 2：零位操作

- 提示人工摆位
- 执行 `set_zero`
- 回读位置

#### Level 3：低风险 MIT 测试

- 小角度、小 Kp、小 Kd、小扭矩
- 单次点动
- 回到零位

#### Level 4：扩展调试

- 连续速度测试
- 位置跟随测试
- 动力学参数读取

Level 4 不属于标准流水线默认流程，应放在工程模式。


## 10. 技术实现建议

### 10.1 第一阶段必须先补齐协议能力

在当前代码基础上，第一批必须补齐：

- `read_motor_param`
- `change_motor_param`
- `save_motor_param`
- `refresh_motor_status`
- 参数回读校验
- `MasterID != 0` 的校验规则

否则无法支撑真正的初始化工作。

### 10.2 第二阶段拆分后端

建议将 [src/damiao_motor_driver.py](/home/ubuntu/Projects/OpenARM/src/damiao_motor_driver.py) 拆分为：

- `src/protocol/damiao_protocol.py`
- `src/transports/serial_bridge.py`
- `src/transports/socketcan.py`
- `src/services/commissioning_service.py`

这样后续对接 OpenARM 的 `openarm_can` 会自然很多。

### 10.3 第三阶段重构 Web/API

当前 [web/app.py](/home/ubuntu/Projects/OpenARM/web/app.py) 采用大量全局变量，适合 demo，不适合工站。

建议改为：

- `api/devices.py`
- `api/workflows.py`
- `api/motors.py`
- `api/reports.py`

并引入：

- 任务对象
- 状态机
- 后台 worker
- WebSocket 事件流

### 10.4 建议的状态机

每个电机任务建议统一状态：

- `disconnected`
- `connected`
- `identified`
- `profile_loaded`
- `params_written`
- `params_saved`
- `zeroed`
- `tested`
- `passed`
- `failed`

这样 UI、日志、报告都能共用同一套事实来源。


## 11. 推荐的 API 设计

### 11.1 设备与发现

- `POST /api/device/connect`
- `POST /api/device/disconnect`
- `GET /api/device/ports`
- `POST /api/device/scan`

### 11.2 参数读取与写入

- `GET /api/motors/{id}/params`
- `POST /api/motors/{id}/params/write`
- `POST /api/motors/{id}/params/save`
- `POST /api/motors/{id}/refresh`

### 11.3 工站流程

- `POST /api/workflows/commission/start`
- `POST /api/workflows/commission/{job_id}/write_profile`
- `POST /api/workflows/commission/{job_id}/zero`
- `POST /api/workflows/commission/{job_id}/test`
- `POST /api/workflows/commission/{job_id}/finish`

### 11.4 记录与报告

- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/report`


## 12. 推荐的数据模型

### 12.1 MotorIdentity

```text
MotorIdentity
- serial_number
- motor_type
- current_esc_id
- current_master_id
- hw_ver
- sw_ver
```

### 12.2 JointAssignment

```text
JointAssignment
- project_name
- arm_side
- joint_name
- target_motor_type
- target_esc_id
- target_master_id
```

### 12.3 CommissioningRecord

```text
CommissioningRecord
- record_id
- operator
- station_id
- started_at
- finished_at
- motor_identity
- assignment
- param_snapshot_before
- param_snapshot_after
- zero_result
- test_result
- final_status
```


## 13. 安全设计建议

### 13.1 默认进入安全模式

首次连接后默认只允许：

- 读取参数
- 刷新状态
- 配置参数

不允许直接高速运动。

### 13.2 零位与测试前强提醒

执行零位和测试动作前必须要求：

- 确认机械无遮挡
- 确认供电电流足够
- 确认人工已扶稳或固定
- 确认急停可用

### 13.3 测试限幅

初始化工作站内置测试参数必须保守：

- 小位移
- 小速度
- 小扭矩
- 有超时
- 有自动 disable

### 13.4 Flash 写入次数提醒

OpenARM 文档明确提醒参数写入存在写入次数限制，因此：

- 默认只在最终确认后执行 `save`
- 页面上显示“未保存 / 已保存”
- 记录每次持久化时间


## 14. 实施优先级

### P0：必须完成

- 补齐 SDK 参数读写能力
- 支持改 `ESC_ID / MST_ID`
- 支持保存到 Flash
- 支持状态刷新
- 支持初始化报告
- 支持 OpenARM Joint 模板

### P1：强烈建议

- 自动扫描/识别
- 批量建站
- 测试状态机
- SQLite 留痕
- 专家模式

### P2：后续增强

- 条码/二维码录入
- 多工位并行
- 对接 MES/资产系统
- 校准视频/工装提示
- 与 `openarm_can` 直接联动


## 15. 最终建议

这套软件不应继续沿着“Web 遥控面板”方向小修小补，而应重构为“流程驱动的建站工具”。

最值得优先投入的方向不是页面美化，而是：

1. 补齐 SDK 参数操作闭环
2. 引入 OpenARM Joint 模板
3. 把初始化流程做成可复用状态机
4. 补上报告与追溯

只要这四点完成，这个仓库就会从“能控制电机”升级成“能真正支撑 OpenARM 电机上线流程”的工站软件。


## 16. 参考资料

- OpenARM Setup Guide: https://docs.openarm.dev/software/setup/
- OpenARM Motor ID Configuration: https://docs.openarm.dev/software/setup/motor-id/
- OpenARM Motor Configuration: https://docs.openarm.dev/software/setup/motor-config/
- OpenARM CAN Library: https://docs.openarm.dev/software/can/
- OpenARM Motor Specifications: https://docs.openarm.dev/hardware/specifications/motor/
- Seeed Damiao Series Wiki: https://wiki.seeedstudio.com/damiao_series/
- 仓库内 Damiao SDK 适配驱动: [src/damiao_motor_driver.py](/home/ubuntu/Projects/OpenARM/src/damiao_motor_driver.py)
- 仓库内 SDK 调研文档: [docs/SDK_RESEARCH.md](/home/ubuntu/Projects/OpenARM/docs/SDK_RESEARCH.md)
- 原始 SDK 实现: [external/qt5_damiao_motor_friction_detection/DM_CAN.py](/home/ubuntu/Projects/OpenARM/external/qt5_damiao_motor_friction_detection/DM_CAN.py)
