# OpenARM 出厂工作站 V5 方案：1.0 / 2.0 双版本 · 新手可用 · 出厂全流程

更新时间：2026-09-17
状态：Proposed（待 §9 决策项确认后进入实施）
基线：工作站 `0.8.0-single-motor-wizard`（未提交）、官方 `enactic/openarm_can` 1.4.0（2026-09-16）

一句话定义：

`V5 = 一套工作站代码，两套隔离的产品版本（1.0 / 2.0），从单电机到出厂放行全部是“一步一按钮 + 自动留证 + 出错给解决方案”的向导流程`

---

## 1. 目标与原则

| 目标 | 含义 |
|---|---|
| 兼容 1.0 和 2.0 | 版本在整机建档时确定，之后 ID、总线模式、夹爪、零位、相机、报告全部由版本配置驱动，禁止 1.0/2.0 证据混用 |
| 新手可用 | 每个工位都是向导：只亮当前可执行的一个按钮；危险动作前有勾选确认；出错显示“原因 + 解决步骤 + 重试/重新开始” |
| 安全 | 不运动的步骤绝不发使能/运动帧；运动步骤有急停确认、限位、超时、结束必失能；参数写入 = 失能 → 写 → 回读 → 保存 → 断电复核 |
| 准确 | 报告只用同一台臂、同一版本、实测读回的数据；目标值只是判据，不能冒充实测 |
| 与官方一致 | 流程顺序、CAN 模式、工具命令以官方文档和 `openarm_can` 为准；工作站自己的安全增强以“包装层”叠加，不改动官方源码 |

---

## 2. 调研结论（依据）

### 2.1 1.0 与 2.0 的差异（官方）

| 项目 | 1.0 | 2.0 | 对工作站的影响 |
|---|---|---|---|
| 关节电机 | J1-J2 DM-J8009P，J3 DM-J4340P，J4 DM-J4340，J5-J7 + 夹爪 DM-J4310 | **相同**（官方 “Same motor lineup”） | 电机型号表可共用 |
| CAN ID（官方） | 每条臂独立总线，J1-J8 = 0x01-0x08 / 0x11-0x18 | 相同；右臂 can0，左臂 can1 | 见 §2.3 与我们方案 A 的差异 |
| 末端 | 连杆平行夹爪，开合 60°（-60°→0°），无相机 | 紧凑夹爪 + 手内相机；右臂 0→-90°，左臂 0→+90°（方向相反） | 夹爪目标、方向、行程判据必须按版本和左右臂区分 |
| CAN 模式 | 官方推荐 FD 1M/5M，经典 CAN 1M 也支持 | 官方默认 FD 1M/5M（`openarm-can-cli can_configure`） | 需要 FD 通路 |
| 零位 | 自动限位搜索脚本 | Cell 夹具 + `set_zero --arm`，或脚本 `--robot-version v2` | 零位方式按版本 + 是否有夹具 |
| 相机 | 无 | 官方 Cell：Arducam 腕部/顶部 + ZED-M 头部，udev 固定设备名；**我们产品**：夹爪相机 DCXGW20（必测），顶部 D435i（选配） | 新增相机工位，按订单选配 |

### 2.2 官方工具现状

- 上游 `openarm_can` 最新 **1.4.0**，统一命令行 `openarm-can-cli`：`can_configure`、`discover`、`change_id`、`change_baud`、`show_param`、`write_param`、`set_zero`、`enable/disable/clear_error`、`monitor`、`diagnose --explain`（新增）。旧脚本（`openarm-can-change-baudrate`、`configure-socketcan`、`set-zero`、`motor_check`）已被删除。
- 我们本地是 **1.2.2**，且零位脚本被改过（780 行，带 `WORKSTATION_*` 安全参数），上游原版 343 行，没有 `--robot-version`。本地没有安装 `openarm-can-cli`。
- 官方文档部分落后于 1.4.0 代码（如 `--rm` 默认值、`discover` 后是否需要重配）。以代码为准。

### 2.3 与我们已定方案的差异（需要清楚记录的风险）

