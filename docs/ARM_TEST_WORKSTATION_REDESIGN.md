# OpenARM 机械臂测试工作站重设计

更新时间：2026-04-17

对应的可执行规格文档：

- [ARM_TEST_WORKSTATION_V2_SPEC.md](/home/ubuntu/Projects/OpenARM/docs/ARM_TEST_WORKSTATION_V2_SPEC.md)
- [ARM_WORKSTATION_V3_SPEC.md](/home/ubuntu/Projects/OpenARM/docs/ARM_WORKSTATION_V3_SPEC.md)

## 1. 目标

基于 OpenARM 最新官方文档、OpenARM CAN 开源链路以及达妙电机开源资料，把当前仓库从“可用但局限的调试页面”重设计为一套真正适合装配、调试、验收和返修的 Linux 本地工站。

这套工站需要覆盖：

- Linux 下 CAN 接口识别与配置
- 单电机 CAN ID / Master ID 配置
- 单电机参数读取、修改、保存
- 单电机零位校准
- 单电机低风险测试
- 整臂 8 电机总线盘点与一致性校验
- 报告输出与可追溯工件

## 2. 调研结论

### 2.1 OpenARM 官方流程结论

根据 OpenARM Setup Guide（2026-04-13 更新）、Motor ID Configuration（2026-02-23 更新）、CAN Setup（2026-02-02 更新）、Motor Configuration（2026-03-21 更新）：

- OpenARM 官方默认把电机 ID 设置放在 Windows + Damiao Debugging Tools 路径里。
- Linux 侧官方主流程是：
  - 配置 SocketCAN
  - 测试基本通信
  - 配置电机波特率
  - 零位校准
  - 通信验证
- 官方明确的 Joint ID 映射为：
  - `J1..J8` -> `ESC_ID 0x01..0x08`
  - `MST_ID 0x11..0x18`
- 官方通信验收本质是在验证：
  - 发送 ID 是否正确
  - 接收 ID 是否正确
  - 波特率是否正确
  - 电机状态是否正常

### 2.2 OpenARM 官方电机型号结论

根据 OpenARM BOM 和硬件规格页：

- `J1`, `J2` -> `DM-J8009P-2EC`
- `J3` -> `DM-J4340P-2EC`
- `J4` -> `DM-J4340-2EC`
- `J5`, `J6`, `J7`, `J8` -> `DM-J4310-2EC`

这意味着 UI、profile、报告都应该优先展示官方商品型号；驱动层再映射回 `DM8009 / DM4340 / DM4310`。

### 2.3 OpenARM CAN 开源链路结论

根据 OpenARM CAN Library 文档：

- OpenARM 官方 Linux 控制链路核心是 SocketCAN。
- `OpenArm` / `ArmComponent` / `GripperComponent` 之上，底层实际还是 Damiao motor protocol。
- 典型操作包括：
  - 注册电机类型与 send/recv CAN IDs
  - 读取参数
  - enable/disable
  - MIT 控制
  - 刷新状态
- 文档强调不同操作要使用不同的超时策略：
  - 参数查询、enable/disable 用更保守的 timeout
  - 高频控制周期不能盲目拉高

### 2.4 达妙 SDK / 工具链结论

结合仓库现有驱动实现和达妙资料：

- 当前工站真正依赖的低层能力是：
  - `read_motor_param`
  - `change_motor_param`
  - `save_motor_param`
  - `refresh_motor_status`
  - `enable` / `disable`
  - `set_zero_position`
  - `controlMIT`
- 关键参数寄存器包括：
  - `ESC_ID`
  - `MST_ID`
  - `CTRL_MODE`
  - `TIMEOUT`
  - `can_br`
  - `sw_ver`
  - `sub_ver`
  - `SN`
- 参数写入不是可无限重试动作，官方明确提到写入次数有限。
- `dm-tools` 和其 USB-CAN 教程说明：USB-CAN 调试器识别、接口稳定性、波特率一致性是现场最常见问题来源。

## 3. 当前仓库现状

当前仓库已经具备：

- `serial_bridge` 单电机写参与保存的基础闭环
- `socketcan` 下的整臂扫描与总线盘点基础
- `gs_usb / gsusb1002enc` 识别
- OpenARM profile、报告工件、单屏 Tab UI

