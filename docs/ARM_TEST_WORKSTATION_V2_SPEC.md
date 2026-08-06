# OpenARM 机械臂测试工作站 V2 Spec

更新时间：2026-04-17
状态：Proposed

## 1. Summary

本 spec 将当前仓库收敛为一套可执行的 Linux 本地 Web 工站规格，用于 OpenARM 电机和整臂的建站、配置、零位、低风险测试与验收。

V2 的核心目标：

- 在 Linux 下完成 CAN 接口识别与配置
- 在 Linux 下完成单电机 ID 配置与参数写入
- 在 Linux 下完成单电机零位与低风险测试
- 完成整臂 8 电机总线盘点与一致性验收
- 生成可追溯的任务工件与 HTML 报告

V2 保留单屏约束：

- `1920x1080`
- 浏览器缩放 `100%`
- 不允许页面级纵向滚动
- 不同层级功能统一通过 Tab 切换

## 2. Canonical Inputs

### 2.1 Official OpenARM assumptions

基于 2026-04-17 时可查的 OpenARM 官方资料，V2 采用以下固定真值：

- `J1`, `J2` -> `DM-J8009P-2EC`
- `J3` -> `DM-J4340P-2EC`
- `J4` -> `DM-J4340-2EC`
- `J5`, `J6`, `J7`, `J8` -> `DM-J4310-2EC`

固定 ID 映射：

- `ESC_ID`: `0x01 .. 0x08`
- `MST_ID`: `0x11 .. 0x18`

固定前提：

- 官方默认 Windows + Damiao Debugging Tools 负责首轮 ID 配置
- 但本工作站必须提供 Linux 原生配置闭环
- Linux 侧主通信链路以 SocketCAN 为标准路径

### 2.2 Profile truth source

V2 的默认真值来源是：

- [openarm_v1.yaml](/home/ubuntu/Projects/OpenARM/profiles/openarm/openarm_v1.yaml)

profile 覆盖规则：

- 允许本地文件覆盖
- 覆盖方式为整文件替换
- 不做深度 merge

## 3. Scope

### 3.1 In scope

- `system_can` 接口识别与配置
- `serial_bridge` 单电机识别、读参、写参、保存、零位、测试
- `socketcan` 单电机识别、读参、写参、保存、零位、测试
- 整臂总线盘点
- 整臂参数一致性验收
- 报告输出

### 3.2 Out of scope

- ROS2 控制站
- 连续轨迹控制
- 高级伺服调参
- 双臂协同控制
- MES / 数据库对接
- Windows 打包
- 长时间自动巡检

## 4. Task Model

V2 定义 6 个任务类型，其中前 5 个进入正式验收，`engineering_mode` 不进入默认验收。

### 4.1 `can_interface_setup`

目标：

- 识别 Linux 下的 `can0/can1/slcan0`
- 配置 CAN 2.0 / CAN FD 参数
- 执行 bring up / bring down
- 记录接口配置结果

### 4.2 `single_id_config`

目标：

- 识别单电机
- 写入 `ESC_ID` / `MST_ID`
- 可选写入 `CTRL_MODE` / `TIMEOUT` / `can_br`
- 回读校验
- 可选保存 Flash
- 生成复核报告

### 4.3 `single_motor_commissioning`

目标：

- 完成单电机完整建站
- 写入全部目标参数
- 保存 Flash
- 执行零位
- 执行低风险测试
- 输出单电机建站报告

### 4.4 `single_comm_check`

目标：

- 只读校验单电机
- 检查 ID、参数、状态、温度、在线性
- 不写参数
- 不保存 Flash

### 4.5 `arm_bus_scan`

目标：

- 盘点整条总线上的所有节点
- 输出在线、缺失、意外、重复 ID
- 生成总线 inventory

### 4.6 `arm_acceptance`

目标：

- 按 profile 对 J1~J8 做参数和状态一致性验收
- 允许只做通信验收
- 可选按 profile 执行低风险逐 Joint 测试

