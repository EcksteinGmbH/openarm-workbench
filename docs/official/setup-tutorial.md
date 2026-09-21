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

---

## 附：2026-09-21 复核时确认「官方没有给」的内容

复核范围：`docs.openarm.dev` 的 2.0 相关页面 + `openarm_can` 1.4.0 全部代码。

| 我们需要的 | 官方状态 |
|---|---|
| 2.0 夹爪开合角度 | **未公布**。`hardware/openarm-2.0/gripper` 只说"结构紧凑、内置相机"，无任何数值 |
| 2.0 夹爪开合方向（哪个符号是张开） | **未公布** |
| 2.0 夹爪电机型号 | **未公布** |
| 2.0 手内相机型号 | **未公布**，只说 "a built-in camera is integrated inside the case" |
| 相机分辨率/帧率/格式 | **未公布** |
| 任何相机验收判据 | **没有**。官方相机设置只做到"认得出" |
| 2.0 关节限位角度 | 未在 general 页给出 |
| 2.0 的 TIMEOUT 值 | 未公布 |

**结论**：我们注册表里 2.0 夹爪的 ±90°（`open_target_rad_by_arm_side`）**没有一手来源**，
来自 `ARM_WORKSTATION_V5_DUAL_VERSION_PLAN.md` §2.1，其自身出处已无法追溯。
已在注册表里标记 `open_target_rad_source: unverified_from_v5_plan` 并保持锁定。

官方确实公布的 2.0 差异（`overview/whats-new-in-2.0`）：

- 电机阵容**和 1.0 相同**：DM-J4310-2EC、DM4340、DM-J8009P
- 负载：标称 4.1 kg / 峰值 6.0 kg（**含末端执行器自重**）
- 末端：紧凑夹爪 + 手内相机 + 可换指尖
- Leader：2.0 的是**无电机的 KER**，不是带电机的主臂
  → 所以 2.0 不存在 Follower/Leader 的电机差异

---

## 附二：2026-09-21 复核的更正与补充

**我在 2026-09-21 第一次复核时下过两个错结论，这里更正：**

| 错误结论 | 实际 | 出处 |
|---|---|---|
| "官方未公布 2.0 夹爪电机型号" | **DM4310，ID 0x08 / MST 0x18** | `examples/demo.cpp:41`、`examples/gripper_posforce.cpp:33` |
| "±90° 没有一手来源" | **`3.14/2.0` = 1.5708 rad 就是官方示例的值** | `examples/gripper_posforce.cpp:45` |

错因相同：**只查了文档页，没查 examples 代码**。官方的硬件参数很多只出现在示例代码里，不在文档。

### 官方夹爪参数（一手来源）

| 项 | 值 | 出处 |
|---|---|---|
| 电机 | DM4310 | `examples/gripper_posforce.cpp:33` |
| ID / MST | 0x08 / 0x18 | 同上 |
| **控制模式** | **POS_FORCE** | 同上 |
| 开合位置 | 3.14/2.0 = 1.5708 rad | `gripper_posforce.cpp:45` |
| 速度上限 | 25.0 rad/s | 同上 |
| 力矩上限 | 0.15 pu（0–1 标幺） | 同上；Python 版写 `1.5/10` |

Python 版同参：`python/examples/test_gripper_posforce.py:24-25, 36-47`

### 为什么官方从 MIT 换成 POS_FORCE

**enactic/openarm_can issue #81**（2025-12-18 提出，2026-01-13 关闭）

> 提问者：MIT 模式无法设置最大力矩，夹到硬物时力矩过大，电机很容易过热
> 官方 tokirobot：完全同意……POS_FORCE 正是我们想走的方向

**时间线注意**：#81 提出时官方主仓库最新 release 是 2025-10-31 的 **1.1**，还没有 2.0。
所以这条反馈**大概率针对的是 1.0**。另外三个官方仓库搜过，没有第二例夹爪过热报告。

### 官方在代码注释里留的坑

`gripper_posforce.cpp:29-32`：

> `init_gripper_motor` 写控制模式是**只写 RAM、不回读**。写丢了电机就还停在 Flash 里的
> 旧模式，而后面所有指令被**静默丢弃**。夹爪不响应就去查 RID 10。

### issue #101：零位校准要一条臂一条臂做

https://github.com/enactic/openarm_can/issues/101（OPEN）

> 官方 abetomo：零位校准应对每条臂单独执行，不要主从同时连着跑。

**对我们尤其重要**：方案 A 把左右臂放在同一条 can0 上。