但仍然存在 6 个核心缺口：

1. 没有真正的“CAN 接口配置”工作流，只能手填 `can0`/bitrate。
2. `socketcan` 当前只读，不支持 Linux 原生单电机写参与配置闭环。
3. 工作流仍偏 demo，不是明确的“工位任务”模型。
4. 零位与测试仍然挂在一个较粗糙的执行页里，缺少前置条件与安全分级。
5. 报告虽然可用，但还不够像产线/返修工单。
6. 现有任务模型没有把“官方路径”和“增强路径”分开，容易让操作员混淆。

## 4. 新的产品定位

### 4.1 产品名称

建议名称：

`OpenARM Arm Test Workstation`

中文：

`OpenARM 机械臂测试工作站`

### 4.2 一句话定义

一套 Linux 本地 Web 工站，用于 OpenARM 电机与整臂的 CAN 建站、参数配置、零位校准、低风险测试、总线验收和报告输出。

### 4.3 产品边界

V2 的目标不是替代 ROS2 控制站，也不是替代长期运行控制系统。

V2 只做工位型能力：

- 装配前配置
- 装配后验收
- 返修排障

不做：

- 连续轨迹控制
- 高级伺服调参
- 双臂协同控制
- 正式生产调度 / MES

## 5. 重设计原则

1. 先通信、后动作
2. 先单机、后整臂
3. 默认安全，工程功能下沉
4. 单屏高密度，不靠滚动
5. 所有高风险动作都必须有前置检查和留痕
6. 报告必须能回答“发生了什么、改了什么、当前状态是否可放行”

## 6. 新的信息架构

### 6.1 顶层布局

保留单屏约束：

- `1920x1080`
- 100% 缩放
- 不允许页面级纵向滚动
- 局部列表可内部滚动

### 6.2 顶层 5 个主 Tab

- `工站`
- `接口`
- `识别`
- `执行`
- `报告`

### 6.3 主 Tab 职责

#### `工站`

用于选择任务模式和目标工位：

- 单电机建站
- 单电机复核
- 整臂验收
- 工程模式

#### `接口`

用于处理 Linux 侧系统接口问题：

- 识别 `can0/can1/slcan0`
- 识别 `gs_usb` / `gsusb1002enc`
- 显示当前 UP/DOWN 状态
- 显示当前 bitrate / dbitrate / FD 状态
- 提供系统级接口配置动作

#### `识别`

用于识别当前总线对象：

- 单电机发现
- 整臂总线盘点
- 当前 ID / 目标 ID 对照
- unexpected / duplicate / missing 节点高亮

#### `执行`

通过二级 Tab 承载：

- `ID`
- `参数`
- `零位`
- `测试`

不同任务模式下，二级 Tab 只显示允许的动作。

#### `报告`

展示：

- 本次任务摘要
- per-joint / per-motor 结果
- 参数改动
- 校验结论
- 工件目录

## 7. 新的任务模型

### 7.1 `single_id_config`

用于单电机 ID 配置。

标准流程：

1. 连接接口
2. 检测单个电机
3. 读取当前 `ESC_ID / MST_ID / CTRL_MODE / TIMEOUT / can_br`
4. 选择目标 Joint
5. 写入目标 ID
6. 回读校验
7. 可选保存 Flash
8. 通信复核
9. 出报告

适用场景：

- 新电机上线
- 返修后重新配 ID
- 已知当前 ID 的单机改配

### 7.2 `single_motor_commissioning`

用于单电机完整建站。

标准流程：

1. 读取当前参数与状态
2. 绑定目标 Joint
3. 写入 `ESC_ID / MST_ID / CTRL_MODE / TIMEOUT / can_br`
4. 回读校验
5. 保存 Flash
6. 零位校准
7. 低风险测试
8. 出报告

这是对 `single_id_config` 的增强版。

### 7.3 `single_comm_check`

用于单电机只读复核。

标准流程：

1. 识别单电机
2. 读取关键寄存器
3. 刷新状态
4. 判定在线 / 参数一致性 / 温度 / 故障
5. 出报告

### 7.4 `arm_bus_scan`

用于整臂总线盘点。

输出：