### 4.7 `engineering_mode`

目标：

- 非标准工位的手工调试

限制：

- 默认 UI 不展示入口
- 必须显式开启
- 必须填写原因
- 所有覆盖参数必须进入报告

## 5. Transport Model

### 5.1 Transports

V2 固定三类 transport：

- `system_can`
- `serial_bridge`
- `socketcan`

### 5.2 Capability matrix

| Capability | system_can | serial_bridge | socketcan |
|---|---:|---:|---:|
| list_interfaces | yes | no | no |
| configure_interface | yes | no | no |
| connect_device | no | yes | yes |
| scan_bus | no | yes | yes |
| read_params | no | yes | yes |
| write_params | no | yes | yes |
| save_flash | no | yes | yes |
| zero | no | yes | yes |
| test | no | yes | yes |
| arm_scan | no | no | yes |
| arm_acceptance | no | no | yes |

约束：

- `arm_bus_scan` 与 `arm_acceptance` 的标准 transport 只允许 `socketcan`
- `single_*` 任务优先支持 `serial_bridge` 和 `socketcan`
- `system_can` 只管理 Linux CAN 接口，不直接控制电机

## 6. Job State Machine

### 6.1 Shared states

所有任务统一使用以下状态集合的子集：

- `draft`
- `prepared`
- `interface_ready`
- `device_connected`
- `identified`
- `profile_selected`
- `params_written`
- `params_verified`
- `params_saved`
- `zero_ready`
- `zeroed`
- `test_ready`
- `tested`
- `inventory_ready`
- `acceptance_ready`
- `reported`
- `passed`
- `failed`
- `cancelled`

### 6.2 `can_interface_setup`

流转：

`draft -> prepared -> interface_ready -> reported -> passed`

失败流转：

- 任一步骤失败 -> `failed`

### 6.3 `single_id_config`

流转：

`draft -> device_connected -> identified -> profile_selected -> params_written -> params_verified -> params_saved? -> reported -> passed`

说明：

- `params_saved` 为可选
- 若不保存 Flash，允许从 `params_verified` 直接进入 `reported`

### 6.4 `single_motor_commissioning`

流转：

`draft -> device_connected -> identified -> profile_selected -> params_written -> params_verified -> params_saved -> zero_ready -> zeroed -> test_ready -> tested -> reported -> passed`

### 6.5 `single_comm_check`

流转：

`draft -> device_connected -> identified -> acceptance_ready -> reported -> passed`

### 6.6 `arm_bus_scan`

流转：

`draft -> device_connected -> inventory_ready -> reported -> passed`

### 6.7 `arm_acceptance`

流转：

`draft -> device_connected -> inventory_ready -> acceptance_ready -> tested? -> reported -> passed`

### 6.8 Failure handling

统一失败规则：

- 参数回读不一致 -> `failed`
- 设备断开 -> `failed`
- 接口配置失败 -> `failed`
- 零位失败 -> `failed`
- 测试失败 -> `failed`
- 整臂存在缺失节点、重复 ID、严重参数不一致 -> `failed`

### 6.9 Cancel rules

取消规则：

- `params_saved` 之前允许取消
- `params_saved` 之后不允许取消写参数类任务
- `arm_bus_scan` / `arm_acceptance` 在 `reported` 前允许取消

## 7. Selection Rules

### 7.1 Single motor tasks

标准模式：

- 扫描结果必须且只能有 1 个候选节点

异常情况：

- `0` 个候选节点 -> 任务失败，提示检查供电/接线/波特率/接口状态
- `>1` 个候选节点 -> 任务失败，提示进入专家模式并指定 `current_id`

专家模式：

- 必须输入 `current_id`
- 若输入 ID 不可读 -> 任务失败

### 7.2 Arm tasks

整臂任务固定规则：

- 按 profile 的 `target_esc_id` 顺序扫描
- 逐 Joint 串行处理
- 不允许并发写入或并发测试