| 项目 | 官方 | 我们 | 说明 |
|---|---|---|---|
| 左臂 ID | can1 上 0x01-0x08 | **方案 A：左臂 0x09-0x10 / 0x19-0x20**（已定，不调换） | 官方零位脚本、`set_zero --arm`、Demo、ROS2 默认按 0x01-0x08。左臂需要我们的包装层传 ID；L-J8 = 0x10 在达妙状态帧 4 位 ID 字段里放不下，驱动与报告已特殊处理。**客户若直接用官方软件控制左臂，需要给出对应 ID 配置**（见 §9 决策 2） |
| 改波特率时接口模式 | 1.0 文档：改波特率时接口一律用 CAN 2.0；2.0 文档：接口先匹配电机当前速率 | 单电机 1M 经典 CAN 配 ID，装配后整臂切 5M（方案 A 顺序） | 两版文档不一致；社区 openarm#471 有 J2 必须用 FD 写波特率才生效的案例 → **必须实测**（§8 P0） |
| 5M 电机是否回应经典帧 | 维护者：出厂 CAN 2.0 电机“能响应 FD 帧”；5M 电机回应经典帧**无文档** | — | 官方 `set_zero`/`change_baud` 在 FD 接口上发经典帧，属间接证据，**必须实测** |
| TIMEOUT / 限位 / 固件 | 官方未规定 TIMEOUT；给出了测试过的固件版本（DM4310 V5017_04、DM4340 V5117_04、DM8009 V6417_04） | TIMEOUT 整臂 5000（1.0 两臂已统一） | 2.0 的 TIMEOUT 需确认；固件版本改为“读取并与基线比对” |
| 电机 SN | — | 达妙 SN 寄存器不唯一（4 颗新电机读到同一值） | 电机身份 = 我们自己的编号（整机 CN + 关节号），不做铭牌 SN 输入 |

### 2.4 现有工作站盘点

已经具备（可复用）：

- 单电机新手向导（0.8.0）：识别 → 核对（含型号推断、关节占用提醒）→ 写入校验 → 保存 → 断电复核 → 记录；问题目录 + 解决方案；**已在真机完成 R-J1/R-J2/L-J1/L-J2**。
- 整臂静态验收（ID/参数矩阵/故障/重复扫描稳定性）、TIMEOUT 按关节标准化、低增益使能检查、极小幅响应。
- 官方动态测试：整机 CN、零位工作流、Demo 工作流、CAN 健康快照、candump 抓包、放行门（release gate）、正式报告（证据 SHA-256）。
- 安全：确认清单、默认 dry-run、失能后写入、运动命令结束强制失能、零位 bump/恢复姿态限制。

缺口：

1. **没有版本抽象**：ID 表、电机型号、夹爪、CAN 模式分散写死在 `workstation.py`、Demo、零位脚本、报告里；向导里的“OpenArm 2.0”只是记录标签。
2. **没有 CAN-FD 通路**：驱动只发经典帧；安全 motor-check 拒绝 FD；零位/Demo 调用不传 `--fd`；报告与放行门写死 “CAN 2.0 / 1 Mbps / FD disabled”。
3. **只有单电机页是新手向导**：03-05 仍是工程师界面（左侧任务栏、专家模式），整臂流程分散在两个页签、需手动关联任务。
4. **单电机记录没进出厂报告**。
5. **测试数据污染真实记录**：`tests/test_arm_can_scan_cli.py` 未重定向输出目录，跑测试会在 `artifacts/jobs` 里生成假的 PASS 任务。
6. 技术债：`workstation.py` 6900+ 行；15 份新旧规格文档重叠；TIMEOUT 在基础 Profile（1000）与派生 Profile（5000）不一致；DMTool 路径写死。

---

## 3. 目标架构

```
┌──────────────── 新手向导层（web） ────────────────┐
│ 单电机向导 │ 整臂出厂向导（按版本生成步骤） │ 报告签核 │
└──────────────────────┬───────────────────────────┘
                       │ 步骤 API（每步：前置检查 → 执行 → 留证 → 问题目录）
┌──────────────────────┴───────────────────────────┐
│ 流程编排层  station_flow：步骤定义、状态机、放行门      │
├───────────────┬───────────────┬──────────────────┤
│ 产品版本注册表  │ 传输层          │ 官方工具包装层      │
│ product/*.yaml │ classic / FD    │ openarm-can-cli    │
│               │ 驱动 + 总线健康   │ 零位/Demo/诊断     │
├───────────────┴───────────────┴──────────────────┤
│ 证据与记录层：单电机记录、整臂任务、CAN 健康、相机快照、报告 │
└──────────────────────────────────────────────────┘
```

### 3.1 产品版本注册表（单一事实来源）

新增 `profiles/products/openarm_1_0.yaml`、`openarm_2_0.yaml`，替代分散的写死表。工作站、Demo 包装、零位包装、报告全部从这里读：

