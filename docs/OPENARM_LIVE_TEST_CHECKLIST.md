# OpenARM 真机测试现场检查表

本文档用于 OpenARM + Damiao 电机本地 Web 工站的现场测试。目标是把官方流程、当前工站能力和已遇到的现场问题合并成一份可执行检查表，减少误判和重复排查。

## 1. 官方流程对齐

官方 OpenARM 1.0 文档将流程分为：

1. 电机 ID 配置：先确认每个关节的发送 CAN ID 和接收 Master ID。
2. SocketCAN 建站：Linux 侧使用 SocketCAN 接口。
3. Motor Communication Test：用 `candump` / `cansend` 做基础通信检查。
4. Motor Configuration：设置波特率、零位，并复核通信。
5. Demo Run：只在 ID、CAN、零位和安全条件都完成后执行。

本工站与官方流程的关系：

- “电机 ID 盘点 / 整臂扫描”对应官方 ID 与通信检查。
- “参数一致性矩阵”对应官方 Motor Configuration 后的回读复核。
- “工站安全零位”只执行人工摆位后的 `disable -> set_zero -> save -> refresh`，不主动发送运动轨迹；它只能作为工站静态零位写入/回读检查。
- 官方 Step 4 的 `openarm-can-zero-position-calibration` 是动态零位校准，官方文档明确提示校准开始后机械臂会自动移动；它与工站安全零位不是同一个测试。
- 工站内置的官方动态零位适配脚本保留官方左/右臂 ID 映射，但启动阶段已改为多帧位置确认和低刚度缓使能；禁止在未验证当前位置反馈稳定时直接使用高刚度锁臂。
- 官方动态零位会主动寻找机械限位。若现场只需要出厂基础验收，应先完成静态扫描、参数一致性、CAN 健康、低刚度使能保持检查；动态零位和 Demo 必须单独确认风险后再执行。
- 官方 Step 5 Demo 会执行使能、位置控制、力矩控制、夹爪控制、状态监测和安全失能；未执行 Demo 时，报告只能写基础静态检查，不能写官方完整验收完成。
- “Demo / Follower 验证”必须放在官方零位完成、急停可用、工作空间清空之后。

## 2. CAN 与上电准备

每次 USB-CAN 重插、机械臂断电重上电、线束调整、刷新工站后，都先检查 CAN 接口。

```bash
ip -details link show can0
```

期望看到：

- `UP`
- `LOWER_UP`
- `ERROR-ACTIVE`
- `bitrate 1000000`

若不是上述状态，重新配置 CAN 2.0 / 1 Mbps：

```bash
sudo modprobe gs_usb
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details link show can0
```

注意：

- 工站默认 CAN 2.0 / 1 Mbps。
- 如果后端提示 `RTNETLINK answers: Operation not permitted`，说明当前 Web 服务进程没有权限直接配置网卡，需要在终端手动执行上面的 `sudo ip link` 命令。
- `can0` 为 `DOWN`、`STOPPED` 或没有 `LOWER_UP` 时，Web 扫描不到 ID 是预期现象。

## 3. 低层通信 sanity check

连接 Web 工站前，可以用官方建议的底层方式验证第一个电机：

```bash
candump can0
```

另一个终端发送使能和失能帧：

```bash
cansend can0 001#FFFFFFFFFFFFFFFC
cansend can0 001#FFFFFFFFFFFFFFFD
```

对于右臂 J1，期望响应 ID 为 `011`；左臂 J1 若按本工站 profile，期望发送 ID 为 `009`，响应 ID 为 `019`。

如果 `cansend` 后完全没有响应，优先排查：

- 电机是否上电，24V 是否到达电机端子。
- CANH / CANL 是否接反或松动。
- 120R 终端电阻是否符合当前链路。
- `can0` 是否仍是 `UP / LOWER_UP / ERROR-ACTIVE / 1000000`。
- 电机实际 ESC_ID / MST_ID 是否与 profile 一致。

## 4. ID 与 profile 判定