## 8. Safety Gates

### 8.1 Save Flash

`save_flash` 前必须满足：

- 已完成回读校验
- 当前 transport 支持保存
- 当前电机能够成功失能
- 当前总线上没有选机歧义

### 8.2 Zero

`zero` 前必须满足：

- 当前任务类型为 `single_motor_commissioning`
- 当前状态为 `params_saved`
- 电机已失能
- 当前无 fault
- `MOS < 60C`
- `Rotor < 80C`
- 连续 3 次刷新稳定
- 操作者已确认机械基准已对齐

### 8.3 Low-risk test

测试前必须满足：

- 当前状态为 `zeroed` 或 `acceptance_ready`
- 当前无 fault
- 温度不过限
- 当前 transport 支持测试
- 操作者已确认安全区域清空

## 9. Test Profiles

V2 固定定义 3 种测试档位：

### 9.1 `comm_ping`

动作：

- `enable`
- `refresh`
- `disable`

用途：

- 最低风险通信确认

### 9.2 `micro_mit_ping`

动作：

- `enable`
- `q=+0.05 rad, dq=0, tau=0, kp=10, kd=0.2, 250ms`
- `q=0 rad, 250ms`
- `disable`

用途：

- 单机关节低风险动作确认

### 9.3 `return_to_zero_check`

动作：

- 从零位附近做极小幅度往返
- 检查是否返回容差范围

默认任务与测试档位绑定：

- `single_comm_check` -> `comm_ping` only
- `arm_bus_scan` -> no test
- `arm_acceptance` -> `comm_ping` default, `micro_mit_ping` optional
- `single_motor_commissioning` -> `micro_mit_ping`

## 10. API Contract

### 10.1 Common response shape

成功响应：

```json
{
  "success": true
}
```

失败响应：

```json
{
  "success": false,
  "message": "..."
}
```

### 10.2 Error codes

- `400` 参数错误、状态不允许
- `404` session/job/interface 不存在
- `409` 当前 transport 不支持、系统状态冲突
- `502` 设备运行时失败、通信失败、系统命令失败

### 10.3 Config API

`GET /api/config`

返回：

- profiles
- transports
- job_types
- tabs
- temp_limits
- test_profiles
- feature_flags

### 10.4 System CAN APIs

`GET /api/system/can-interfaces`

返回：

```json
{
  "interfaces": [
    {
      "name": "can0",
      "driver": "gs_usb",
      "adapter_kind": "gsusb1002enc",
      "state": "UP",
      "bitrate": 1000000,
      "dbitrate": 5000000,
      "fd_enabled": true,
      "bus_info": "1-1.2"
    }
  ],
  "recommended_channel": "can0"
}
```

`POST /api/system/can-interfaces/configure`

请求：

```json
{
  "name": "can0",
  "mode": "can20",
  "bitrate": 1000000,
  "dbitrate": null,
  "fd_enabled": false,
  "tool": "ip_link"
}
```

说明：

- `mode` 只能是 `can20` 或 `canfd`
- `tool` 允许 `ip_link` 或 `openarm_helper`

`POST /api/system/can-interfaces/up`

请求：

```json
{
  "name": "can0"
}
```

`POST /api/system/can-interfaces/down`

请求：

```json
{
  "name": "can0"
}
```

### 10.5 Device APIs

`POST /api/device/connect`

请求：

```json
{
  "transport": "socketcan",
  "connection": {
    "channel": "can0",
    "bitrate": 1000000
  }
}
```

返回：

- `device_session_id`
- `capabilities`
- `connection_state`

`POST /api/device/disconnect`

`POST /api/device/scan`

请求：

```json
{
  "device_session_id": "sess_x",
  "job_type": "single_motor_commissioning",
  "profile_id": "openarm_v1",
  "current_id": 1,
  "expert_mode": false
}
```

返回：

- `candidates`
- `conflicts`
- `summary`
- `scan_mode`