```yaml
product_version: openarm_2_0
profile_revision: 2026-09-17.1
arms:
  right_arm: { bus: can0, joint_prefix: R, esc_ids: [0x01..0x08], mst_ids: [0x11..0x18] }
  left_arm:  { bus: can1, joint_prefix: L, esc_ids: [0x09..0x10], mst_ids: [0x19..0x20] }   # 方案 A
motors: { J1: DM-J8009P-2EC, J2: DM-J8009P-2EC, J3: DM-J4340P-2EC, J4: DM-J4340-2EC, J5..J8: DM-J4310-2EC }
can:
  commissioning: { mode: classic, bitrate: 1000000 }          # 单电机配 ID
  operation:     { mode: fd, bitrate: 1000000, dbitrate: 5000000, motor_can_br_code: 9 }
parameters: { CTRL_MODE: MIT, TIMEOUT: 5000 }                  # 2.0 TIMEOUT 待确认
firmware_baseline: { DM4310: V5017_04, DM4340: V5117_04, DM8009: V6417_04 }
gripper:
  right_arm: { closed_deg: 0, open_deg: -90 }
  left_arm:  { closed_deg: 0, open_deg: 90 }
zero: { methods: [cell_jig_set_zero, limit_search_v2], default: 待确认 }
cameras:
  gripper: { model: DCXGW20, required: true, mode: 1080p60 }
  top:     { model: D435i, required: per_order }
```

- 1.0 配置保留 `operation.mode: classic`（已售和在产的 1.0 不迁移，见 §9 决策 4），夹爪 -60°，无相机。
- **版本绑定在整机 CN 建档时**，之后所有任务从 CN 读取版本，界面不再让操作员每一步选版本。
- 报告写入 `product_version` + `profile_revision`，与工作站软件版本（SemVer）分开。

### 3.2 传输层：经典 CAN 与 CAN-FD 双模式

| 位置 | 改动 |
|---|---|
| `DamiaoSocketCANDriver` | `can.Bus(..., fd=True)`；发送 `is_fd` / `bitrate_switch` 按模式；接收同时处理经典帧和 FD 帧 |
| 接口配置 / 向导自动启动 | 按版本的 `can` 配置执行 `bitrate` + `dbitrate` + `fd on`，与 `openarm-can-cli can_configure` 默认一致（采样点 0.75、dsjw 2） |
| 总线健康 / 放行门 | 检查项从“CAN 2.0 / 1 Mbps”改为按版本判定：模式、仲裁速率、数据速率、BRS、错误计数、ERROR-ACTIVE |
| 安全 motor-check / 使能检查 / 就绪检查 | 支持 `--fd`，速率从版本配置读取 |
| 零位 / Demo 调用 | 按版本传 `--fd`、`--robot-version v1/v2`、臂侧 ID |
| 正式报告 | 去掉写死的 “CAN 2.0 / FD disabled”，改为实测的模式和速率 |

### 3.3 官方工具包装层

- 在 `external/` 新增**原版** `openarm_can_1.4.0`（固定版本、不修改），构建 `openarm-can-cli`；现有 1.2.2 保留给 1.0 回归，直到 1.4.0 回归通过后下线。
- 工作站的安全增强（bump 限制、恢复姿态、位置稳定性检查、失能恢复）从“改官方脚本”改为**包装脚本 + 参数**：官方命令前后做检查，不改官方源码。这样以后升级官方版本只需回归测试。
- 用 `openarm-can-cli diagnose --explain` 作为整臂“连接自检”步骤，其判断规则（60Ω 终端、回帧在 0x00 说明 MST_ID 未设、连续多个关节无响应 = 菊花链断点）直接进问题目录。
- 报告记录官方工具版本号。

---

## 4. 出厂全流程（新手向导）

一台臂从电机到出厂的完整顺序。每一步都是：**前置检查 → 一个主按钮 → 自动留证 → 失败时给解决方案**。

### 阶段 A：单电机工位（装配前，已完成主体）

| 步骤 | 1.0 | 2.0 | 是否运动 |
|---|---|---|---|
| A1 选择产品 / 臂侧 / 关节 | ✓ | ✓ | 否 |
| A2 识别：单颗检查、故障/温度、**型号推断 + 铭牌确认**、关节占用提醒 | ✓ | ✓ | 否 |
| A3 写入 ID / MST / MIT / 1M（TIMEOUT 只记录）→ 回读 | ✓ | ✓ | 否 |
| A4 保存 Flash → 断电重上电 → 只读复核 → 保存记录 | ✓ | ✓ | 否 |

