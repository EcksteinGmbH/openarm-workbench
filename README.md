# OpenARM Damiao 电机工作站项目

当前工作站版本：`0.6.3-single-id-safety`

版本更新记录见 [docs/WORKSTATION_CHANGELOG.md](/home/ubuntu/Projects/OpenARM/docs/WORKSTATION_CHANGELOG.md)。

## 项目简介
这是一个面向 OpenARM 的达妙电机工作站仓库，当前同时覆盖：

- 单电机建站与参数写入
- 整臂 CAN2.0 / SocketCAN 通信扫描
- USB-CAN / `gs_usb` 适配器识别
- OpenARM profile 与报告工件输出

## 项目特性

- ✓ 完整的damiao电机SDK支持
- ✓ OpenARM 官方 Joint / ID 模板
- ✓ 支持多种控制模式（MIT、位置+速度、速度、力位混合）
- ✓ 实时状态监控（位置、速度、扭矩、温度）
- ✓ 错误检测和处理
- ✓ Web图形界面（基于Flask + Socket.IO）
- ✓ SocketCAN / USB-CAN 接口识别
- ✓ 整条机械臂电机 ID 盘点
- ✓ 命令行测试工具
- ✓ 完整的测试示例

## 目录结构

```
OpenARM/
├── docs/                                # 文档目录
│   └── SDK_RESEARCH.md                   # SDK调研文档
├── src/                                 # 源代码目录
│   ├── damiao_motor_driver.py             # Damiao电机驱动（主）
│   └── motor_driver.py                   # 旧版驱动（CAN总线）
├── web/                                 # Web界面
│   ├── app.py                          # Flask后端服务器
│   ├── templates/
│   │   └── index.html                  # 主页面模板
│   ├── static/
│   │   ├── css/style.css              # 样式文件
│   │   └── js/app.js                 # 前端JavaScript
│   ├── requirements.txt                  # Web依赖
│   └── README.md                      # Web界面文档
├── examples/                            # 示例代码
│   └── test_damiao_motor.py             # 测试示例
├── tests/                              # 测试目录
│   └── test_motor_driver.py             # 测试用例
├── config/                             # 配置文件目录
│   └── config.yaml                      # 配置文件
├── external/                           # 外部SDK
│   └── qt5_damiao_motor_friction_detection/  # 开源SDK
├── start_web.sh                        # Web服务启动脚本
├── requirements.txt                      # Python依赖
└── README.md                           # 项目说明文档
```

## 开发进度

- [x] 完成SDK调研
- [x] 下载并整理开源SDK
- [x] 搭建开发环境
- [x] 编写电机驱动模块
- [x] 实现基础控制功能
- [x] 编写测试示例
- [x] 开发Web图形界面
- [ ] 实际硬件测试
- [ ] 文档完善

## OpenARM 当前官方电机型号

依据 OpenARM 官方 BOM：

- `J1`, `J2`: `DM-J8009P-2EC`
- `J3`: `DM-J4340P-2EC`
- `J4`: `DM-J4340-2EC`
- `J5`, `J6`, `J7`, `J8`: `DM-J4310-2EC`

仓库内部仍保留到基础驱动型号的兼容映射：

- `DM-J8009P-2EC` -> `DM8009`
- `DM-J4340P-2EC` / `DM-J4340-2EC` -> `DM4340`
- `DM-J4310-2EC` -> `DM4310`

## 快速开始

### 方式一：Web界面（推荐）

#### 环境要求
- Python 3.8+
- Linux
- 对于整臂扫描：SocketCAN 或 `gs_usb` / USB-CAN 适配器
- 对于官方推荐的电机 ID 配置：Windows + Damiao USB CAN Debugger

#### 安装依赖
```bash
pip install -r requirements.txt
pip install -r web/requirements.txt
```

#### Linux CAN 环境准备

整臂扫描和 SocketCAN 单电机建站需要 Linux CAN 工具与 `python-can`：