`POST /api/device/line-inventory`

返回：

- `inventory`
- `summary`

### 10.6 Job APIs

`POST /api/jobs`

请求：

```json
{
  "job_type": "single_motor_commissioning",
  "device_session_id": "sess_x",
  "profile_id": "openarm_v1",
  "target_joint": "J4",
  "expert_mode": false
}
```

返回：

- `job_id`
- `status`
- `allowed_actions`

`GET /api/jobs/{job_id}`

返回：

- `job`
- `motors`
- `events`
- `allowed_actions`

`POST /api/jobs/{job_id}/apply-profile`

请求：

```json
{
  "target_joint": "J4",
  "profile_id": "openarm_v1",
  "overrides": null
}
```

`POST /api/jobs/{job_id}/write-params`

`POST /api/jobs/{job_id}/verify-params`

`POST /api/jobs/{job_id}/save-flash`

`POST /api/jobs/{job_id}/zero`

请求：

```json
{
  "confirmed": true
}
```

`POST /api/jobs/{job_id}/run-test-profile`

请求：

```json
{
  "profile": "micro_mit_ping",
  "confirmed": true
}
```

`POST /api/jobs/{job_id}/run-comm-check`

`POST /api/jobs/{job_id}/run-arm-scan`

`POST /api/jobs/{job_id}/run-arm-acceptance`

`POST /api/jobs/{job_id}/cancel`

`GET /api/jobs/{job_id}/report`

### 10.7 WebSocket events

固定事件：

- `job_state`
- `motor_status`
- `interface_status`

`job_state`：

```json
{
  "job_id": "job_x",
  "status": "params_written",
  "step": "params_written",
  "message": "参数写入完成",
  "progress": 45
}
```

`motor_status`：

```json
{
  "job_id": "job_x",
  "joint_or_slot": "J4",
  "position": 0.01,
  "velocity": 0.0,
  "torque": 0.0,
  "t_mos": 31.0,
  "t_rotor": 35.0,
  "motor_status": "DISABLED",
  "transport_online": true
}
```

`interface_status`：

```json
{
  "name": "can0",
  "state": "UP",
  "bitrate": 1000000,
  "fd_enabled": false
}
```

## 11. UI Contract

### 11.1 Top-level tabs

顶层固定 5 个主 Tab：

- `工站`
- `接口`
- `识别`
- `执行`
- `报告`

### 11.2 Execution subtabs

执行页固定 4 个二级 Tab：

- `ID`
- `参数`
- `零位`
- `测试`

显示规则：

- `can_interface_setup` 不进入执行页
- `single_id_config` 显示 `ID + 参数`
- `single_motor_commissioning` 显示全部四个二级 Tab
- `single_comm_check` 只显示 `测试`
- `arm_bus_scan` 只显示总线扫描操作面板
- `arm_acceptance` 显示 `参数 + 测试`

### 11.3 Panel layout

固定三栏：

- 左：任务步骤
- 中：当前操作面板
- 右：状态、告警、日志

要求：

- 主按钮始终可见
- 结果矩阵不推动页面整体变高
- modal 打开时背景不滚动

## 12. Report Contract

### 12.1 Artifact directory

每个任务固定落盘到：

`artifacts/jobs/{yyyyMMdd_HHmmss}_{job_id}/`

### 12.2 Required files

- `job.json`
- `events.jsonl`
- `report.html`
- `summary.csv`
- `motors/{slot_or_joint}.json`

### 12.3 Report sections

报告必须包含：

- 任务摘要
- 接口配置
- 目标 profile
- per-motor / per-joint 结果
- 参数变更记录
- 零位结果
- 测试结果
- 放行结论

### 12.4 Audit fields

至少保留：

- `job_type`
- `transport`
- `interface_name`
- `operator`
- `expert_mode`
- `save_flash_performed`
- `test_profile`
- `failure_reason`

## 13. Acceptance Criteria

### 13.1 P0: Config and UI shell

验收通过条件：