当前工站 profile 采用单臂出厂模板，leader 和 follower 的左右臂 ID 规则相同；左臂保留我们之前确定的 `0x09-0x10 / 0x19-0x20` 规划。

| Arm | Joint | ESC_ID | MST_ID |
| --- | --- | --- | --- |
| 右臂 | J1-J8 | `0x01-0x08` | `0x11-0x18` |
| 左臂 | J1-J8 | `0x09-0x10` (`9-16`) | `0x19-0x20` (`25-32`) |

说明：

- follower 右臂仍使用右臂 ID。
- follower 左臂仍使用左臂 ID。
- 不需要为 leader/follower 拆出不同 ID profile，除非后续硬件定义发生变化。
- OpenArm 官方脚本默认示例多为右臂 `0x01-0x08 / 0x11-0x18`；本工站已提供适配版 `tools/openarm-can-zero-position-calibration`，运行 `--arm_side left_arm` 时使用左臂 `0x09-0x10 / 0x19-0x20`，不能直接套默认右臂 ID。

## 5. 扫描结果解释

### ID 盘点通过

表示总线能看到目标 ESC_ID / MST_ID，不等于机械臂已经可运动。

继续检查：

- `CTRL_MODE` 是否为 MIT。
- `can_br` 是否匹配 1 Mbps。
- 状态是否为 `DISABLED` / `ENABLED`。
- 是否存在 `UNDERVOLTAGE`、`OVERVOLTAGE`、`MOTOR_ERROR` 等状态。

### `can_br=4`

Damiao 参数中的 `can_br` 是枚举值，不是实际 bitrate 数字。官方 Motor Configuration 文档中的映射为：

| can_br | bitrate |
| --- | --- |
| 4 | 1000000 |

因此工站看到 `can_br=4` 时应按 1 Mbps 处理，不应误判为 4 bps 或未知速率。

### `TIMEOUT` 参数

当前左右臂 Profile 的目标值均为 J1-J8=`5000`。现场处理建议：

- 单电机测试默认只读取并记录 `TIMEOUT`，不要直接写参数或保存 Flash。
- 记录在参数一致性矩阵中。
- 参数标准化只在整臂验收阶段执行，并必须由工作台按所选 Profile 逐关节取值，禁止给 J1-J8 统一写入一个数值。
- 写入时必须逐关节执行 `disable -> write TIMEOUT -> readback -> save_flash -> readback`；断电重启后按所选左右臂 Profile 再次复核。
- 不要用低频或自定义控制循环反复尝试裸使能，否则可能触发 `COMM_LOST`；动态测试必须使用能够满足通信看门狗要求的官方控制流程。

## 6. 电源与状态故障排查

若扫描能看到 ID，但关节状态为 `UNDERVOLTAGE` 或 `OVERVOLTAGE`：

1. 不做零位、Demo、Follower 或微动测试。
2. 测电源输出端电压。
3. 测故障关节电机端子电压。
4. 对比同一总线中正常关节和异常关节的供电。
5. 检查 XT30 / GH 线束、转接板、分线端子和接插件压接。
6. 故障消失后，断电重上电，再重新扫描。

当前工站建议把以下状态视为阻断项：

- `OVERVOLTAGE`
- `UNDERVOLTAGE`
- `MOTOR_ERROR`
- `COMMUNICATION_LOST`
- `OVERHEATING`

## 7. 真机测试顺序

若当天目标是“按官方完整流程跑通一条机械臂”，按以下顺序执行。工站中的“辅助静态写零位”只能用于排查和辅助记录，不能替代 Step 4 官方动态零位。