待补：记录挂到整机 CN（装配时扫码/选择“这台臂的 R-J1 用哪条记录”），固件版本与基线比对。

### 阶段 B：整臂出厂向导（新建，替代 03/04 页签的工程师操作）

| 步骤 | 内容 | 1.0 | 2.0 | 运动 | 安全要求 |
|---|---|---|---|---|---|
| B1 整机建档 | 生成/扫描 CN，选定**产品版本**、臂侧、顶部相机是否选配；关联 8 条单电机记录 | ✓ | ✓ | 否 | 版本一经确定锁定 |
| B2 连接自检 | 适配器识别、终端电阻、总线状态；`diagnose` 定位断点 | ✓ | ✓ | 否 | — |
| B3 静态验收（经典 CAN 1M） | 8 关节 ID / MST / 模式 / 波特率 / 故障 / 温度 / 型号推断，重复扫描稳定性 | ✓ | ✓ | 否 | 只读 |
| B4 参数标准化 | TIMEOUT 按关节写入：失能 → 写 → 回读 → 保存 → 回读 | ✓ | ✓ | 否 | 需确认 |
| B5 **切换到 CAN-FD** | 8 关节 `change_baud 5M --save` → 断电重上电 → 接口配 FD 1M/5M → FD 下 `discover` 全部找到 → 静态复核 | — | ✓ | 否 | 专用确认页；失败给“切回 1M”恢复流程 |
| B6 低增益使能检查 | 逐关节低增益使能/失能，确认无故障 | ✓ | ✓（FD） | 微动 | 急停确认、工作空间清空 |
| B7 零位 | 1.0：限位搜索（包装层）；2.0：Cell 夹具 `set_zero --arm` 或 `--robot-version v2` 限位搜索 | ✓ | ✓ | 是 | 急停、护具、限位、恢复姿态 ≤ 30° |
| B8 夹爪测试 | 按版本和臂侧的方向/行程：全开、全闭、位置误差、温度/电流不持续施力 | 60° | ±90° | 是 | 手远离夹爪 |
| B9 相机测试 | DCXGW20：枚举、1080p60 实际帧率、丢帧、黑屏/花屏、快照；D435i（选配）：序列号、USB3、RGB/深度/IMU | — | ✓ | 否 | 选配未购买 = N/A，不算失败 |
| B10 官方 Demo | 按版本传 FD / ID；记录周期、错误、结束失能 | ✓ | ✓ | 是 | 急停 |
| B11 放行门 | 所有必需项 PASS、无阻断项、CAN 健康快照、证据齐全 → PASS / HOLD | ✓ | ✓ | 否 | HOLD 列出原因和处理方法 |
| B12 报告签核 | 正式报告（含单电机记录、版本、CAN 模式、工具版本、适配器序列号、相机结果、固件）→ 签核 → 打包 | ✓ | ✓ | 否 | 证据哈希 |

向导通用规则：

- 步骤按版本配置生成，1.0 不显示 B5、B9。
- 前一步未 PASS，后一步不亮；允许“从失败步骤重试”，已通过的步骤不重复运动。
- 每个运动步骤前统一“安全确认卡”：急停在手边、工作空间清空、夹爪附近无手。
- 所有运动命令结束（含异常、超时、页面关闭）强制失能恢复。
- 工程师界面保留在“高级工具”，与单电机页一致。

---

## 5. 问题目录与解决方案（新手提示知识库）

沿用单电机向导的做法：后端统一的问题目录，每条包含“标题、原因、解决步骤、是否可重试、技术信息”。在现有 17 条基础上补充：