- `GET /api/config` 返回新增任务和测试档位
- 页面保留单屏布局
- 顶层 5 个 Tab 可正常切换
- 较大内容只在局部区域滚动

### 13.2 P1: System CAN

验收通过条件：

- 能识别 `gs_usb` / `gsusb1002enc`
- 能显示 `can0/can1/slcan0` 状态
- 能成功执行 down / configure / up
- 配置结果可在 UI 与接口 API 中回读

### 13.3 P2: Single motor Linux commissioning

验收通过条件：

- `serial_bridge` 单电机完整建站通过
- `socketcan` 单电机完整建站通过
- 改 `ESC_ID / MST_ID / can_br` 后能回读一致
- 保存 Flash 后断电重上电仍保留
- 零位执行通过
- `micro_mit_ping` 通过

### 13.4 P3: Single motor read-only check

验收通过条件：

- 单电机只读复核不触发写入
- 异常温度、fault、缺失 ID 可正确报错
- 报告中明确标出失败原因

### 13.5 P4: Arm scan and acceptance

验收通过条件：

- 整臂能识别 J1~J8
- 缺失节点会失败
- duplicate ESC_ID 会失败
- unexpected node 会失败
- `MST_ID / can_br / CTRL_MODE` 不一致会失败
- 结果矩阵与 HTML 报告一致

### 13.6 UI acceptance

验收通过条件：

- `1920x1080` 下无页面级滚动条
- 顶层与二级 Tab 切换无页面溢出
- 危险动作前有 modal 确认
- 主按钮始终可见

### 13.7 Regression acceptance

验收通过条件：

- 现有 `line_inventory` 继续可用
- 现有 `gs_usb` 识别继续可用
- 现有工件落盘不退化

## 14. Test Plan

### 14.1 Unit tests

必须覆盖：

- profile 解析
- transport capability gating
- 状态机流转
- 回读校验逻辑
- 零位前置检查
- 测试档位门控

### 14.2 API tests

必须覆盖：

- system CAN 接口配置 API
- 单电机建站完整生命周期
- 整臂扫描完整生命周期
- 取消规则
- 错误码映射

### 14.3 UI tests

必须覆盖：

- 单屏无滚动
- Tab 切换稳定
- 扫描矩阵高亮
- modal 打开时背景冻结

### 14.4 Hardware validation

必须覆盖：

- `gsusb1002enc` 接口识别
- CAN 2.0 配置
- 单电机 Linux 改 ID
- 单电机保存 Flash
- 单电机零位
- 单电机低风险测试
- 整臂 8 电机总线验收

## 15. Implementation Order

建议开发顺序：

1. `system_can` 与接口配置 API
2. `socketcan` 写参/保存/零位补齐
3. 任务状态机升级
4. UI 切到新的任务模型
5. 整臂验收与报告升级
6. 工程模式下沉

## 16. Open Questions

以下问题不阻断 V2 立项，但在实现前需要明确：

- `socketcan` 下达妙写参帧在当前硬件上的稳定性是否与串口桥一致
- 零位引导是否需要按 OpenARM 左臂/右臂区分机械说明
- `arm_acceptance` 是否默认启用 `comm_ping` 还是完全只读
- 操作者身份是本地输入还是系统账户继承

## 17. Sources

- OpenARM Setup Guide: https://docs.openarm.dev/software/setup/
- Motor ID Configuration: https://docs.openarm.dev/software/setup/motor-id/
- CAN Setup: https://docs.openarm.dev/software/setup/can-setup/
- Motor Configuration: https://docs.openarm.dev/software/setup/motor-config/
- OpenARM CAN Library: https://docs.openarm.dev/software/can/
- OpenARM BOM: https://docs.openarm.dev/hardware/bill-of-materials/procuring-components/
- OpenARM Motor Specifications: https://docs.openarm.dev/hardware/specifications/motor/
- DM-Tools: https://gitee.com/kit-miao/dm-tools
