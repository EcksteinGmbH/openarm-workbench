# OpenArm / Damiao 最新调研记录

## 1. 调研范围

本次调研基于 2026-04-17 用户提供的新版官方来源，目标是更新仓库中关于：

- OpenArm 实际使用的电机型号
- 官方软件建站步骤
- Damiao 开源仓库与上位机工具
- 当前仓库设计与官方流程的偏差

主要来源：

- OpenArm BOM: https://docs.openarm.dev/hardware/bill-of-materials/procuring-components/
- OpenArm Setup: https://docs.openarm.dev/software/setup/
- OpenArm Motor ID: https://docs.openarm.dev/software/setup/motor-id/
- OpenArm CAN Setup: https://docs.openarm.dev/software/setup/can-setup/
- OpenArm Motor Config: https://docs.openarm.dev/software/setup/motor-config/
- Damiao 开源仓库:
  - https://gitee.com/kit-miao/DM-J8009P-2EC
  - https://gitee.com/kit-miao/DM-J4340P-2EC
  - https://gitee.com/kit-miao/DM-J4340-2EC
  - https://gitee.com/kit-miao/DM-J4310-2EC
  - https://gitee.com/kit-miao/dm-tools


## 2. OpenArm 当前官方硬件结论

根据 OpenArm BOM 页面，截至 2026-04-13，OpenArm 使用的电机型号已经可以明确对应到具体达妙产品：

| Joint | OpenArm 官方型号 |
|------|------------------|
| J1, J2 | `DM-J8009P-2EC` |
| J3 | `DM-J4340P-2EC` |
| J4 | `DM-J4340-2EC` |
| J5, J6, J7, J8 | `DM-J4310-2EC V1.1` |

注意：

- BOM 页面给出的数量是整套系统采购数量，不是单臂单关节数量
- 我们仓库原先只保留了 `DM8009 / DM4340 / DM4310` 这种驱动层抽象型号
- 新版 profile 应同时保留“官方商品型号”和“驱动层基础型号”的映射关系


## 3. OpenArm 当前官方软件流程

## 3.1 Step 0: 设备准备

OpenArm 官方把通信设备分成了两类：

### 用于电机 ID 设置

- `Damiao USB CAN Debugger`
- `Windows`

### 用于后续控制与进一步设置

- `SocketCAN-compatible interface device`
- `Ubuntu 22.04/24.04` 或其他支持 SocketCAN 的 Linux

这和我们仓库里之前“统一用 Linux 本地 Web 工站完成全部步骤”的假设不完全一致。

## 3.2 Step 1: Motor ID Configuration

OpenArm 官方当前推荐流程是：

- 在 Windows 中使用达妙调试助手
- 先 `ReadParam`
- 再写 `Sender CAN ID / Receiver (Master) ID`
- 再 `WriteParam`

官方页面还明确说明：

- 如果知道当前 ID，理论上也可以直接通过 CAN 帧改 ID
- 但这不是官方教程默认路径

官方当前 ID 对应关系：

| Joint | Sender CAN ID | Receiver / Master ID |
|------|----------------|----------------------|
| J1 | `0x01` | `0x11` |
| J2 | `0x02` | `0x12` |
| J3 | `0x03` | `0x13` |
| J4 | `0x04` | `0x14` |
| J5 | `0x05` | `0x15` |
| J6 | `0x06` | `0x16` |
| J7 | `0x07` | `0x17` |
| J8 | `0x08` | `0x18` |

额外细节：

- 官方把达妙调试助手定位为：
  - 配 ID
  - 简单校准
  - 固件版本与控制模式检查
- 页面还给出了校准/测试阶段推荐电流：
  - `DM-J4310`: 约 `0.3A`
  - `DM-J4340`: 约 `0.3A`
  - `DM-J8009P`: 约 `0.75A`

## 3.3 Step 2: Setup SocketCAN Interface

OpenArm 官方当前 Linux 侧步骤已经明确落在 SocketCAN 工具链上：