| 问题 | 判断依据 | 解决方案要点 | 来源 |
|---|---|---|---|
| 终端电阻不对 | CAN_H-CAN_L 应 60Ω；120Ω = 只有一端，40Ω = 三个 | 补/去终端电阻 | openarm_can `diagnose` |
| 菊花链断点 | 连续一段关节无响应 | 检查最后一个响应关节到第一个无响应关节之间的线 | `diagnose` |
| MST_ID 未设置 | 回帧 ID 为 0x00 | 回到单电机工位配置 | `diagnose` |
| 模式不匹配（FD/经典） | 接口 FD 而电机未切 5M，或相反 | 按版本重新配置接口，或执行切换/恢复流程 | openarm_teleop#8、openarm_can#60 |
| 个别关节切 FD 后无响应（常见 J2） | 切换后 `discover` 缺关节 | 用 FD 重写该关节波特率并保存 | openarm#471 |
| 电机不响应 MIT 指令 | CTRL_MODE ≠ MIT | 重写 CTRL_MODE=1 | openarm_can#64 |
| 适配器不支持 FD | 接口无法开启 FD | 换合格适配器（CANable v1 不支持） | openarm_description#21 |
| 总线 bus-off 后接口不恢复 | 1.4.0 `--rm` 默认 0 | 检查接线后重启接口 | openarm_can 1.4.0 |
| 夹爪过热 | MIT 模式夹持硬物持续施力 | 测试时限制夹持时间；评估 POS_FORCE 模式 | openarm_can#81 |
| 零位时关节不动 / 前后臂同时连接失败 | 多臂同时校准 | 一次只接一条臂 | openarm_can#101 |
| 相机名称错乱 | /dev/videoX 顺序变化 | 使用 udev 固定名称；按序列号识别 | 官方 2.0 教程 |
| 固件版本不在基线 | 读取 sw_ver 与基线不符 | 暂停，交工程师用达妙工具升级后复测 | 官方固件更新页 |

---

## 6. 报告与追溯

- **身份**：整机 CN + 关节号（如 `OAF26091701 / R-J2`）；不使用达妙 SN 寄存器做身份（不唯一）。
- **单电机记录进入报告**：每个关节展示单电机工位的读回参数、型号核对结果、时间、工作站版本。
- **版本字段**：`product_version`、`profile_revision`、夹爪版本、工作站版本、官方工具版本（openarm_can 1.4.0）。
- **通信字段**：CAN 模式（经典 / FD）、仲裁速率、数据速率、BRS、错误计数、适配器型号与序列号、物理通道。
- **2.0 额外**：波特率切换记录（每关节前后 `can_br`）、夹爪行程（方向按臂侧）、相机结果与快照、顶部相机选配状态。
- **禁止混用**：放行门校验所有关联证据的 CN、版本、臂侧、CAN 模式一致，否则 HOLD。
- 1.0 已出报告不修改；1.0 新报告模板在 V5 中保持内容等价（回归比对）。

---

## 7. 安全与质量保证

1. **分级**：只读（扫描/复核）→ 参数写入（需确认 + 回读）→ 运动（安全确认卡 + 限位 + 超时 + 强制失能）。
2. **版本锁**：整机 CN 绑定版本后，接口模式、ID、夹爪方向、零位方式都从版本读取；实测与版本不符（例如 FD 下找不到关节、夹爪方向反）立即 HOLD。
3. **FD 切换专项保护**：切换前静态验收必须 PASS；逐关节执行并回读；任何关节失败 → 停止，给出切回 1M 的恢复步骤；Flash 写入次数有限（约 1 万次），避免反复切换。
4. **测试隔离**：修复测试写入真实 `artifacts` 的问题；新增守卫测试：测试运行后真实目录无新增文件。
5. **回归**：冻结 1.0 回归样例（已出报告的数据），每次改动比对 1.0 报告内容等价；2.0 用假驱动覆盖 FD 帧和步骤编排；真机试产前不开放 2.0 正式报告。
6. **变更管理**：每个阶段按 VERSION / changelog 规则发布，写明硬件、安全、报告影响和验证证据。

---

## 8. 实施计划

| 阶段 | 内容 | 交付与验收标准 |
|---|---|---|
| **P0 立即（1-2 天）** | ① 提交当前 0.7.0 / 0.8.0 改动；② 修复测试污染真实记录；③ 安装/构建 `openarm-can-cli` 1.4.0；④ **R-J1 实测**：经典 1M → `change_baud 5M --save` → FD 1M/5M 下 `discover`/`show_param` → 工作站经典帧在 FD 接口上能否读参 → 切回 1M；⑤ 确认 §9 决策项 | 实测记录写入 wiki；决定 B5 的具体执行方式（接口先经典还是先 FD）|
| **P1 版本注册表** | 1.0 / 2.0 产品配置；整机 CN 绑定版本；现有写死表改读配置；TIMEOUT 基础/派生 Profile 统一 | 1.0 回归测试和报告比对不变；2.0 配置可加载 |
| **P2 CAN-FD 通路** | 驱动 FD 收发；接口配置与健康检查按模式；安全检查/使能/零位/Demo 传 FD；报告字段按实测 | 假驱动 FD 测试；R-J1 真机 FD 读参、使能/失能通过 |
| **P3 整臂出厂向导（1.0 先行）** | 复用现有能力，把 03/04 整合成 B1-B12 向导（1.0 步骤）；问题目录扩充；单电机记录挂 CN | 用一台 1.0 臂完整走通，报告与旧流程等价 |
| **P4 2.0 专项** | B5 FD 切换、零位（夹具或 v2 脚本）、夹爪 ±90° 测试、相机工位 | 假驱动 + 2.0 右臂真机走通 |
| **P5 报告与放行门 V5** | 版本/通信/相机/单电机记录字段；证据一致性校验 | 1.0 / 2.0 各出一份样例报告评审 |
| **P6 试产** | 2.0 左右臂各一台完整试产；操作员（新手）按向导独立完成 | 无工程师介入完成；问题目录覆盖出现的所有问题后开放正式出厂 |
| 持续 | 拆分 `workstation.py`（按工位/传输/报告）；归档旧规格文档 | 不影响功能的前提下逐步进行 |