- 在线 Joint
- 缺失 Joint
- duplicate ESC_ID
- unexpected node
- 实际 `ESC_ID / MST_ID / can_br / CTRL_MODE`

### 7.5 `arm_acceptance`

用于整臂验收。

在 `arm_bus_scan` 基础上，再增加：

- profile 一致性判定
- 参数漂移判定
- 状态健康判定
- 可选逐 Joint 低风险测试

### 7.6 `engineering_mode`

用于开发和返修。

允许：

- 手工输入当前 ID
- 手工修改目标参数
- 单关节动作测试
- 不在 profile 中的电机调试

但必须：

- 在 UI 中明显标红
- 要求填写原因
- 报告记录覆盖参数

## 8. Linux 工位必须新增的能力

### 8.1 系统级 CAN 接口配置

这是当前缺口最大的部分。

工站应直接支持：

- 扫描系统接口：`can0`, `can1`, `slcan0`
- 显示：
  - 接口名
  - 驱动
  - 适配器类型
  - `state`
  - `bitrate`
  - `dbitrate`
  - `fd on/off`
- 提供动作：
  - `bring down`
  - `configure CAN 2.0`
  - `configure CAN FD`
  - `bring up`

实现方式建议：

- 首选调用系统 `ip link`
- 如果检测到已安装 `openarm-can-configure-socketcan`，可提供“官方配置”快捷入口
- 所有系统命令输出写入任务事件流

### 8.2 Linux 原生单电机改 ID

虽然 OpenARM 官方默认用 Windows 工具配 ID，但工站必须提供 Linux 原生能力。

限制条件：

- 默认只允许“单机工装”
- 必须先确认总线上仅有 1 颗目标电机
- 若有多颗电机，必须切换专家模式并指定 `current_id`

### 8.3 Linux 原生零位校准

应区分两种模式：

- `single_zero`
  - 单关节零位
  - 适合返修或单机场景
- `arm_zero_guided`
  - 引导式整臂零位
  - 按 J1 -> J8 逐步执行

零位前必须通过：

- 电机已失能
- 当前状态无 fault
- 温度不过限
- 操作者确认机械位置已就位

### 8.4 低风险电机测试

测试不应默认直接暴露完整 MIT 调试，而应定义分级：

- `comm_ping`
  - enable / disable / refresh
- `micro_mit_ping`
  - 极小幅度位置脉冲
- `return_to_zero_check`
  - 零位附近往返

默认整臂验收只允许 `comm_ping`；`micro_mit_ping` 作为单机关卡。

## 9. Profile 设计

profile 需要从“静态参数表”升级为“工位真值来源”。

每个 Joint 至少包含：

- `joint_name`
- `official_motor_type`
- `driver_motor_type`
- `target_esc_id`
- `target_mst_id`
- `target_ctrl_mode`
- `target_timeout`
- `target_can_br`
- `expected_bus`
- `requires_zero`
- `allowed_test_profiles`
- `zero_mechanical_note`
- `acceptance_limits`

其中 `acceptance_limits` 应包括：

- `mos_max`
- `rotor_max`
- `position_return_tol`
- `comm_timeout_ms`

## 10. 报告重设计

报告应该分成 3 层：

### 10.1 任务摘要

- 任务类型
- 工位模式
- 操作者
- 时间
- transport
- 接口配置
- 总结论

### 10.2 逐电机结果

每个 Joint / Motor 记录：

- 官方型号
- 当前 ID
- 目标 ID
- 当前 `can_br`
- 当前 `CTRL_MODE`
- 当前状态
- 是否零位成功
- 是否测试成功
- issues

### 10.3 审计与变更

- 哪些参数被修改
- 是否保存 Flash
- 是否进入工程模式
- 谁执行了危险动作确认

建议固定输出：

- `job.json`
- `events.jsonl`
- `motors/*.json`
- `summary.csv`
- `report.html`

## 11. 建议的软件架构

### 11.1 四层结构

#### A. UI Layer

负责：

- 单屏 Tab UI
- 风险提示
- 结果矩阵
- 报告展示

#### B. Workflow Layer

负责：

- 任务状态机
- 动作门控
- 前置条件检查
- 风险确认

#### C. Device Layer

负责：