1. 硬件接线确认：电源、CANH/CANL、终端电阻、急停。
2. `ip -details link show can0`，必要时重配 CAN 2.0 / 1 Mbps。
3. `candump` / `cansend` 验证一颗已知 ID 电机。
4. 打开 Web 工站，连接 SocketCAN。
5. 创建整臂任务，选择右臂或左臂 profile。
6. 执行 ID 盘点。
7. 执行整臂参数扫描。
8. 处理状态故障，直到所有目标关节无电源类故障。
9. 在“官方命令”区对代表关节执行一次 `openarm-can-motor-check`，完成动态零位前的官方通信复核；同一上电周期内证据有效时不要在零位后重复执行。
10. 人工摆到官方零位姿态，夹爪闭合为零位。
11. 清空工作空间、确认急停和快速断电手段，然后执行 `openarm-can-zero-position-calibration` 官方动态零位。
12. 官方动态零位结束后，断电重上电并重新扫描，确认 ID、波特率、零位和状态仍正常；通过后直接进入 Demo 前置门禁。
13. 执行官方 Step 5 `openarm-can-demo` 或按当前机械臂配置构建后的等价官方 Demo。
14. Demo 结束后确认电机已安全失能，无 fault、无异常声音、无异常发热。
15. 生成整臂出厂报告；只有官方动态零位和 Step 5 Demo 都通过时，报告才能写“官方完整流程通过”。

### Leader 基础静态检查范围

Leader 侧基础静态检查不要求执行 Follower 跟随或持续运动 Demo，但也不能替代官方动态零位和 Step 5 Demo。若当天目标只是基础静态检查，可按以下项目判定：

- CAN 2.0 / 1 Mbps 接口正常。
- J1-J8 全部在线，ESC_ID / MST_ID 与 profile 一致。
- J1-J8 `TIMEOUT` 已按所选左右臂 Profile 保存，并在断电重启后复核保持。
- 工站安全零位完成，并在断电重启后所有关节位置接近 0。该项只证明静态零位写入/回读，不证明官方动态零位校准已完成。
- 最终状态为 `DISABLED`，无 fault、无过温、无缺失关节。

Leader 基础静态检查报告应明确标注：

- 官方动态零位校准未执行时，应标注为 `PENDING`。
- `Demo / Follower` 未执行，作为本次基础静态检查范围外项目。
- 未执行自定义持续使能控制循环。
- 后续如需官方完整验收或 Follower 验证，必须在完整双臂、急停可用、工作空间清空的环境中按官方程序另行测试。

2026-05-09 右臂 Leader 现场结果（历史记录；当时采用全臂 `TIMEOUT=1000`，不作为当前规则）：

- 右臂 `R-J1 ~ R-J8` 全部在线。
- `TIMEOUT=1000` 已保存，断电重启后复核通过。
- 工站安全零位完成，断电重启后位置约 `-0.0001907 rad`。该记录已重新归类为“工站基础静态检查”，不是官方动态零位校准完成证明。
- 最终状态 `DISABLED`，无 fault。
- 已生成基础静态检查报告：
  `artifacts/reports/leader_basic_acceptance/right_arm_20260509/OpenARM_Leader_Right_Arm_Factory_Test_Report_20260509_v5.pdf`

## 8. 危险动作前确认

以下动作必须只连接目标设备，并确认急停、断电手段、工作空间：

- 写入 ESC_ID / MST_ID。
- 写入 `can_br`、`CTRL_MODE`、`TIMEOUT` 等参数。
- 保存 Flash。
- 设置零位。
- 微动测试。
- Demo / Follower。

若当天目标是通信验收，优先完成扫描、报告和故障定位，不急于执行运动类测试。

## 9. 参考资源

- OpenArm Website: https://openarm.dev/
- OpenArm Documentation: https://docs.openarm.dev/
- OpenArm GitHub: https://github.com/enactic/openarm
- OpenArm Setup Guide: https://docs.openarm.dev/software/setup/
- Motor ID Configuration: https://docs.openarm.dev/software/setup/motor-id/
- SocketCAN Setup: https://docs.openarm.dev/software/setup/can-setup/
- Motor Communication Test: https://docs.openarm.dev/software/setup/configure-test/
- Motor Configuration: https://docs.openarm.dev/software/setup/motor-config/
- CAN Library: https://docs.openarm.dev/software/can/
- Motor Specifications: https://docs.openarm.dev/hardware/specifications/motor/