---

## 9. 需要确认的决策

| # | 问题 | 建议 |
|---|---|---|
| 1 | 2.0 零位方式：有没有 Cell 校准夹具？ | 有夹具：官方 `set_zero --arm`（不运动、最准）；没有：限位搜索 `--robot-version v2`（运动，需包装层安全限制） |
| 2 | 左臂方案 A（0x09-0x10）交付给客户时，客户软件如何配置？ | 维持方案 A（已定），在交付说明中提供左臂 ID 配置；若客户需直接使用官方默认软件，需重新评估 |
| 3 | 2.0 相机：出厂按 DCXGW20 + D435i（选配）测，还是按官方 Arducam + ZED-M？PASS 判据（帧率、清晰度）？ | 按实际出货 BOM；判据需要你们给出数值，官方没有公布 |
| 4 | 1.0 是否迁移到 FD？ | 不迁移：已售与在产 1.0 保持经典 CAN 1M；如需 FD 新批次，另立 `1.0-FD` 配置并先样机验证 |
| 5 | 2.0 TIMEOUT 值 | 暂按 1.0 的 5000，P0 实测后确认 |
| 6 | 客户配套 USB-CAN-FD 适配器型号 | 提供 `lsusb` 信息，列入合格适配器清单并做 FD 1M/5M 验证 |
| 7 | 夹爪验收判据（行程误差、温度、夹持时间） | 由你们给出数值；工作站先记录实测值 |
| 8 | 单电机阶段是否直接切 5M（原方案 B） | 维持方案 A；P0 实测后如果 FD 下复核可靠，可再评估 |

---

## 10. 参考

- 官方：[What's New in 2.0](https://docs.openarm.dev/overview/whats-new-in-2.0)、[2.0 电机](https://docs.openarm.dev/hardware/openarm-2.0/motor)、[2.0 Setup 教程](https://docs.openarm.dev/tutorial/setup)、[Motor ID](https://docs.openarm.dev/setup/openarm-setup/motor-id)、[CAN Setup](https://docs.openarm.dev/setup/openarm-setup/can-setup)、[Motor Config](https://docs.openarm.dev/setup/openarm-setup/motor-config)、[1.0 Motor Config](https://docs.openarm.dev/1.0/software/setup/motor-config)、[CLI 参考](https://docs.openarm.dev/api-reference/can/cli)、[固件更新](https://docs.openarm.dev/setup/openarm-setup/motor-firmware-update)、[Cell 校准流程](https://docs.openarm.dev/hardware/openarm-cell/calibration-workflow)、[1.0 夹爪](https://docs.openarm.dev/1.0/hardware/specifications/gripper)
- GitHub：[enactic/openarm_can](https://github.com/enactic/openarm_can)（1.4.0）、[openarm#471](https://github.com/enactic/openarm/issues/471)、[openarm_teleop#8](https://github.com/enactic/openarm_teleop/issues/8)、[openarm_can#60](https://github.com/enactic/openarm_can/issues/60)、[openarm_can#64](https://github.com/enactic/openarm_can/issues/64)、[openarm_can#81](https://github.com/enactic/openarm_can/issues/81)、[openarm_can#101](https://github.com/enactic/openarm_can/issues/101)、[openarm_description#21](https://github.com/enactic/openarm_description/issues/21)
- 本仓库：`docs/DAMIAO_CALIBRATION_POLICY.md`、`docs/WORKSTATION_CHANGELOG.md`、`agent_wiki/openarm-factory-arm-acceptance-flow.md`、`agent_wiki/openarm-factory-acceptance-release-gate.md`