- `serial_bridge`
- `socketcan`
- `system_can`

其中 `system_can` 是新增的系统接口适配层，不直接控电机，而是控 Linux CAN 接口。

#### D. Artifact Layer

负责：

- 任务工件
- HTML/CSV/JSON 输出
- 报告模板

### 11.2 设备适配矩阵

- `system_can`
  - 列出接口
  - 配置接口
  - 拉起/拉下接口
- `socketcan`
  - 扫描
  - 读参
  - 写参
  - 保存
  - 零位
  - 测试
- `serial_bridge`
  - 扫描
  - 读参
  - 写参
  - 保存
  - 零位
  - 测试

建议目标不是把 `socketcan` 永远保持只读，而是补齐 Linux 原生闭环。

## 12. 对当前代码的具体改造建议

### 12.1 `src/workstation.py`

需要从当前的“两个任务 + 一些兼容别名”升级成真正的任务编排器：

- 增加 `system_can` 服务
- 拆分 `single_id_config` 与 `single_motor_commissioning`
- 补 `arm_acceptance`
- 把风险动作前置检查从 UI 挪到服务层

### 12.2 `src/damiao_motor_driver.py`

需要继续补齐：

- `socketcan` 下的 `change_motor_param`
- `socketcan` 下的 `save_motor_param`
- `socketcan` 下的参数写后确认
- 更明确的错误码和超时处理

### 12.3 `web/app.py`

需要增加接口：

- `GET /api/system/can-interfaces`
- `POST /api/system/can-interfaces/configure`
- `POST /api/system/can-interfaces/up`
- `POST /api/system/can-interfaces/down`
- `POST /api/jobs/{id}/run-zero-guided`
- `POST /api/jobs/{id}/run-test-profile`

### 12.4 前端

需要把现在“调试页式执行区”改成真正的工位流程执行器：

- 工位模式切换
- 官方路径 / 增强路径提示
- 接口配置板块前置
- 整臂结果矩阵更突出
- 风险动作 modal 更严格

## 13. 推荐实施顺序

### P0：规格收敛

- 完成新 spec
- 统一任务命名
- 统一 profile 字段

### P1：Linux 接口配置

- 扫描 `can0/can1/slcan0`
- 支持 `ip link` 配置
- 接口状态实时显示

### P2：Linux 单电机闭环

- 单电机改 ID
- 单电机保存
- 单电机零位
- 单电机低风险测试

### P3：整臂验收

- 整臂盘点
- 参数一致性
- 健康判定
- 验收报告

### P4：工程模式

- 高级动作测试
- 非 profile 节点调试
- 返修模式

## 14. 最终建议

结论是：

- 你现在这个仓库已经具备“工作站雏形”，但还不是完整的 OpenARM 测试工作站。
- 真正需要补的是“Linux 工位闭环”，尤其是：
  - 系统级 CAN 接口配置
  - `socketcan` 写参与保存
  - 零位/测试的任务化和安全化
  - 整臂验收结果矩阵与报告
- 设计上不应该再把它当成“达妙调试助手替代品”，而应该当成“OpenARM 工位执行器”。

## 15. 参考资料

- OpenARM Setup Guide: https://docs.openarm.dev/software/setup/
- OpenARM Motor ID Configuration: https://docs.openarm.dev/software/setup/motor-id/
- OpenARM CAN Setup: https://docs.openarm.dev/software/setup/can-setup/
- OpenARM Motor Configuration: https://docs.openarm.dev/software/setup/motor-config/
- OpenARM CAN Library: https://docs.openarm.dev/software/can/
- OpenARM BOM: https://docs.openarm.dev/hardware/bill-of-materials/procuring-components/
- OpenARM Motor Specifications: https://docs.openarm.dev/hardware/specifications/motor/
- DM-Tools: https://gitee.com/kit-miao/dm-tools
- DM-J4310-2EC: https://gitee.com/kit-miao/DM-J4310-2EC
- DM-J4340-2EC: https://gitee.com/kit-miao/DM-J4340-2EC
- DM-J4340P-2EC: https://gitee.com/kit-miao/DM-J4340P-2EC
- DM-J8009P-2EC: https://gitee.com/kit-miao/DM-J8009P-2EC
