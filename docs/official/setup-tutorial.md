# OpenArm 2.0 Setup 教程（官方摘录）

- 原始页面：https://docs.openarm.dev/tutorial/setup
- 抓取日期：2026-09-21
- 覆盖：CAN 配置 / 零位 / 相机

页面章节顺序：Pre-requisites → 安装 uv → **CAN setup** → **Zero position setup**
→ **Camera setup** → Next: Data collection (VR)

---

## 1. CAN 设置

> Connect right arm to can0 and left arm to can1.

官方安装方式是 PPA：

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:openarm/main
sudo apt update
sudo apt install -y libopenarm-can-dev openarm-can-utils
```

配置接口：

```bash
openarm-can-cli can_configure
```

> `can_configure` automatically sets up all CAN interfaces with a CAN FD
> data-phase bitrate of 5 Mbps.

**默认即 CAN FD 1M/5M。** 具体参数见 `external/openarm_can_1.4.0/setup/cli/cli.hpp`
的 `CanConfigureOptions`：sample-point 0.75、dsample-point 0.75、dsjw 2、restart-ms 0。
工作站的 `_can_configure_command()` 已逐字符对齐（0.22.0）。

### 我们的偏离

| 项 | 官方 | 我们（方案 A） |
|---|---|---|
| 左臂总线 | can1 | **can0**（和右臂同一条） |
| 左臂 ID | 0x01–0x08 | **0x09–0x10 / MST 0x19–0x20** |

原因见 `docs/ARM_WORKSTATION_V5_DUAL_VERSION_PLAN.md` §2.3。
**影响：凡是官方用 `--arm`（默认 IDs 1–8）的命令，左臂都必须改用 `--id`。**

---

## 2. 零位设置

> Set up the arm with the jig as shown below.

前置：确认 CAN 接口已启动。

```bash
openarm-can-cli -i can0 set_zero --arm
openarm-can-cli -i can1 set_zero --arm
```

**这是 2.0 官方的零位方式：用夹具把臂机械固定住，再原地清零。**

从 `external/openarm_can_1.4.0/setup/cli/commands/zero_position_commands.cpp` 读到的实现：

- 用**经典 CAN** 连接（`CANSocket(interface, false)`），注释写明
  "Use Classic CAN (CAN 2.0) for configuration sequences to ensure compatibility"
- 逐个 ID：先发失能帧 `FF FF FF FF FF FF FF FD`，再发置零帧 `FF FF FF FF FF FF FF FE`
- **不发任何运动指令**——姿态完全由夹具保证

CLI 选项（`setup/cli/openarm_cli.cpp:239-246`）：

- `-a, --arm` / `--no-arm`：作用于 IDs 1–8，**默认开**
- `--id`：指定 ID，可写 `--id 1,2,3` 或 `--id 1 2 3`；**给了 `--id` 就会覆盖 `--arm`**

**我们左臂要用**：`openarm-can-cli -i can0 set_zero --id 9,10,11,12,13,14,15,16`

### 和 1.0 的区别

1.0 用的是限位搜索（`openarm-can-zero-position-calibration`，**机械臂会运动**）。
2.0 用夹具 + 原地清零，**不运动**，更安全也更准。

---

## 3. 相机设置

**官方 Cell 的相机**（和我们的 BOM 不同）：

| 位置 | 型号 |
|---|---|
| 右腕 / 左腕 / 顶部 | Arducam USB ×3 |
| 头部 | ZED-M（Stereolabs） |

Arducam 需要用 `ArducamUvcConfigUpdateTool` 手动刷写序列号：
`CELL1_CAM_RIGHT`、`CELL1_CAM_LEFT`、`CELL1_CAM_CEILING`。

udev 规则 `/etc/udev/rules.d/99-camera.rules`：

```
SUBSYSTEM=="video4linux", ATTRS{serial}=="CELL*_CAM_RIGHT", ATTR{index}=="0", SYMLINK+="camera_wrist_right"
SUBSYSTEM=="video4linux", ATTRS{serial}=="CELL*_CAM_LEFT", ATTR{index}=="0", SYMLINK+="camera_wrist_left"
SUBSYSTEM=="video4linux", ATTRS{serial}=="CELL*_CAM_CEILING", ATTR{index}=="0", SYMLINK+="camera_ceiling"
SUBSYSTEM=="video4linux", ATTRS{idVendor}=="2b03", ATTRS{idProduct}=="f682", ATTR{index}=="0", SYMLINK+="camera_head_stereo"
```

验证：`ls -l /dev/camera_*`

### 官方没有给的东西

- **没有分辨率、帧率、格式要求**
- **没有任何验收判据**——官方只做到"认得出相机"，不做"测相机好坏"

### 对我们的意义

可以照搬的是**识别方案**：udev 固定软链接，Arducam 按序列号匹配、ZED 按 VID/PID 匹配。
我们的 DCXGW20 / D435i 同样可以按 VID/PID 或序列号固定命名。

出厂**判据**（帧率、丢帧、清晰度）官方没有，必须我们自己定 —— 见 V5 §9-3。