```bash
sudo apt update
sudo apt install can-utils
pip install python-can
```

使用 `gs_usb` / `gsusb1002enc` 一类 USB-CAN 适配器时，先加载驱动并配置 `can0`：

```bash
sudo modprobe gs_usb
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details link show can0
```

工站默认使用 CAN 2.0 / `1000000` bitrate；写入 ID、保存 Flash、零位和 Demo 类动作前，请确认只连接目标设备、急停/断电手段可用，并在操作后执行断电重上电复核。

#### 启动Web服务
```bash
./start_web.sh
```

或手动启动：
```bash
cd web
python app.py
```

#### 访问界面
打开浏览器访问: http://localhost:5000

### 方式二：命令行测试

#### 运行测试示例
```bash
python examples/test_damiao_motor.py
```

#### 整臂 CAN2.0 通信扫描
```bash
./scan_arm_can.sh
```

或显式指定参数：

```bash
python3 -m src.arm_can_scan_cli --channel can0 --bitrate 1000000 --profile openarm_v1 --output-dir ./artifacts/can_scan
```

输出内容：
- `scan_summary.json`：扫描摘要、缺失关节、异常节点、意外节点
- `joint_results.csv`：逐关节通信结果
- `report.html` / `job.json` / `events.jsonl`：工站兼容工件

也支持环境变量：

```bash
OPENARM_CAN_CHANNEL=can0 \
OPENARM_CAN_BITRATE=1000000 \
OPENARM_CAN_PROFILE=openarm_v1 \
OPENARM_SCAN_OUTPUT_DIR=./artifacts/can_scan \
./scan_arm_can.sh
```

#### 基本使用
```python
from src.damiao_motor_driver import DamiaoMotorDriver, Motor, DM_Motor_Type, Control_Type

# 创建驱动器
driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
driver.connect()

# 创建电机
motor = Motor(MotorType=DM_Motor_Type.DM4310, SlaveID=1, MasterID=0)
driver.addMotor(motor)

# 使能电机
driver.enable(motor)

# 速度控制
driver.switchControlMode(motor, Control_Type.VEL)
driver.control_Vel(motor, 5.0)  # 5 rad/s

# 失能电机
driver.disable(motor)
driver.disconnect()
```

## 注意事项

1. **安全使用**: 最好在上电后几秒再使能电机
2. **温度监控**: 需要监控MOS管和线圈温度，防止过热
3. **状态监控**: 需要实时监控电机状态，及时处理错误
4. **官方流程差异**: OpenARM 官方当前把“电机 ID 设置”与“Linux SocketCAN 建站/控制”分成了两套流程
5. **通信方式**: 本仓库同时支持串口桥和 SocketCAN，但 OpenARM 官方后续软件链路以 SocketCAN 为主
6. **商业使用**: 使用达妙资料与工具时，请关注对应仓库/工具的许可证与授权条款
7. **整臂扫描模式**: `src.arm_can_scan_cli` 与 Web 扫描只做参数读取和 ID 对账，不发送动作控制帧

## 技术文档

- 真机现场测试检查表请查看 [docs/OPENARM_LIVE_TEST_CHECKLIST.md](/home/ubuntu/Projects/OpenARM/docs/OPENARM_LIVE_TEST_CHECKLIST.md)
- 最新调研记录请查看 [docs/SDK_RESEARCH.md](/home/ubuntu/Projects/OpenARM/docs/SDK_RESEARCH.md)
- 最新通信工作站 spec 请查看 [docs/ARM_COMM_WORKSTATION_V1_SPEC.md](/home/ubuntu/Projects/OpenARM/docs/ARM_COMM_WORKSTATION_V1_SPEC.md)

## 许可证

基于开源SDK修改：https://github.com/cdssywc/qt5_damiao_motor_friction_detection
非商业用途仅限学术、研究和教学目的。