- 安装 `can-utils`, `iproute2`, `libopenarm-can-dev`, `openarm-can-utils`
- 用 `ip link show` 查找 `can0`, `can1`, `slcan0` 等接口
- 配置方式有两种：
  - `openarm-can-configure-socketcan can0`
  - 手动 `ip link set can0 type can bitrate 1000000 && ip link set can0 up`

这意味着：

- 只要我们的 USB-CAN 适配器最终能在 Linux 中暴露为标准 SocketCAN 接口
- 仓库里的 Linux Web 工站路线就仍然成立

## 3.4 Step 4: Motor Configuration

OpenArm 官方当前把后续配置拆成三部分：

1. 设置电机波特率
2. 设置零位
3. 验证电机通信

值得特别注意的新版细节：

- 波特率设置时，官方要求先在 `CAN 2.0` 下完成
- 电机参数写入限制为约 `10000` 次
- 支持从 `125000` 到 `5000000` 的多档波特率
- 推荐使用 `openarm-can-motor-check <send_id> <recv_id> can0` 验证最终通信状态


## 4. Damiao 开源仓库最新结论

## 4.1 电机资料仓库

新版电机资料仓库已经和 OpenArm BOM 对齐：

- `DM-J8009P-2EC`
- `DM-J4340P-2EC`
- `DM-J4340-2EC`
- `DM-J4310-2EC`

这意味着我们仓库里原先只写通用型号的做法已经不够准确。

建议：

- profile 层使用 OpenArm 官方商品型号
- 驱动层保留到 `DM8009 / DM4340 / DM4310` 的兼容映射

## 4.2 DM-Tools 上位机

`dm-tools` 仓库目前明确包含：

- `USB转CAN`
- `USB转CAN软件使用教程.pdf`

这说明达妙官方/社区目前仍然把“USB-CAN 调试助手 + 上位机教程”作为重要工作流一部分。

对我们仓库的意义是：

- “识别 USB-CAN 调试器”与“识别整条总线上的所有电机 ID”是合理且必要的能力
- 工站不能只围绕串口桥设计


## 5. 对当前仓库的直接影响

## 5.1 需要修正的旧认知

以下旧认知已经不够准确：

- “Damiao 电机主要通过串口桥工作”
- “OpenArm 初始化主流程默认由 Linux 工站独立完成”
- “J1~J8 只需保留 `DM8009 / DM4340 / DM4310` 即可”

需要更新为：

- OpenArm 官方当前把 ID 配置默认放在 Windows + 达妙调试助手
- Linux + SocketCAN 主要负责后续配置、通信验证与控制
- profile 应使用 OpenArm BOM 中的具体官方型号

## 5.2 对当前工作站设计的建议

建议把工作站拆成两层：

### 层 A：官方兼容工作流

- 支持识别 `SocketCAN` 接口
- 支持识别 `gs_usb`/USB-CAN 适配器
- 支持整臂总线 ID 盘点
- 支持 `openarm-can-motor-check` 风格的通信复核

### 层 B：增强型本地工作流

- 在已知当前 ID 的前提下，支持 Linux 本地 Web 界面直接改参
- 支持单电机建站、保存、零位、测试

换言之：

- 我们的工站可以比官方教程更强
- 但文档与 UI 必须明确标出“官方推荐路径”和“本仓库增强路径”的区别


## 6. 已更新到仓库的内容

本次基于官方新版资料，建议同步更新：

- `profiles/openarm/openarm_v1.yaml`
- `README.md`
- 通信工作站 spec 文档

并在代码中增加：

- OpenArm 官方商品型号到驱动层基础型号的映射


## 7. 后续建议

下一步建议继续做三件事：

1. 在 UI 中明确区分：
   - `官方流程`
   - `增强流程`
2. 在连接页明确展示：
   - `Damiao USB CAN Debugger`
   - `SocketCAN-compatible interface`
   - `gs_usb` 识别结果
3. 在 profile 与报告里统一使用 OpenArm 官方型号命名
