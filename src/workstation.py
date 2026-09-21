"""
OpenARM motor commissioning workstation services.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from src.damiao_motor_driver import (
    Control_Type,
    DM_Motor_Type,
    DM_variable,
    DamiaoMotorDriver,
    DamiaoSocketCANDriver,
    LIMIT_PARAM,
    Motor,
)
from src.formal_factory_report import render_formal_factory_report


ROOT_DIR = Path(__file__).resolve().parent.parent
BUILTIN_PROFILE_DIR = ROOT_DIR / "profiles" / "openarm"
OVERRIDE_PROFILE_DIR = ROOT_DIR / "config" / "profiles"
PRODUCT_REGISTRY_DIR = ROOT_DIR / "profiles" / "products"
ARTIFACTS_DIR = ROOT_DIR / "artifacts" / "jobs"
FACTORY_DIR = ROOT_DIR / "artifacts" / "factory"
FACTORY_MOTORS_DIR = FACTORY_DIR / "motors"
FACTORY_ARMS_DIR = FACTORY_DIR / "arms"
FACTORY_BUNDLES_DIR = FACTORY_DIR / "bundles"
FACTORY_ARM_RECORDS_DIR = FACTORY_DIR / "arm_records"
FACTORY_REPORTS_DIR = FACTORY_DIR / "reports"
FACTORY_EVIDENCE_DIR = FACTORY_DIR / "evidence"
# Formal acceptance reports live beside the factory dir, not inside it. Declared as
# a constant so the test redirect and its guard can both see it.
FORMAL_REPORTS_DIR = ROOT_DIR / "artifacts" / "reports"
VENDOR_MAINTENANCE_DIR = FACTORY_DIR / "vendor_maintenance"
VENDOR_MAINTENANCE_RECORDS_DIR = VENDOR_MAINTENANCE_DIR / "records"
VENDOR_MAINTENANCE_LOGS_DIR = VENDOR_MAINTENANCE_DIR / "logs"
DMTOOL_APPIMAGE_PATH = Path(os.environ.get("DMTOOL_APPIMAGE_PATH", "/home/ubuntu/下载/DMTool-v2.1.6.0-fix-x86_64.AppImage"))
OFFICIAL_ZERO_COMMAND = "openarm-can-zero-position-calibration"
OFFICIAL_MOTOR_CHECK_COMMAND = "openarm-can-motor-check"
OFFICIAL_CHANGE_BAUDRATE_COMMAND = "openarm-can-change-baudrate"
OFFICIAL_DEMO_COMMAND = "openarm-can-demo"
LOCAL_OPENARM_COMMANDS = {
    OFFICIAL_ZERO_COMMAND: ROOT_DIR / "tools" / OFFICIAL_ZERO_COMMAND,
    OFFICIAL_MOTOR_CHECK_COMMAND: ROOT_DIR / "tools" / OFFICIAL_MOTOR_CHECK_COMMAND,
    OFFICIAL_CHANGE_BAUDRATE_COMMAND: ROOT_DIR / "tools" / OFFICIAL_CHANGE_BAUDRATE_COMMAND,
    OFFICIAL_DEMO_COMMAND: ROOT_DIR / "tools" / OFFICIAL_DEMO_COMMAND,
    "openarm-can-configure-socketcan": ROOT_DIR / "tools" / "openarm-can-configure-socketcan",
}
WORKSTATION_VERSION = (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip() if (ROOT_DIR / "VERSION").exists() else "0.0.0-local"
OPENARM_ALLOWED_COMMAND_PREFIXES = ("openarm-",)
OFFICIAL_DEMO_DEFAULT_ENABLE_HOLD_MS = 1500
OFFICIAL_DEMO_DEFAULT_PHASE_HOLD_S = 3.0
OFFICIAL_DEMO_MIN_GRIPPER_TRAVEL_RAD = 0.8

# Operational TIMEOUT for every assembled-arm joint, written during whole-arm
# acceptance. Kept here so the generic profile, the derived arm profiles and
# commissioning_policy cannot drift apart. J1-J4 used to sit at a superseded 1000
# in the generic profile only, which would have failed a scan run with the default
# profile; no production job ever used it (all used the derived arm profiles).
# CAN timing the official CLI applies, from openarm_can 1.4.0
# setup/cli/cli.hpp CanConfigureOptions. Kept identical so an interface prepared here
# and one prepared with the official tool behave the same on the same bus.
OFFICIAL_CAN_SAMPLE_POINT = "0.75"
OFFICIAL_CAN_DSAMPLE_POINT = "0.75"
OFFICIAL_CAN_DSJW = "2"
OFFICIAL_CAN_RESTART_MS = 0

# Damiao register codes for `can_br`, from openarm_can 1.4.0
# setup/cli/commands/change_motor_baudrate_commands.cpp BAUDRATE_MAP.
OFFICIAL_BAUDRATE_CODES = {
    125000: 0, 200000: 1, 250000: 2, 500000: 3, 1000000: 4, 2000000: 5,
    2500000: 6, 3200000: 7, 4000000: 8, 5000000: 9, 8000000: 10, 10000000: 11,
}

WHOLE_ARM_TARGET_TIMEOUT = 5000

# Arm records written before the product registry existed carry no product_version.
# Every such record on disk is a 1.0 Follower, so they are read as 1.0 rather than
# rejected or flagged.
DEFAULT_PRODUCT_VERSION = "openarm_1_0"
OFFICIAL_COMMAND_STDOUT_LIMIT = 60000
OFFICIAL_COMMAND_STDERR_LIMIT = 12000
OPENARM_SUPPORTED_BAUDRATES = [125000, 200000, 250000, 500000, 1000000, 2000000, 2500000, 3200000, 4000000, 5000000, 8000000, 10000000]
ZERO_COMMAND_CONFIRMATIONS = {
    "workspace_clear": "工作空间已清空",
    "estop_ready": "急停/断电手段可用",
    "zero_pose_confirmed": "机械臂已摆到官方零位姿态",
    "power_stable": "24V 供电稳定",
    "one_arm_only": "当前只对单侧机械臂执行校准",
}
DEMO_COMMAND_CONFIRMATIONS = {
    "workspace_clear": "工作空间已清空",
    "estop_ready": "急停/断电手段可用",
    "zero_calibrated": "零位校准已经完成并复核",
    "comm_check_passed": "通信扫描/验收已经通过",
    "low_speed": "Demo/Follower 将以低速低风险方式执行",
}
MOTOR_CHECK_CONFIRMATIONS = {
    "motor_powered": "目标电机/机械臂已上电",
    "can_interface_up": "SocketCAN 接口已 UP 且 bitrate 正确",
    "id_pair_verified": "CAN ID 与 Receiver ID 已按工位记录核对",
    "no_motion_expected": "本步骤只做通信复核，不作为动作测试",
}
BAUDRATE_COMMAND_CONFIRMATIONS = {
    "single_motor_only": "当前只连接目标电机，避免误写多电机",
    "can20_mode": "当前接口处于 CAN 2.0 模式",
    "write_limit_ack": "已知电机参数写入有次数限制，不会频繁脚本化写入",
    "power_cycle_plan": "写入后会断电重上电并复核持久化结果",
}
WORKBENCH_ZERO_CONFIRMATIONS = {
    "pose_aligned": "机械臂已按 OpenARM 官方零位姿态手动摆好",
    "gripper_closed": "夹爪已按官方说明闭合为零位",
    "comm_scan_passed": "单臂 J1~J8 通信扫描已通过",
    "workspace_clear": "工作空间已清空",
    "estop_ready": "急停/断电手段可用",
    "no_motion_ack": "理解本工站内置零位只写零位，不发送动作控制命令",
    "one_arm_only": "当前只对单侧机械臂执行零位校准",
}
LEGACY_JOB_TYPE_ALIASES = {
    "single_commissioning": "single_id_config",
    "arm_verification": "arm_comm_scan",
}
PUBLIC_JOB_TYPE_ALIASES = {
    "single_id_config": "single_commissioning",
    "arm_comm_scan": "arm_verification",
}
SINGLE_SCAN_JOB_TYPES = {"single_id_config", "single_param_config", "single_comm_check"}


# 0x01-0x20 spans every ID OpenARM assigns: right arm ESC 0x01-0x08 / MST 0x11-0x18
# and left arm ESC 0x09-0x10 / MST 0x19-0x20. Anything narrower makes a correctly
# configured motor look absent, which is the one answer a scan must never give.
DEFAULT_SCAN_IDS = [*range(0x01, 0x21)]
DEFAULT_ARM_SCAN_IDS = [*range(0x01, 0x21)]
FAST_SCAN_RIDS = [
    DM_variable.ESC_ID,
    DM_variable.MST_ID,
]
SINGLE_SCAN_RIDS = [
    DM_variable.ESC_ID,
    DM_variable.MST_ID,
    DM_variable.CTRL_MODE,
    DM_variable.TIMEOUT,
    DM_variable.can_br,
    DM_variable.sw_ver,
    DM_variable.sub_ver,
    DM_variable.SN,
]
ARM_VERIFY_RIDS = SINGLE_SCAN_RIDS + [DM_variable.Gr, DM_variable.KT_Value, DM_variable.PMAX, DM_variable.VMAX, DM_variable.TMAX]
PARAM_CONFIG_RIDS = ARM_VERIFY_RIDS + [DM_variable.KT_Value]
HEALTH_REPORT_RIDS = [
    DM_variable.ESC_ID,
    DM_variable.MST_ID,
    DM_variable.CTRL_MODE,
    DM_variable.TIMEOUT,
    DM_variable.can_br,
    DM_variable.UV_Value,
    DM_variable.OV_Value,
    DM_variable.hw_ver,
    DM_variable.sw_ver,
    DM_variable.sub_ver,
    DM_variable.SN,
]
TEMP_LIMITS = {"mos": 60.0, "rotor": 80.0}
# Read-only motor inspection: everything an operator may need to see before assembly.
# Order defines the display order; nothing here is ever written.
SINGLE_INSPECT_FIELDS = [
    ("ESC_ID", DM_variable.ESC_ID, "节点 ID (ESC_ID)", "identity"),
    ("MST_ID", DM_variable.MST_ID, "反馈 ID (MST_ID)", "identity"),
    ("CTRL_MODE", DM_variable.CTRL_MODE, "控制模式", "identity"),
    ("can_br", DM_variable.can_br, "CAN 波特率", "identity"),
    ("TIMEOUT", DM_variable.TIMEOUT, "通信看门狗 TIMEOUT", "identity"),
    ("Gr", DM_variable.Gr, "减速比 Gr", "motor"),
    ("KT_Value", DM_variable.KT_Value, "力矩常数 KT", "motor"),
    ("PMAX", DM_variable.PMAX, "位置上限 PMAX", "motor"),
    ("VMAX", DM_variable.VMAX, "速度上限 VMAX", "motor"),
    ("TMAX", DM_variable.TMAX, "力矩上限 TMAX", "motor"),
    ("UV_Value", DM_variable.UV_Value, "欠压保护值", "protection"),
    ("OV_Value", DM_variable.OV_Value, "过压保护值", "protection"),
    ("hw_ver", DM_variable.hw_ver, "硬件版本", "version"),
    ("sw_ver", DM_variable.sw_ver, "固件版本", "version"),
    ("sub_ver", DM_variable.sub_ver, "子版本", "version"),
    ("SN", DM_variable.SN, "SN 寄存器（不唯一，仅作证据）", "version"),
]
SINGLE_INSPECT_RIDS = [rid for _, rid, _, _ in SINGLE_INSPECT_FIELDS]
SINGLE_WIZARD_ARM_PROFILES = {
    "right_arm": {"profile_id": "openarm_right_arm_v1", "prefix": "R", "label": "右臂"},
    "left_arm": {"profile_id": "openarm_left_arm_v1", "prefix": "L", "label": "左臂"},
}
SINGLE_WIZARD_PRODUCT_LINES = {"openarm_2_0": "OpenArm 2.0", "openarm_1_0": "OpenArm 1.0"}
# Operator-facing troubleshooting catalog for the beginner single-motor wizard.
# Problems that stop the operator dead - no CAN port, the port will not start, or it
# cannot be opened. The wizards raise these in a blocking dialog instead of only the
# in-page panel, because nothing further can be tried until someone fixes the port.
BLOCKING_PROBLEM_CODES = {
    # Needs a hardware verification or a decision that cannot happen on this page.
    "arm_step_locked",
    "can_interface_missing",
    "can_interface_down",
    "can_bus_error",
    "adapter_missing",
    "interface_prepare_failed",
    "connect_failed",
}

SINGLE_MOTOR_PROBLEMS: Dict[str, Dict[str, Any]] = {
    "can_interface_missing": {
        "title": "没有找到 USB-CAN 适配器",
        "message": "电脑上没有检测到所选的 CAN 口。",
        "solutions": [
            "检查 USB-CAN 适配器（DM-USB2FDCAN）是否插好，指示灯是否亮。",
            "换一个 USB 口重新插入，等待 3 秒后再点一次。",
            "确认选择的 CAN 口名称正确（一般是 can0）。",
        ],
    },
    "can_interface_down": {
        "title": "CAN 口没有启动",
        "message": "工作站尝试自动启动 CAN 口，但没有成功。",
        "solutions": [
            "请工程师在终端执行：sudo ip link set can0 type can bitrate 1000000 && sudo ip link set can0 up",
            "执行完后回到这里再点一次。",
        ],
    },
    "can_bus_error": {
        "title": "CAN 总线通信异常",
        "message": "CAN 口处于错误状态（BUS-OFF / ERROR-PASSIVE），通常是接线或波特率问题。",
        "solutions": [
            "检查 CAN 线 CANH / CANL 是否接反、是否松动。",
            "检查总线两端是否有 120Ω 终端电阻。",
            "确认电机已经上电。",
            "处理后点「处理好了，再试一次」，工作站会重启 CAN 口。",
        ],
    },
    "adapter_missing": {
        "title": "没有检测到 USB-CAN 适配器",
        "message": "电脑上一个 CAN 口都没有，说明适配器没插好或驱动没加载。",
        "solutions": [
            "确认 USB-CAN 适配器（DM-USB2FDCAN）已插入电脑，指示灯亮。",
            "换一个 USB 口重新插入，等 3 秒后再点「检测适配器」。",
            "达妙双路适配器必须刷 SocketCAN(gs_usb) 固件；刷成 DMTool 固件时 Linux 下不会出现 can0。",
            "仍然没有时请工程师在终端执行：sudo modprobe gs_usb",
        ],
    },
    "interface_prepare_failed": {
        "title": "CAN 口配置失败",
        "message": "工作站无法把这个 CAN 口配置成所需的波特率并启动。",
        "solutions": [
            "确认没有其他程序（DMTool、candump 脚本）正在占用这个 CAN 口。",
            "请工程师在终端执行：sudo ip link set can0 down && sudo ip link set can0 type can bitrate 1000000 && sudo ip link set can0 up",
            "执行完后回到这里再点一次「配置并启动」。",
        ],
    },
    "arm_cn_invalid": {
        "title": "整机编号不符合规则",
        "message": "整机编号要按出厂规则命名，否则报告归档会对不上。",
        "solutions": [
            "格式是 OA + F/L + 6 位日期 + 2 位序号，例如 OAF26092001。",
            "F 表示 Follower，L 表示 Leader。",
            "直接用页面给出的建议编号最稳妥，它已经避开了已用过的号。",
        ],
    },
    "arm_cn_taken": {
        "title": "这个整机编号已经用过了",
        "message": "工作站里已经有一台这个编号的机械臂。",
        "solutions": [
            "如果你想继续测那一台，从下面的列表里选它，不要新建。",
            "如果这是另一台新臂，把序号加一（例如 ...01 改成 ...02）。",
        ],
    },
    "arm_has_evidence": {
        "title": "这台机械臂不能删除",
        "message": "它上面已经有测试记录了，删掉就等于销毁证据。",
        "solutions": [
            "只有刚建好、还没做过任何测试的档案才能删除。",
            "如果产品版本或编号填错了，而且已经测过：请交给工程师处理，不要自行删除。",
            "如果只是不想继续测这台，直接不管它即可，它不会影响别的机械臂。",
        ],
    },
    "arm_not_found": {
        "title": "找不到这台机械臂的档案",
        "message": "输入的整机编号在工作站里没有对应记录。",
        "solutions": [
            "确认整机编号输入正确（右臂 Follower 形如 OAF26092001）。",
            "如果这是一台新臂，请先在「整机建档」这一步建立档案。",
            "在「已建档机械臂」列表里查看已有编号，直接选择而不是手输。",
        ],
    },
    "arm_step_locked": {
        "title": "这一步还不能执行",
        "message": "这台臂的产品版本里，这一步所依赖的参数还没有经过真机验证。",
        "solutions": [
            "先完成该项的真机验证，再回到这一步。",
            "页面上会写明具体缺什么；把它交给工程师处理。",
            "在验证完成前，工作站不会让这一步运行，也不会为这台臂出正式报告。",
        ],
    },
    "arm_step_out_of_order": {
        "title": "前一步还没完成",
        "message": "出厂流程有固定顺序，跳过前面的步骤会让后面的结果不可信。",
        "solutions": [
            "回到高亮显示的那一步，先把它做完。",
            "如果前一步做过但没通过，请先处理它的问题再重试。",
        ],
    },
    "arm_motor_record_mismatch": {
        "title": "电机记录和这台臂对不上",
        "message": "要挂载的单电机记录，和这台臂的产品版本或关节不一致。",
        "solutions": [
            "确认选的是这台臂的记录：产品版本（1.0 / 2.0）和关节号都要对上。",
            "一个关节只能挂一条记录；要换请先移除原来那条。",
            "找不到对应记录时，说明这颗电机还没做单电机配置，请先去「单电机测试」完成。",
        ],
    },
    "bus_no_motor": {
        "title": "CAN 口正常，但总线上没有电机",
        "message": "工作站已经能使用这个 CAN 口，但扫描 ID 0x01–0x20 没有任何电机应答。",
        "solutions": [
            "确认电机已上电（24V），电源指示灯亮。",
            "检查电机和 USB-CAN 之间的 CAN 线，CANH / CANL 不要接反。",
            "检查总线两端是否有 120Ω 终端电阻。",
            "双路适配器请确认电机接的是所选的这个通道（can0 / can1）。",
            "处理后点「重新检查总线」。",
        ],
    },
    "connect_failed": {
        "title": "无法打开 CAN 口",
        "message": "CAN 口存在，但工作站连接失败。",
        "solutions": [
            "确认没有其他程序（如 DMTool、candump 脚本）独占这个 CAN 口。",
            "拔插 USB-CAN 适配器后再试。",
        ],
    },
    "no_motor_found": {
        "title": "没有找到电机",
        "message": "总线上没有电机应答（已扫描 ID 0x01–0x20）。",
        "solutions": [
            "确认电机已上电（电源指示灯亮），供电电压正常。",
            "检查电机和 USB-CAN 之间的 CAN 线是否接好。",
            "新电机默认波特率是 1 Mbps；如果电机被改过波特率，请用达妙上位机 DMTool 查看并改回 1 Mbps。",
            "如果电机 ID 被改成了 0x20 以上，请用 DMTool 查看当前 ID。",
        ],
    },
    "multiple_motors": {
        "title": "总线上有多颗电机",
        "message": "为防止改错电机，一次只能配置一颗。",
        "solutions": [
            "断电，只保留要配置的这一颗电机连在 CAN 线上。",
            "重新上电后点「处理好了，再试一次」。",
        ],
    },
    "motor_fault": {
        "title": "电机报故障",
        "message": "电机状态里有故障码，不能继续写参数。",
        "solutions": [
            "断电等待 10 秒后重新上电，再点「处理好了，再试一次」。",
            "检查供电电压是否在电机额定范围内。",
            "如果故障一直存在，用 DMTool 查看具体故障码并交给工程师处理，这颗电机先不要装配。",
        ],
    },
    "status_read_anomaly": {
        "title": "电机状态无法识别",
        "message": "电机返回了工作站不认识的状态码。",
        "solutions": [
            "断电重上电后再试一次。",
            "如果仍然出现，暂停这颗电机，交给工程师用 DMTool 复核。",
        ],
    },
    "motor_overtemp": {
        "title": "电机温度过高",
        "message": "MOS 或线圈温度超过安全阈值。",
        "solutions": [
            "断电让电机冷却 10 分钟后再试。",
            "检查电机是否被外力卡住或长时间堵转。",
        ],
    },
    "disable_failed": {
        "title": "电机无法失能",
        "message": "写参数/保存前必须先让电机失能，但没有成功。",
        "solutions": [
            "断电重上电（上电后电机默认是失能状态），再点「重新开始这颗电机」。",
            "如果反复出现，停止操作并联系工程师。",
        ],
    },
    "write_failed": {
        "title": "参数写入失败",
        "message": "电机没有确认参数写入。",
        "solutions": [
            "检查 CAN 线是否松动，电机是否掉电。",
            "点「重新开始这颗电机」，重新识别后再写一次（已写入的部分会重新检查）。",
            "如果连续失败两次，停止操作并联系工程师。",
        ],
    },
    "param_mismatch": {
        "title": "参数回读和目标不一致",
        "message": "写入后读回来的参数和目标值不同。",
        "solutions": [
            "点「重新开始这颗电机」，重新识别后再写入一次。",
            "如果仍不一致，可能是电机固件不支持该参数，先不要保存，联系工程师。",
        ],
    },
    "save_failed": {
        "title": "保存到 Flash 失败",
        "message": "参数没能保存到电机内部存储，断电后会丢失。",
        "solutions": [
            "不要断电，直接点「处理好了，再试一次」。",
            "如果仍失败，点「重新开始这颗电机」从写入参数重新做。",
        ],
    },
    "readback_no_response": {
        "title": "重新上电后电机没有应答",
        "message": "按新 ID 读不到电机。",
        "solutions": [
            "确认电机已经重新上电，等待 3 秒后点「处理好了，再试一次」。",
            "检查 CAN 线在断电重上电时有没有碰松。",
            "如果一直没有应答，可能保存没有生效：点「重新开始这颗电机」重新识别。",
        ],
    },
    "readback_mismatch": {
        "title": "断电后参数没有保持",
        "message": "重新上电后读到的参数和目标不一致，说明保存没有生效。",
        "solutions": [
            "点「重新开始这颗电机」，重新写入并保存一次。",
            "保存后等待 2 秒再断电。",
            "如果第二次仍然不保持，这颗电机先不要装配，联系工程师。",
        ],
    },
    "job_state_invalid": {
        "title": "步骤顺序不对",
        "message": "当前步骤还不能执行这个操作。",
        "solutions": ["按页面上亮起的按钮顺序操作；如果页面状态混乱，点「重新开始这颗电机」。"],
    },
    "unknown_error": {
        "title": "发生未知错误",
        "message": "工作站遇到了没有预料到的错误。",
        "solutions": [
            "点「重新开始这颗电机」再试一次。",
            "如果仍出现，把下面的技术信息截图发给工程师。",
        ],
    },
}
PARAM_TARGET_FIELD_MAP = {
    "target_ctrl_mode": DM_variable.CTRL_MODE,
    "target_timeout": DM_variable.TIMEOUT,
    "target_can_br": DM_variable.can_br,
    "target_mst_id": DM_variable.MST_ID,
    "target_kt_value": DM_variable.KT_Value,
    "target_gr": DM_variable.Gr,
    "target_pmax": DM_variable.PMAX,
    "target_vmax": DM_variable.VMAX,
    "target_tmax": DM_variable.TMAX,
}
ARM_MATRIX_FIELDS = [
    ("ESC_ID", "target_esc_id"),
    ("MST_ID", "target_mst_id"),
    ("CTRL_MODE", "target_ctrl_mode"),
    ("TIMEOUT", "target_timeout"),
    ("can_br", "target_can_br"),
    ("Gr", "target_gr"),
    ("KT_Value", "target_kt_value"),
    ("PMAX", "target_pmax"),
    ("VMAX", "target_vmax"),
    ("TMAX", "target_tmax"),
]
ARM_REQUIRED_SCAN_FIELDS = {"ESC_ID", "MST_ID", "CTRL_MODE", "TIMEOUT", "can_br"}
DM_CAN_BR_CODE_TO_BITRATE = {
    0: 125000,
    1: 250000,
    2: 500000,
    3: 800000,
    4: 1000000,
    5: 2000000,
    6: 2500000,
    7: 3200000,
    8: 4000000,
    9: 5000000,
}
DM_CAN_BR_BITRATE_TO_CODE = {bitrate: code for code, bitrate in DM_CAN_BR_CODE_TO_BITRATE.items()}


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def _atomic_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _atomic_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _html_table(rows: Iterable[Iterable[Any]]) -> str:
    return "".join(
        "<tr>" + "".join(f"<td>{escape(str(value if value is not None else '-'))}</td>" for value in row) + "</tr>"
        for row in rows
    )


def _html_report_manifest(rows: Iterable[Dict[str, Any]]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('owner') or '-'))}</td>"
        f"<td>{escape(str(item.get('title') or '-'))}</td>"
        f"<td>{escape(str(item.get('report_type') or '-'))}</td>"
        f"<td>{escape(str(item.get('pdf_path') or item.get('html_path') or item.get('json_path') or '-'))}</td>"
        "</tr>"
        for item in rows
    )
    return f"""
    <section class="manifest-section">
        <h2>Attached Report Manifest</h2>
        <table>
            <thead><tr><th>Owner</th><th>Title</th><th>Type</th><th>Primary File</th></tr></thead>
            <tbody>{body or '<tr><td colspan="4">No attached reports</td></tr>'}</tbody>
        </table>
    </section>
    """


def _report_sections_from_rows(rows: Iterable[Iterable[Any]]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    current = {"title": "Test Results", "rows": []}
    for raw_row in rows:
        row = list(raw_row)
        if row and str(row[0]).strip() and all(not str(value).strip() for value in row[1:]):
            if current["rows"] or current["title"] != "Test Results":
                sections.append(current)
            current = {"title": str(row[0]), "rows": []}
        else:
            current["rows"].append(row)
    if current["rows"] or current["title"] != "Test Results":
        sections.append(current)
    return sections


def _status_class(value: Any) -> str:
    label = str(value or "").strip().lower()
    if label in {"pass", "passed"}:
        return "pass"
    if label in {"warning", "review", "hold"}:
        return "warning"
    if label in {"fail", "failed", "error"}:
        return "fail"
    return "neutral"


def _compact_json_for_html(value: Any) -> str:
    text = str(value if value is not None else "-")
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return text
    try:
        parsed = json.loads(stripped)
    except Exception:
        return text
    if isinstance(parsed, dict):
        interesting_keys = [
            "position",
            "velocity",
            "torque",
            "t_mos",
            "t_rotor",
            "status",
            "status_code",
            "has_error",
            "raw_frame",
        ]
        pieces = []
        for key in interesting_keys:
            if key not in parsed:
                continue
            item = parsed[key]
            if key == "raw_frame" and isinstance(item, dict):
                item = item.get("data_hex") or item.get("data") or item
            pieces.append(f"{key}={item}")
        return "; ".join(pieces) if pieces else json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def _html_cell(value: Any, *, compact_json: bool = False) -> str:
    text = _compact_json_for_html(value) if compact_json else str(value if value is not None else "-")
    text = text.replace("; ", ";\n")
    return f"<td><div class='cell-text'>{escape(text)}</div></td>"


def _html_factory_acceptance_report(title: str, payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    gate = summary.get("release_gate") or {}
    warning_items = gate.get("warning_items") or []
    blocking_items = gate.get("blocking_items") or []
    decision = gate.get("release_decision") or ("PASS" if summary.get("release_ready") else "HOLD")
    summary_cards = [
        ("Arm Serial", summary.get("arm_serial") or payload.get("subject_id")),
        ("Arm Type", summary.get("arm_type") or "-"),
        ("BOM Profile", summary.get("bom_profile") or "-"),
        ("Release Decision", decision),
        ("Linked Jobs", summary.get("linked_job_count", 0)),
        ("Zero Records", summary.get("zero_record_count", 0)),
        ("Demo Records", summary.get("demo_record_count", 0)),
        ("Operator", summary.get("operator") or "-"),
    ]
    cards_html = "".join(
        f"<div class='summary-card'><div class='label'>{escape(str(label))}</div>"
        f"<div class='value {('status-' + _status_class(value)) if label == 'Release Decision' else ''}'>{escape(str(value if value is not None else '-'))}</div></div>"
        for label, value in summary_cards
    )
    standards_html = "".join(f"<li>{escape(str(item))}</li>" for item in summary.get("reference_standards") or [])
    warnings_html = "".join(f"<li>{escape(str(item))}</li>" for item in warning_items) or "<li>None</li>"
    blocking_html = "".join(f"<li>{escape(str(item))}</li>" for item in blocking_items) or "<li>None</li>"

    sections_html = []
    headers = payload.get("headers") or []
    for section in _report_sections_from_rows(payload.get("rows") or []):
        body = ""
        for row in section["rows"]:
            padded = list(row) + [""] * max(0, len(headers) - len(row))
            result = padded[len(headers) - 1] if headers else padded[-1]
            body += (
                f"<tr class='result-{_status_class(result)}'>"
                + "".join(
                    _html_cell(value, compact_json=(index == 3))
                    for index, value in enumerate(padded[: len(headers)])
                )
                + "</tr>"
            )
        sections_html.append(
            f"""
            <section class="report-section">
                <h2>{escape(section['title'])}</h2>
                <table class="results-table">
                    <thead><tr>{''.join(f'<th>{escape(str(header))}</th>' for header in headers)}</tr></thead>
                    <tbody>{body or f'<tr><td colspan="{len(headers)}">No records</td></tr>'}</tbody>
                </table>
            </section>
            """
        )

    manifest_html = _html_report_manifest(summary.get("attached_report_manifest", []))
    notes = summary.get("notes") or "-"
    return f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8">
        <title>{escape(title)}</title>
        <style>
            @page {{ size: A4 portrait; margin: 12mm; }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                color: #172033;
                font-family: Arial, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
                font-size: 10.5px;
                line-height: 1.42;
            }}
            .cover {{
                border-bottom: 3px solid #1d4ed8;
                padding-bottom: 12px;
                margin-bottom: 14px;
            }}
            h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }}
            h2 {{
                margin: 0 0 8px;
                color: #123c69;
                font-size: 15px;
                border-bottom: 1px solid #d8e0eb;
                padding-bottom: 4px;
            }}
            h3 {{ margin: 10px 0 5px; font-size: 12px; color: #243b53; }}
            .muted {{ color: #637083; }}
            .summary-grid {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                margin: 12px 0;
            }}
            .summary-card {{
                border: 1px solid #ccd6e2;
                border-radius: 4px;
                padding: 7px 8px;
                min-height: 45px;
                background: #f8fafc;
            }}
            .label {{ color: #64748b; font-size: 9px; text-transform: uppercase; }}
            .value {{ margin-top: 3px; font-size: 12px; font-weight: 700; overflow-wrap: anywhere; }}
            .status-pass {{ color: #166534; }}
            .status-warning {{ color: #92400e; }}
            .status-fail {{ color: #991b1b; }}
            .two-column {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 14px;
                margin: 10px 0 14px;
            }}
            .panel {{
                border: 1px solid #d8e0eb;
                border-radius: 4px;
                padding: 8px 10px;
                page-break-inside: avoid;
            }}
            ul {{ margin: 4px 0 0 16px; padding: 0; }}
            .report-section {{ margin: 14px 0 0; page-break-inside: avoid; }}
            table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
            th, td {{ border: 1px solid #cfd8e3; padding: 5px 6px; vertical-align: top; }}
            th {{ background: #eaf1f8; font-weight: 700; color: #1f3654; }}
            .results-table th:nth-child(1) {{ width: 17%; }}
            .results-table th:nth-child(2) {{ width: 12%; }}
            .results-table th:nth-child(3) {{ width: 20%; }}
            .results-table th:nth-child(4) {{ width: 27%; }}
            .results-table th:nth-child(5) {{ width: 16%; }}
            .results-table th:nth-child(6) {{ width: 8%; }}
            .cell-text {{ white-space: pre-wrap; overflow-wrap: anywhere; max-height: 96px; overflow: hidden; }}
            tr.result-pass td:last-child {{ color: #166534; font-weight: 700; }}
            tr.result-warning td:last-child {{ color: #92400e; font-weight: 700; }}
            tr.result-fail td:last-child {{ color: #991b1b; font-weight: 700; }}
            .manifest-section {{ margin-top: 16px; page-break-inside: avoid; }}
            .manifest-section h2 {{ margin-top: 0; }}
            .signature-grid {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 10px;
                margin-top: 18px;
            }}
            .signature-box {{ border-top: 1px solid #94a3b8; padding-top: 5px; color: #475569; }}
        </style>
    </head>
    <body>
        <section class="cover">
            <h1>{escape(title)}</h1>
            <div class="muted">Report ID: {escape(str(payload.get('report_id')))} · Generated: {escape(str(payload.get('generated_at')))}</div>
            <div class="summary-grid">{cards_html}</div>
            <div class="two-column">
                <div class="panel">
                    <h3>Release Gate</h3>
                    <div><strong>Blocking Items</strong></div>
                    <ul>{blocking_html}</ul>
                    <div style="margin-top: 6px;"><strong>Warnings</strong></div>
                    <ul>{warnings_html}</ul>
                </div>
                <div class="panel">
                    <h3>Reference Standards</h3>
                    <ul>{standards_html or '<li>-</li>'}</ul>
                    <h3>Notes</h3>
                    <div>{escape(str(notes))}</div>
                </div>
            </div>
        </section>
        {''.join(sections_html)}
        {manifest_html}
        <section class="report-section">
            <h2>Sign-Off</h2>
            <div class="signature-grid">
                <div class="signature-box">Prepared By / Date</div>
                <div class="signature-box">Reviewed By / Date</div>
                <div class="signature-box">Approved By / Date</div>
            </div>
        </section>
    </body>
    </html>
    """


def _write_pdf_from_html(html_path: Path, pdf_path: Path) -> bool:
    error_path = pdf_path.parent / "pdf_error.txt"
    chromium = (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
        or ("/snap/bin/chromium" if Path("/snap/bin/chromium").exists() else None)
    )
    if not chromium:
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text("Chromium/Chrome was not found. Formal factory PDFs require Chromium/Skia output.\n", encoding="utf-8")
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        chromium,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path.resolve()}",
        html_path.resolve().as_uri(),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    except Exception as exc:
        error_path.write_text(f"Chromium PDF generation failed: {exc}\n", encoding="utf-8")
        return False
    if completed.returncode != 0:
        error_path.write_text(
            "Chromium PDF generation failed.\n"
            f"command={' '.join(cmd)}\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}\n",
            encoding="utf-8",
        )
        return False
    for _ in range(20):
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            if error_path.exists():
                error_path.unlink()
            return True
        time.sleep(0.1)
    error_path.write_text("Chromium exited successfully, but the target PDF was not created.\n", encoding="utf-8")
    return False


def _report_section_row(section: str) -> tuple:
    return (section, "", "", "", "", "")


def _status_read_anomaly(status: Dict[str, Any]) -> bool:
    return bool(status) and not bool(status.get("has_error")) and not bool(status.get("is_healthy", True))


def _is_official_demo_command(command: List[str]) -> bool:
    return bool(command) and Path(str(command[0])).name == OFFICIAL_DEMO_COMMAND


def _ensure_command_option(command: List[str], *option_and_value: str) -> List[str]:
    option = option_and_value[0]
    if option in command:
        return command
    return [*command, *option_and_value]


def _command_arm_side(command: List[str]) -> Optional[str]:
    """The arm side the demo command itself declares, e.g. `--arm_side left_arm`."""
    for option in ("--arm_side", "--arm-side"):
        if option in command:
            index = command.index(option)
            if index + 1 < len(command):
                return str(command[index + 1])
    return None


def _official_demo_gripper_targets(gripper: Dict[str, Any], arm_side: Optional[str]) -> tuple:
    """(open, close) targets for one arm, taken from the product registry.

    1.0 declares one open target that applies to both arm sides and to Follower and
    Leader alike, matching the official limit table [-60 deg, 0 deg]. 2.0 keys it on
    the arm side instead (right 0 -> -90 deg, left 0 -> +90 deg) - a different scheme,
    not a different number - so the registry keeps the two as separate fields and this
    reads whichever one the product actually declares.
    """
    close_target = float(gripper.get("close_target_rad") or 0.0)
    open_target = gripper.get("open_target_rad")
    if open_target is not None:
        return float(open_target), close_target
    by_arm_side = gripper.get("open_target_rad_by_arm_side") or {}
    if arm_side and arm_side in by_arm_side:
        return float(by_arm_side[arm_side]), close_target
    raise ValueError(
        "this product keys the gripper open target on the arm side; "
        f"the demo command must state --arm_side (one of {sorted(by_arm_side)})"
    )


def _normalize_official_demo_command(
    command: List[str],
    arm_cn: Optional[str] = None,
    gripper: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if not _is_official_demo_command(command):
        return command
    if gripper is None:
        raise ValueError("gripper configuration is required to build the official demo command")
    normalized = list(command)
    open_target, close_target = _official_demo_gripper_targets(gripper, _command_arm_side(normalized))
    normalized = _ensure_command_option(normalized, "--enable-hold-ms", str(OFFICIAL_DEMO_DEFAULT_ENABLE_HOLD_MS))
    normalized = _ensure_command_option(normalized, "--phase-hold-s", str(OFFICIAL_DEMO_DEFAULT_PHASE_HOLD_S))
    normalized = _ensure_command_option(normalized, "--gripper-open-target", f"{open_target:.4f}")
    normalized = _ensure_command_option(normalized, "--gripper-close-target", f"{close_target:.1f}")
    return normalized


def _parse_official_demo_stdout(stdout: str) -> Dict[str, Any]:
    text = stdout or ""
    enabled = len(re.findall(r"ENABLE recv_id=.*'status': 'ENABLED'", text))
    disabled = len(re.findall(r"DISABLE recv_id=.*'status': 'DISABLED'", text))
    id16_special = len(re.findall(r"'status': 'STATE_FRAME_ID16_UNTAGGED'", text))
    keepalive_match = re.search(r"enable_keepalive_frames_sent=([0-9]+)", text)
    open_start = re.search(r"OPEN gripper: target=([-0-9.]+) start=([-0-9.]+)", text)
    close_start = re.search(r"CLOSE gripper: target=([-0-9.]+) start=([-0-9.]+)", text)
    final_grip = list(re.finditer(r"Gripper Motor \d+ recv=\d+ position=([-0-9.]+).*tmos=([0-9.]+) trotor=([0-9.]+)", text))
    close_final = float(final_grip[-1].group(1)) if final_grip else None
    open_observed = float(close_start.group(2)) if close_start else None
    travel = abs(close_final - open_observed) if close_final is not None and open_observed is not None else None
    aborts = re.findall(r"GRIPPER_ABORT: ([^\n]+)", text)
    blocking = []
    warnings = []
    expects_id16_special = "arm_side: left_arm" in text or "0x10" in text
    if aborts:
        # The demo stopped a gripper phase because the gripper was not following. Most
        # likely the open direction is wrong for this arm, or something blocks it.
        blocking.append("gripper_progress_aborted")
    if "COMM_LOST" in text:
        blocking.append("comm_lost_reported")
    if "Demo completed successfully; motors disabled." not in text:
        blocking.append("missing_successful_disable_message")
    if enabled < 7:
        blocking.append("enable_feedback_incomplete")
    if disabled < 7:
        blocking.append("disable_feedback_incomplete")
    if expects_id16_special and id16_special < 2:
        warnings.append("id16_special_frame_not_observed")
    if travel is None:
        warnings.append("gripper_travel_not_measured")
    elif travel < OFFICIAL_DEMO_MIN_GRIPPER_TRAVEL_RAD:
        blocking.append("gripper_travel_below_threshold")
    return {
        "enabled_count": enabled,
        "disabled_count": disabled,
        "id16_special_frame_count": id16_special,
        "keepalive_frames": int(keepalive_match.group(1)) if keepalive_match else None,
        "open_target": float(open_start.group(1)) if open_start else None,
        "open_start": float(open_start.group(2)) if open_start else None,
        "open_observed_at_close_start": open_observed,
        "close_final": close_final,
        "gripper_travel_rad": travel,
        "gripper_travel_threshold_rad": OFFICIAL_DEMO_MIN_GRIPPER_TRAVEL_RAD,
        "gripper_abort_messages": aborts,
        "blocking_items": blocking,
        "warning_items": warnings,
        "passed": not blocking,
    }


def _parse_official_enable_stdout(stdout: str, expected_count: int) -> Dict[str, Any]:
    text = stdout or ""
    enabled = len(re.findall(r"ENABLE recv_id=.*'status': 'ENABLED'", text))
    disabled = len(re.findall(r"DISABLE recv_id=.*'status': 'DISABLED'", text))
    id16_special = len(re.findall(r"'status': 'STATE_FRAME_ID16_UNTAGGED'", text))
    keepalive_match = re.search(r"keepalive_frames_sent=([0-9]+)", text)
    comm_lost = "COMM_LOST" in text
    expected_normal_count = expected_count - 1 if id16_special >= 2 else expected_count
    passed = "RESULT: PASS" in text and enabled >= expected_normal_count and disabled >= expected_normal_count and not comm_lost
    return {
        "enabled_count": enabled,
        "disabled_count": disabled,
        "id16_special_frame_count": id16_special,
        "keepalive_frames": int(keepalive_match.group(1)) if keepalive_match else None,
        "comm_lost_reported": comm_lost,
        "passed": passed,
    }


def _parse_official_zero_output(stdout: str, stderr: str = "") -> Dict[str, Any]:
    text = f"{stdout or ''}\n{stderr or ''}"
    zero_written = "wrote zero positon to arm" in text or "wrote zero position to arm" in text
    restore_completed = "initial physical pose restored" in text
    limit_failed = "LimitSearchFailed" in text or "did not reach a reliable limit before guard" in text
    refused_zero = "Refusing reverse motion and zero write" in text
    stops = re.findall(r"mechanical stop(?: near guard)? \((?:Joint )?([^)]+)\):[^\n]*?([-0-9.]+) rad / ([-0-9.]+)°", text)
    blocking = []
    warnings = []
    if limit_failed:
        blocking.append("limit_search_failed")
    if refused_zero:
        blocking.append("zero_write_refused")
    if not zero_written:
        blocking.append("zero_write_not_confirmed")
    if "--restore-initial-pose" in text and not restore_completed:
        warnings.append("restore_not_confirmed")
    return {
        "zero_written": zero_written,
        "restore_completed": restore_completed,
        "limit_search_failed": limit_failed,
        "zero_write_refused": refused_zero,
        "mechanical_stops": [
            {"joint": joint, "position_rad": float(rad), "position_deg": float(deg)}
            for joint, rad, deg in stops
        ],
        "blocking_items": blocking,
        "warning_items": warnings,
        "passed": not blocking,
    }


def _motor_result_label(present: bool, issues: Iterable[str]) -> str:
    issue_set = set(issues)
    if not present:
        return "FAIL"
    if not issue_set:
        return "PASS"
    if issue_set == {"status_read_anomaly"}:
        return "WARNING"
    return "FAIL"


def _pdf_escape(value: Any) -> str:
    text = str(value if value is not None else "-")
    return (
        text.encode("latin-1", "replace")
        .decode("latin-1")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _write_simple_pdf(path: Path, title: str, payload: Dict[str, Any]):
    """Write a dependency-free PDF fallback for factory artifact traceability."""
    lines = [
        title,
        f"Report ID: {payload.get('report_id', '-')}",
        f"Generated: {payload.get('generated_at', '-')}",
        f"Subject: {payload.get('subject_type', '-')}/{payload.get('subject_id', '-')}",
        "",
        "Summary",
    ]
    for key, value in (payload.get("summary") or {}).items():
        if key == "attached_report_manifest":
            continue
        lines.append(f"{key}: {value}")
    manifest = (payload.get("summary") or {}).get("attached_report_manifest") or []
    if manifest:
        lines.extend(["", "Attached Report Manifest"])
        for item in manifest:
            lines.append(
                f"{item.get('owner', '-')} | {item.get('title', '-')} | {item.get('report_type', '-')} | "
                f"{item.get('pdf_path') or item.get('html_path') or item.get('json_path') or '-'}"
            )
    lines.extend(["", "Results"])
    headers = " | ".join(str(item) for item in payload.get("headers", []))
    if headers:
        lines.append(headers)
    for row in payload.get("rows", []):
        if row and str(row[0]).strip() and all(not str(value).strip() for value in row[1:]):
            lines.extend(["", str(row[0])])
        else:
            lines.append(" | ".join(str(item if item is not None else "-") for item in row))

    page_width = 842
    page_height = 595
    margin_left = 42
    lines_per_page = 46
    pages = [lines[index : index + lines_per_page] for index in range(0, len(lines), lines_per_page)] or [[]]
    page_contents = []
    for page_lines in pages:
        cursor_y = page_height - 42
        content_lines = ["BT", "/F1 8 Tf", "10 TL"]
        for line in page_lines:
            clipped = _pdf_escape(line)[:170]
            content_lines.append(f"1 0 0 1 {margin_left} {cursor_y} Tm ({clipped}) Tj")
            cursor_y -= 10
        content_lines.append("ET")
        page_contents.append("\n".join(content_lines).encode("latin-1", "replace"))

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_object_ids = []
    content_object_ids = []
    next_object_id = 4
    for content in page_contents:
        page_id = next_object_id
        content_id = next_object_id + 1
        next_object_id += 2
        page_object_ids.append(page_id)
        content_object_ids.append(content_id)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{item} 0 R' for item in page_object_ids)}] /Count {len(page_object_ids)} >>".encode("ascii")
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    _atomic_bytes(path, bytes(pdf))


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _arm_record_dir(arm_cn: str) -> Path:
    return FACTORY_ARM_RECORDS_DIR / _safe_name(arm_cn)


def _motor_type_from_name(name: str) -> DM_Motor_Type:
    aliases = {
        "DM-J4310-2EC": "DM4310",
        "DM-J4340-2EC": "DM4340",
        "DM-J4340P-2EC": "DM4340",
        "DM-J8009P-2EC": "DM8009",
        "DM-J8009-2EC": "DM8009",
    }
    name = aliases.get(name, name)
    return DM_Motor_Type[name]


def _motor_family(motor_type: DM_Motor_Type) -> str:
    return motor_type.name.replace("_48V", "")


def _infer_motor_model(params: Dict[str, Any], expected_motor_type: Optional[str]) -> Dict[str, Any]:
    """Infer the Damiao motor family from factory limit registers; motors expose no model register."""
    evidence = {key: params.get(key) for key in ("PMAX", "VMAX", "TMAX", "Gr")}
    try:
        expected_family = _motor_family(_motor_type_from_name(expected_motor_type)) if expected_motor_type else None
    except KeyError:
        expected_family = None
    limits = [evidence["PMAX"], evidence["VMAX"], evidence["TMAX"]]
    families: List[str] = []
    if all(value is not None for value in limits):
        for motor_type in DM_Motor_Type:
            if all(abs(float(actual) - float(reference)) < 1e-3 for actual, reference in zip(limits, LIMIT_PARAM[int(motor_type)])):
                family = _motor_family(motor_type)
                if family not in families:
                    families.append(family)
    if not families:
        verdict = "unknown"
    elif expected_family and expected_family in families:
        verdict = "match"
    elif expected_family:
        verdict = "mismatch"
    else:
        verdict = "unknown"
    return {
        "method": "limit_registers",
        "families": families,
        "expected_motor_type": expected_motor_type,
        "expected_family": expected_family,
        "verdict": verdict,
        "evidence": evidence,
    }


def _official_motor_type_map() -> Dict[str, str]:
    return {
        "J1": "DM-J8009P-2EC",
        "J2": "DM-J8009P-2EC",
        "J3": "DM-J4340P-2EC",
        "J4": "DM-J4340-2EC",
        "J5": "DM-J4310-2EC",
        "J6": "DM-J4310-2EC",
        "J7": "DM-J4310-2EC",
        "J8": "DM-J4310-2EC",
    }


def _control_from_value(value: Any) -> Control_Type:
    if isinstance(value, Control_Type):
        return value
    if isinstance(value, int):
        return Control_Type(value)
    return Control_Type[str(value)]


def _normalize_can_br(value: Any) -> Optional[int]:
    if value is None:
        return None
    raw = int(value)
    return DM_CAN_BR_CODE_TO_BITRATE.get(raw, raw)


def _encode_can_br_for_motor(value: Any) -> int:
    raw = int(value)
    return DM_CAN_BR_BITRATE_TO_CODE.get(raw, raw)


def _can_br_matches(actual: Any, expected: Any) -> bool:
    normalized_actual = _normalize_can_br(actual)
    normalized_expected = _normalize_can_br(expected)
    return normalized_actual is not None and normalized_actual == normalized_expected


def _control_name(value: Any) -> str:
    try:
        return _control_from_value(value).name
    except Exception:
        return str(value)


def _motor_snapshot_for_report(motor: Motor, params: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = motor.snapshot()
    snapshot["params"] = params
    return snapshot


def _factory_date_code(date_code: Optional[str] = None) -> str:
    if date_code is None:
        return datetime.now().strftime("%y%m%d")
    value = str(date_code).strip()
    if not re.fullmatch(r"\d{6}", value):
        raise ValueError("date_code must be YYMMDD, e.g. 260427")
    return value


def _factory_role_code(role: str) -> str:
    value = str(role or "F").strip().upper()
    aliases = {"FOLLOWER": "F", "LEADER": "L"}
    value = aliases.get(value, value)
    if value not in {"F", "L"}:
        raise ValueError("role must be F or L")
    return value


def _resolve_openarm_command(command: str) -> Optional[str]:
    resolved = shutil.which(command)
    if resolved:
        return resolved
    local_command = LOCAL_OPENARM_COMMANDS.get(command)
    if local_command and local_command.exists() and os.access(local_command, os.X_OK):
        return str(local_command)
    return None


@dataclass
class TransportCapabilities:
    read_params: bool
    write_params: bool
    save_flash: bool
    zero: bool
    test: bool
    communication_check: bool


class WizardConnectError(RuntimeError):
    """The workstation could not open a device session on the requested CAN port."""


@dataclass
class DeviceSession:
    session_id: str
    transport: str
    driver: Any
    connection: Dict[str, Any]
    capabilities: TransportCapabilities
    connection_state: str = "connected"
    last_scan: Dict[str, Any] = field(default_factory=dict)
    last_inventory: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    device_session_id: str
    artifact_dir: str
    profile_id: Optional[str] = None
    target_joint: Optional[str] = None
    expert_mode: bool = False
    status: str = "draft"
    current_step: str = "draft"
    candidate: Dict[str, Any] = field(default_factory=dict)
    motors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    target_config: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=_now_iso)
    finished_at: Optional[str] = None
    failure_reason: Optional[str] = None
    product_line: Optional[str] = None


class ProfileManager:
    def __init__(self):
        self._profiles = self._load_profiles()

    def _default_openarm_v1(self) -> Dict[str, Any]:
        joints = []
        motor_map = _official_motor_type_map()
        for index, joint_name in enumerate(motor_map, start=1):
            joints.append(
                {
                    "joint_name": joint_name,
                    "motor_type": motor_map[joint_name],
                    "target_esc_id": index,
                    "target_mst_id": 0x10 + index,
                    "target_ctrl_mode": "MIT",
                    # commissioning_policy.whole_arm_timeout_policy: J1-J8 = 5000 on both arms.
                    "target_timeout": WHOLE_ARM_TARGET_TIMEOUT,
                    "target_can_br": 1000000,
                    "requires_zero": True,
                    "test_profile": "safe_mit_ping",
                    "expected_bus": "can0",
                }
            )
        return {
            "profile_id": "openarm_v1",
            "name": "OpenARM 通用单臂模板",
            "description": "OpenARM 官方单臂映射，适合单臂建站与逐关节检查。",
            "mode": "communication_primary",
            "profile_scope": "single_arm_generic",
            "arm_side": "generic",
            "official_reference": "OpenARM Setup Step 1~4",
            "community_reference": "enactic/openarm_can",
            "recommended_can_mode": "can20_first",
            "supported_scan_ids": [*range(0x01, 0x09)],
            "joints": joints,
        }

    def _derive_arm_profile(
        self,
        base_profile: Dict[str, Any],
        *,
        profile_id: str,
        name: str,
        description: str,
        arm_side: str,
        joint_prefix: str,
        expected_bus: str,
        esc_id_offset: int = 0,
        mst_id_offset: int = 0,
        target_timeout_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        derived_joints = []
        for joint in base_profile["joints"]:
            joint_copy = dict(joint)
            base_joint_name = str(joint_copy["joint_name"])
            joint_copy["joint_name"] = f"{joint_prefix}-{base_joint_name}"
            joint_copy["target_esc_id"] = int(joint_copy["target_esc_id"]) + int(esc_id_offset)
            joint_copy["target_mst_id"] = int(joint_copy["target_mst_id"]) + int(mst_id_offset)
            if target_timeout_override is not None:
                joint_copy["target_timeout"] = int(target_timeout_override)
            joint_copy["expected_bus"] = expected_bus
            joint_copy["arm_side"] = arm_side
            derived_joints.append(joint_copy)
        return {
            **{key: value for key, value in base_profile.items() if key != "joints"},
            "profile_id": profile_id,
            "name": name,
            "description": description,
            "profile_scope": "single_arm_official",
            "arm_side": arm_side,
            "official_reference": "OpenARM Setup Step 1~4",
            "community_reference": "enactic/openarm_can",
            "recommended_can_mode": "can20_first",
            "supported_scan_ids": [int(joint["target_esc_id"]) for joint in derived_joints],
            "expected_bus": expected_bus,
            "joints": derived_joints,
        }

    def _load_profiles(self) -> Dict[str, Dict[str, Any]]:
        profiles = {"openarm_v1": self._default_openarm_v1()}
        builtin_file = BUILTIN_PROFILE_DIR / "openarm_v1.yaml"
        if builtin_file.exists():
            profiles["openarm_v1"] = yaml.safe_load(builtin_file.read_text(encoding="utf-8"))
        override_file = OVERRIDE_PROFILE_DIR / "openarm_v1.yaml"
        if override_file.exists():
            profiles["openarm_v1"] = yaml.safe_load(override_file.read_text(encoding="utf-8"))
        profiles["openarm_right_arm_v1"] = self._derive_arm_profile(
            profiles["openarm_v1"],
            profile_id="openarm_right_arm_v1",
            name="OpenARM 右臂模板",
            description="按 OpenARM 官方单臂映射组织的右臂模板，使用 R-J1 ~ R-J8。",
            arm_side="right_arm",
            joint_prefix="R",
            expected_bus="can0",
            target_timeout_override=5000,
        )
        profiles["openarm_left_arm_v1"] = self._derive_arm_profile(
            profiles["openarm_v1"],
            profile_id="openarm_left_arm_v1",
            name="OpenARM 左臂模板",
            description="按出厂规划组织的左臂模板，使用 L-J1 ~ L-J8 与 0x09 ~ 0x10 ID。",
            arm_side="left_arm",
            joint_prefix="L",
            expected_bus="can0",
            esc_id_offset=8,
            mst_id_offset=8,
            target_timeout_override=5000,
        )
        return profiles

    def list_profiles(self) -> List[Dict[str, Any]]:
        order = ["openarm_v1", "openarm_right_arm_v1", "openarm_left_arm_v1"]
        ordered_ids = [profile_id for profile_id in order if profile_id in self._profiles]
        ordered_ids.extend(profile_id for profile_id in self._profiles if profile_id not in ordered_ids)
        return [self.get_profile(profile_id) for profile_id in ordered_ids]

    def get_profile(self, profile_id: str) -> Dict[str, Any]:
        if profile_id not in self._profiles:
            raise KeyError(f"profile {profile_id} not found")
        return self._profiles[profile_id]

    def get_joint(self, profile_id: str, joint_name: str) -> Dict[str, Any]:
        profile = self.get_profile(profile_id)
        for joint in profile["joints"]:
            if joint["joint_name"] == joint_name:
                return joint
        raise KeyError(f"joint {joint_name} not found in profile {profile_id}")


class ProductRegistry:
    """The product versions the workstation can build, loaded from profiles/products.

    One place answers "what is a 1.0 arm" and "what is a 2.0 arm": IDs, motor types,
    CAN modes, gripper direction and travel, zero method, cameras, firmware baseline.
    Anything not yet confirmed on hardware carries `hardware_verified: false` and a
    `locked_reason`; callers must consult `is_locked()` before acting on it.

    This release only loads, validates and exposes the registry. The scan, acceptance
    and report paths still read their own tables, so 1.0 judgement is unchanged.
    """

    JOINT_NAMES = [f"J{index}" for index in range(1, 9)]

    def __init__(self):
        self._products = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        products: Dict[str, Dict[str, Any]] = {}
        if not PRODUCT_REGISTRY_DIR.exists():
            return products
        for path in sorted(PRODUCT_REGISTRY_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"product registry {path.name} is not a mapping")
            product_version = data.get("product_version")
            if not product_version:
                raise ValueError(f"product registry {path.name} has no product_version")
            if product_version in products:
                raise ValueError(f"duplicate product_version {product_version} in {path.name}")
            self._validate(path.name, data)
            products[str(product_version)] = data
        return products

    def _validate(self, filename: str, data: Dict[str, Any]):
        """Fail loudly at startup rather than mid-run on the factory floor."""
        for key in ("label", "profile_revision", "arms", "motors", "can", "parameters"):
            if key not in data:
                raise ValueError(f"product registry {filename} is missing '{key}'")

        motors = data["motors"]
        if sorted(motors) != sorted(self.JOINT_NAMES):
            raise ValueError(f"product registry {filename} must list exactly J1-J8, got {sorted(motors)}")

        for arm_side, arm in data["arms"].items():
            for key in ("profile_id", "joint_prefix", "expected_bus", "esc_ids", "mst_ids"):
                if key not in arm:
                    raise ValueError(f"product registry {filename} arm {arm_side} is missing '{key}'")
            for key in ("esc_ids", "mst_ids"):
                ids = arm[key]
                if len(ids) != 8:
                    raise ValueError(f"product registry {filename} arm {arm_side} {key} must have 8 entries")
                if len(set(ids)) != 8:
                    raise ValueError(f"product registry {filename} arm {arm_side} {key} has duplicates")
                if not all(0x01 <= int(value) <= 0x20 for value in ids):
                    raise ValueError(f"product registry {filename} arm {arm_side} {key} outside 0x01-0x20")

        sides = list(data["arms"])
        if len(sides) == 2:
            left, right = (data["arms"][side] for side in sides)
            overlap = set(left["esc_ids"]) & set(right["esc_ids"])
            if overlap:
                raise ValueError(f"product registry {filename} arms share ESC IDs {sorted(overlap)}")

        for stage in ("commissioning", "operation"):
            if stage not in data["can"]:
                raise ValueError(f"product registry {filename} can.{stage} is missing")
            mode = data["can"][stage].get("mode")
            if mode not in {"can20", "canfd"}:
                raise ValueError(f"product registry {filename} can.{stage}.mode must be can20 or canfd")
            if mode == "canfd" and not data["can"][stage].get("dbitrate"):
                raise ValueError(f"product registry {filename} can.{stage} is canfd but has no dbitrate")

        for section in self._lockable_sections(data):
            if section.get("hardware_verified") is False and not section.get("locked_reason"):
                raise ValueError(f"product registry {filename} has an unverified section with no locked_reason")

    def _lockable_sections(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        sections = [data["can"]["commissioning"], data["can"]["operation"]]
        for key in ("gripper", "zero"):
            if isinstance(data.get(key), dict):
                sections.append(data[key])
        sections.extend(item for item in (data.get("cameras") or []) if isinstance(item, dict))
        return sections

    def cross_check(self, profile_manager: "ProfileManager") -> List[str]:
        """Report where a product registry disagrees with the profile it points at.

        The registry is new and the profiles are what production actually ran on. If
        the two ever disagree about an ID, a motor type or the TIMEOUT target, the
        registry is wrong - it must describe the system, not redefine it.
        """
        problems: List[str] = []
        for product_version, product in sorted(self._products.items()):
            for arm_side, arm in product["arms"].items():
                where = f"{product_version}/{arm_side}"
                try:
                    profile = profile_manager.get_profile(arm["profile_id"])
                except KeyError:
                    problems.append(f"{where}: profile {arm['profile_id']} not found")
                    continue
                joints = profile["joints"]
                if len(joints) != 8:
                    problems.append(f"{where}: profile has {len(joints)} joints, expected 8")
                    continue
                for index, joint in enumerate(joints):
                    joint_name = self.JOINT_NAMES[index]
                    expected_esc = int(arm["esc_ids"][index])
                    expected_mst = int(arm["mst_ids"][index])
                    if int(joint["target_esc_id"]) != expected_esc:
                        problems.append(
                            f"{where}/{joint_name}: registry ESC 0x{expected_esc:02X} != profile 0x{int(joint['target_esc_id']):02X}"
                        )
                    if int(joint["target_mst_id"]) != expected_mst:
                        problems.append(
                            f"{where}/{joint_name}: registry MST 0x{expected_mst:02X} != profile 0x{int(joint['target_mst_id']):02X}"
                        )
                    if str(joint["motor_type"]) != str(product["motors"][joint_name]):
                        problems.append(
                            f"{where}/{joint_name}: registry motor {product['motors'][joint_name]} != profile {joint['motor_type']}"
                        )
                    if int(joint["target_timeout"]) != int(product["parameters"]["timeout"]):
                        problems.append(
                            f"{where}/{joint_name}: registry TIMEOUT {product['parameters']['timeout']} != profile {joint['target_timeout']}"
                        )
                    if str(joint["expected_bus"]) != str(arm["expected_bus"]):
                        problems.append(
                            f"{where}/{joint_name}: registry bus {arm['expected_bus']} != profile {joint['expected_bus']}"
                        )
        return problems

    def list_products(self) -> List[Dict[str, Any]]:
        return [self.get(product_version) for product_version in sorted(self._products)]

    def get(self, product_version: str) -> Dict[str, Any]:
        if product_version not in self._products:
            raise KeyError(f"product_version {product_version} not found")
        return self._products[product_version]

    def known_versions(self) -> List[str]:
        return sorted(self._products)

    def is_locked(self, product_version: str, section: str) -> bool:
        """True when this part of the product has not been confirmed on hardware."""
        product = self.get(product_version)
        node = product["can"].get(section) if section in ("commissioning", "operation") else product.get(section)
        if not isinstance(node, dict):
            return False
        return node.get("hardware_verified") is False

    def lock_reasons(self, product_version: str) -> Dict[str, str]:
        product = self.get(product_version)
        reasons: Dict[str, str] = {}
        for name, node in (
            ("can.commissioning", product["can"]["commissioning"]),
            ("can.operation", product["can"]["operation"]),
            ("gripper", product.get("gripper")),
            ("zero", product.get("zero")),
        ):
            if isinstance(node, dict) and node.get("hardware_verified") is False:
                reasons[name] = str(node.get("locked_reason") or "")
        for camera in product.get("cameras") or []:
            if isinstance(camera, dict) and camera.get("hardware_verified") is False:
                reasons[f"camera.{camera.get('id')}"] = str(camera.get("locked_reason") or "")
        return reasons


def _canonical_job_type(job_type: str) -> str:
    return LEGACY_JOB_TYPE_ALIASES.get(job_type, job_type)


def _public_job_type(job_type: str) -> str:
    return PUBLIC_JOB_TYPE_ALIASES.get(job_type, job_type)


class WorkstationService:
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.profile_manager = ProfileManager()
        self.product_registry = ProductRegistry()
        # The registry must describe the profiles, never contradict them. Catching a
        # disagreement here beats discovering it against a real arm.
        registry_problems = self.product_registry.cross_check(self.profile_manager)
        if registry_problems:
            raise ValueError("product registry disagrees with profiles: " + "; ".join(registry_problems))
        self.sessions: Dict[str, DeviceSession] = {}
        self.jobs: Dict[str, JobRecord] = {}
        self._lock = threading.RLock()

    def _emit(self, event: str, payload: Dict[str, Any]):
        if self.socketio is not None:
            self.socketio.emit(event, payload)

    def config(self) -> Dict[str, Any]:
        return {
            "workstation_version": WORKSTATION_VERSION,
            "profiles": self.profile_manager.list_profiles(),
            "product_versions": [
                {
                    "product_version": product["product_version"],
                    "label": product["label"],
                    "profile_revision": product["profile_revision"],
                    "hardware_verified": bool(product.get("hardware_verified")),
                    "operation_can_mode": product["can"]["operation"]["mode"],
                    "locked_sections": self.product_registry.lock_reasons(product["product_version"]),
                }
                for product in self.product_registry.list_products()
            ],
            "default_product_version": DEFAULT_PRODUCT_VERSION,
            "transports": [
                {
                    "id": "serial_bridge",
                    "label": "Serial Bridge",
                    "connection_fields": ["serial_port", "baudrate"],
                },
                {
                    "id": "socketcan",
                    "label": "SocketCAN (CAN2.0)",
                    "connection_fields": ["channel", "bitrate"],
                },
            ],
            "job_types": [
                {"id": "single_commissioning", "label": "单电机建站"},
                {"id": "single_param_config", "label": "单电机参数配置"},
                {"id": "arm_verification", "label": "机械臂通信扫描"},
                {"id": "arm_acceptance", "label": "机械臂验收"},
            ],
            "tabs": ["连接", "电机工站", "机械臂工站", "报告"],
            "temp_limits": TEMP_LIMITS,
            "feature_flags": {
                "system_can": True,
                "socketcan_write_params": True,
                "factory_traceability": True,
            },
            "test_profiles": [
                {"id": "comm_ping", "label": "通信 ping"},
                {"id": "micro_mit_ping", "label": "safe_mit_ping"},
            ],
            "factory_serial_rules": {
                "arm_cn": "OA{F/L}{YYMMDD}{NN}",
                "motor_sn": "DM-{model}-{F/L}{can_id_2hex}{YYMMDD}{NN}",
                "examples": {
                    "arm_cn": "OAF26042701",
                    "motor_sn": "DM-J8009P-2EC-F0126042701",
                },
            },
            "commissioning_policy": {
                "docs": "docs/DAMIAO_CALIBRATION_POLICY.md",
                "single_motor_timeout_write_default": False,
                "single_motor_encoder_calibration": "vendor_upper_software_or_service_fixture_only_when_required",
                "single_motor_zero_save_default": False,
                "arm_zero_save_stage": "assembled_arm_official_dynamic_zero_calibration",
                "arm_timeout_standardization_stage": "whole_arm_factory_acceptance_before_dynamic_zero_and_demo",
                "arm_timeout_standardization_mode": "profile_per_joint",
                # Derived from the product registry rather than restated here: the
                # registry already has to agree with the profiles (cross_check), so
                # reading it is the only way this table cannot drift from them.
                "whole_arm_timeout_policy": self._whole_arm_timeout_policy(),
                "motor_traceability_identity": "arm_cn_plus_joint_label",
                "zero_controller_sn_hw_behavior": "accepted_unassigned_optional_metadata",
            },
            "report_data_policy": {
                "docs": "docs/WORKSTATION_CHANGELOG.md#065-report-integrity---2026-08-04",
                "strict_arm_serial_match": True,
                "strict_arm_side_profile_match": True,
                "allow_global_latest_job_fallback": False,
                "fixed_template_allowed": True,
                "fixed_measured_values_allowed": False,
                "missing_required_data_behavior": "report_warning_with_recommended_actions",
                "obsolete_test_data_behavior": "remove_from_active_report_standard_instead_of_emitting_empty_fields",
                "id_display_format": "0xNN",
                "current_timeout_policy": "right arm J1-J8 TIMEOUT=5000; left arm J1-J8 TIMEOUT=5000",
            },
            "vendor_tools": {
                "dmtool_appimage": str(DMTOOL_APPIMAGE_PATH),
                "maintenance_record_stage": "manual_record_only",
                "automatic_encoder_calibration": False,
            },
        }

    CAN_MODE_LABELS = {"can20": "CAN 2.0", "canfd": "CAN FD"}

    def _can_mode_label(self, product_version: Optional[str], stage: str) -> str:
        """Human-readable bus mode for one product stage, e.g. "CAN 2.0".

        Falls back to the default product for records that predate the registry, which
        is what every such record on disk actually used.
        """
        try:
            product = self.product_registry.get(str(product_version or DEFAULT_PRODUCT_VERSION))
        except KeyError:
            product = self.product_registry.get(DEFAULT_PRODUCT_VERSION)
        return self.CAN_MODE_LABELS.get(str(product["can"][stage]["mode"]), str(product["can"][stage]["mode"]))

    def _arm_product_version(self, arm_cn: Optional[str]) -> str:
        """The product an arm is recorded as, defaulting for pre-registry records."""
        try:
            _path, arm = self._load_arm_record(str(arm_cn))
        except (KeyError, ValueError, TypeError):
            return DEFAULT_PRODUCT_VERSION
        version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
        return version if version in self.product_registry.known_versions() else DEFAULT_PRODUCT_VERSION

    def _whole_arm_timeout_policy(self) -> Dict[str, Dict[str, int]]:
        """The operational TIMEOUT each arm side targets, per product version.

        Both product versions currently target the same value on every joint, so the
        shape stays `{arm_side: {"J1-J8": value}}` as before. A version that ever
        targets something different will show up here without any other code changing.
        """
        policy: Dict[str, Dict[str, int]] = {}
        for product in self.product_registry.list_products():
            timeout = int(product["parameters"]["timeout"])
            for arm_side in product["arms"]:
                policy.setdefault(arm_side, {})[f"J1-J8@{product['product_version']}"] = timeout
        # Collapse to the historical shape while every product agrees on one value.
        collapsed: Dict[str, Dict[str, int]] = {}
        for arm_side, entries in policy.items():
            values = set(entries.values())
            collapsed[arm_side] = {"J1-J8": values.pop()} if len(values) == 1 else entries
        return collapsed

    def vendor_tool_status(self) -> Dict[str, Any]:
        path = DMTOOL_APPIMAGE_PATH
        return {
            "dmtool": {
                "path": str(path),
                "exists": path.exists(),
                "executable": path.exists() and os.access(path, os.X_OK),
                "integration_mode": "manual_launch_and_record",
                "automatic_calibration_supported": False,
            }
        }

    def launch_vendor_dmtool(self) -> Dict[str, Any]:
        with self._lock:
            path = DMTOOL_APPIMAGE_PATH
            if not path.exists():
                raise FileNotFoundError(f"DMTool AppImage not found: {path}")
            if not os.access(path, os.X_OK):
                raise PermissionError(f"DMTool AppImage is not executable: {path}")
            VENDOR_MAINTENANCE_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            log_path = VENDOR_MAINTENANCE_LOGS_DIR / f"dmtool_launch_{stamp}.log"
            log_file = log_path.open("ab")
            env = os.environ.copy()
            env.setdefault("QT_QPA_PLATFORM", "xcb")
            process = subprocess.Popen([str(path)], stdout=log_file, stderr=subprocess.STDOUT, cwd=str(ROOT_DIR), env=env)
            log_file.close()
            return {
                "dmtool": {
                    "path": str(path),
                    "pid": process.pid,
                    "log_path": str(log_path),
                    "launched_at": _now_iso(),
                    "mode": "manual_vendor_tool",
                }
            }

    def list_vendor_maintenance_records(self, limit: int = 20) -> Dict[str, Any]:
        with self._lock:
            VENDOR_MAINTENANCE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
            records = sorted(
                [_load_json(path) for path in VENDOR_MAINTENANCE_RECORDS_DIR.glob("*.json")],
                key=lambda item: item.get("recorded_at") or "",
                reverse=True,
            )
            return {"records": records[: int(limit)]}

    def record_vendor_maintenance(
        self,
        target_label: str,
        maintenance_stage: str,
        motor_encoder_calibration: str,
        output_encoder_calibration: str,
        zero_save: str,
        operator: Optional[str] = None,
        notes: Optional[str] = None,
        linked_job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        allowed_states = {"not_performed", "performed", "not_required", "failed", "unknown"}
        for field_name, value in {
            "motor_encoder_calibration": motor_encoder_calibration,
            "output_encoder_calibration": output_encoder_calibration,
            "zero_save": zero_save,
        }.items():
            if value not in allowed_states:
                raise ValueError(f"{field_name} must be one of {sorted(allowed_states)}")
        if not str(target_label or "").strip():
            raise ValueError("target_label is required")
        if not str(maintenance_stage or "").strip():
            raise ValueError("maintenance_stage is required")

        with self._lock:
            VENDOR_MAINTENANCE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
            linked_job = None
            if linked_job_id:
                linked_job = self._job_reference(self._job(linked_job_id))
            entry = {
                "record_id": uuid.uuid4().hex[:12],
                "record_type": "vendor_maintenance",
                "target_label": str(target_label).strip(),
                "maintenance_stage": str(maintenance_stage).strip(),
                "motor_encoder_calibration": motor_encoder_calibration,
                "output_encoder_calibration": output_encoder_calibration,
                "zero_save": zero_save,
                "operator": operator,
                "notes": notes,
                "linked_job": linked_job,
                "vendor_tool": {
                    "name": "Damiao DMTool",
                    "path": str(DMTOOL_APPIMAGE_PATH),
                    "integration_mode": "manual_record_only",
                },
                "recorded_at": _now_iso(),
            }
            path = VENDOR_MAINTENANCE_RECORDS_DIR / f"{entry['recorded_at'].replace(':', '')}_{entry['record_id']}.json"
            entry["record_path"] = str(path)
            _atomic_json(path, entry)
            return {"entry": entry, **self.list_vendor_maintenance_records()}

    def interface_status(self) -> Dict[str, Any]:
        return self.system_can_interfaces()

    def system_can_interfaces(self) -> Dict[str, Any]:
        interfaces = self._list_socketcan_interfaces()
        recommended = next((item["name"] for item in interfaces if item["is_gs_usb"]), None)
        payload = {
            "interfaces": interfaces,
            "recommended_channel": recommended,
        }
        return payload

    def configure_can_interface(
        self,
        name: str,
        mode: str,
        bitrate: int,
        dbitrate: Optional[int] = None,
        fd_enabled: bool = False,
        tool: str = "ip_link",
    ) -> Dict[str, Any]:
        with self._lock:
            self._require_interface(name)
            mode = str(mode)
            bitrate = int(bitrate)
            if bitrate <= 0:
                raise ValueError("bitrate must be positive")
            if mode not in {"can20", "canfd"}:
                raise ValueError("mode must be can20 or canfd")
            if mode == "canfd":
                if dbitrate is None:
                    raise ValueError("dbitrate is required for canfd")
                dbitrate = int(dbitrate)
                if dbitrate <= 0:
                    raise ValueError("dbitrate must be positive")
                fd_enabled = True
            else:
                dbitrate = None
                fd_enabled = False

            # Both tools take the link down; a socket opened on the old link would
            # survive as a deaf handle, so close ours first.
            self._invalidate_socketcan_sessions(name)

            if tool == "openarm_helper":
                helper = shutil.which("openarm-can-configure-socketcan")
                if helper is None:
                    raise RuntimeError("openarm-can-configure-socketcan not found")
                cmd = [helper, name]
                if mode == "canfd":
                    cmd.extend(["-fd", "-b", str(bitrate), "-d", str(dbitrate)])
                elif bitrate != 1000000:
                    cmd.extend(["-b", str(bitrate)])
                self._run_system_command(cmd)
            elif tool == "ip_link":
                self._run_system_command(["ip", "link", "set", name, "down"])
                self._run_system_command(self._can_configure_command(name, mode, bitrate, dbitrate))
            else:
                raise ValueError("unsupported tool")

            payload = self.system_can_interfaces()
            self._emit("interface_status", payload)
            return {
                "configured": True,
                "interface": self._interface_snapshot(name),
                "interfaces": payload["interfaces"],
                "recommended_channel": payload["recommended_channel"],
            }

    def _can_configure_command(
        self, name: str, mode: str, bitrate: int, dbitrate: Optional[int]
    ) -> List[str]:
        """The `ip link` arguments the official CLI applies, for the same interface.

        Ported from `openarm-can-cli can_configure`
        (external/openarm_can_1.4.0/setup/cli/commands/can_configure_commands.cpp), so a
        port this workstation prepared and one the customer prepares with the official
        tool carry the same timing. The sample point and DSJW are not cosmetic: at
        5 Mbps data rate, a controller sampling at a different point can fail to agree
        with the motors at all.

        `restart-ms 0` is also the official default, and deliberate: leaving the
        controller stopped after a bus-off surfaces the fault instead of hiding it
        behind a silent recovery.
        """
        command = [
            "ip", "link", "set", name, "type", "can",
            "bitrate", str(int(bitrate)),
            "sample-point", OFFICIAL_CAN_SAMPLE_POINT,
            "restart-ms", str(OFFICIAL_CAN_RESTART_MS),
        ]
        if mode == "canfd":
            command.extend([
                "dbitrate", str(int(dbitrate or 0)),
                "fd", "on",
                "dsample-point", OFFICIAL_CAN_DSAMPLE_POINT,
                "dsjw", OFFICIAL_CAN_DSJW,
            ])
        return command

    def can_interface_up(self, name: str) -> Dict[str, Any]:
        with self._lock:
            self._require_interface(name)
            self._run_system_command(["ip", "link", "set", name, "up"])
            payload = self.system_can_interfaces()
            self._emit("interface_status", payload)
            return {"ok": True, "interface": self._interface_snapshot(name)}

    def can_interface_down(self, name: str) -> Dict[str, Any]:
        with self._lock:
            self._require_interface(name)
            self._invalidate_socketcan_sessions(name)
            self._run_system_command(["ip", "link", "set", name, "down"])
            payload = self.system_can_interfaces()
            self._emit("interface_status", payload)
            return {"ok": True, "interface": self._interface_snapshot(name)}

    def connect_device(self, transport: str, connection: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if transport == "serial_bridge":
                driver = DamiaoMotorDriver(
                    serial_port=connection.get("serial_port", "/dev/ttyUSB0"),
                    baudrate=int(connection.get("baudrate", 115200)),
                )
                capabilities = TransportCapabilities(True, True, True, True, True, True)
            elif transport == "socketcan":
                driver = DamiaoSocketCANDriver(
                    channel=connection.get("channel", "can0"),
                    bitrate=int(connection.get("bitrate", 1000000)),
                )
                capabilities = TransportCapabilities(True, True, True, True, True, True)
            else:
                raise ValueError("unsupported transport")

            if not driver.connect():
                raise RuntimeError("device connection failed")

            session = DeviceSession(
                session_id=uuid.uuid4().hex,
                transport=transport,
                driver=driver,
                connection=connection,
                capabilities=capabilities,
            )
            self.sessions[session.session_id] = session
            return {
                "device_session_id": session.session_id,
                "capabilities": asdict(capabilities),
                "connection_state": session.connection_state,
            }

    def disconnect_device(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            session.driver.disconnect()
            session.connection_state = "disconnected"
            return {"ok": True}

    def scan_device(
        self,
        session_id: str,
        job_type: str,
        profile_id: Optional[str] = None,
        current_id: Optional[int] = None,
        expert_mode: bool = False,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
        allow_motion: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            canonical_job_type = _canonical_job_type(job_type)
            if canonical_job_type in SINGLE_SCAN_JOB_TYPES:
                candidates = self._scan_single(session, current_id if expert_mode else None)
                conflicts = candidates[1:] if len(candidates) > 1 else []
                result = {
                    "candidates": candidates[:1] if not expert_mode and len(candidates) > 1 else candidates,
                    "conflicts": conflicts,
                    "summary": {
                        "detected": len(candidates),
                        "conflicts": len(conflicts),
                        "passed": len(candidates) == 1 if not expert_mode else len(candidates) >= 1,
                    },
                    "scan_mode": "expert" if expert_mode else "single_safe_scan",
                }
            elif canonical_job_type in {"arm_comm_scan", "arm_acceptance"}:
                if not profile_id:
                    raise ValueError("profile_id is required")
                arm_scan = self._scan_arm_with_stability(
                    session,
                    profile_id,
                    repeat_count=max(1, min(int(repeat_count), 5)),
                    repeat_delay_ms=max(0, min(int(repeat_delay_ms), 2000)),
                )
                if allow_motion:
                    command_summary = self._attach_arm_command_checks(session, arm_scan["results"])
                    arm_scan["summary"].update(command_summary)
                    arm_scan["summary"]["passed"] = arm_scan["summary"]["passed"] and command_summary["command_test_failed"] == 0
                    arm_scan["summary"]["command_check_mode"] = "enabled"
                else:
                    arm_scan["summary"].update(
                        {
                            "command_test_total": 0,
                            "command_test_passed": 0,
                            "command_test_failed": 0,
                            "command_test_failed_joints": [],
                            "command_check_mode": "safe_readonly",
                        }
                    )
                if canonical_job_type == "arm_comm_scan":
                    arm_scan["summary"]["shipment_checklist"] = self._shipment_checklist(arm_scan["summary"])
                    summary = arm_scan["summary"]
                else:
                    summary = self._acceptance_summary(arm_scan)
                result = {
                    "candidates": arm_scan["results"],
                    "conflicts": arm_scan["unexpected"],
                    "summary": summary,
                    "scan_mode": "can2_acceptance_preview" if canonical_job_type == "arm_acceptance" else "can2_scan_inventory_and_profile_match",
                }
            else:
                raise ValueError("unsupported job type")

            session.last_scan = result
            return result

    def line_inventory(self, session_id: str, profile_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            inventory_ids = DEFAULT_ARM_SCAN_IDS
            expected_map = {}
            expected_ids = set()
            if profile_id:
                profile = self.profile_manager.get_profile(profile_id)
                expected_map = {
                    int(joint["target_esc_id"]): {
                        "joint_name": joint["joint_name"],
                        "motor_type": joint["motor_type"],
                    }
                    for joint in profile["joints"]
                }
                expected_ids = set(expected_map)
                if expected_ids:
                    inventory_ids = sorted(expected_ids)

            inventory, duplicate_esc_ids = self._inventory_scan(session, inventory_ids)

            results = []
            for item in inventory:
                detected_esc_id = int(item["detected_esc_id"])
                matched = expected_map.get(detected_esc_id, {})
                if matched:
                    expected_motor = Motor(
                        _motor_type_from_name(matched["motor_type"]),
                        int(item.get("current_id") or detected_esc_id),
                        int(item.get("detected_mst_id") or detected_esc_id + 0x10),
                    )
                    expected_status = self._refresh_and_snapshot(session, expected_motor, ignore_errors=True)
                    if expected_status.get("last_status_frame"):
                        expected_status["protocol_motor_type"] = expected_status.get("motor_type")
                        expected_status["motor_type"] = matched["motor_type"]
                        item["status"] = expected_status
                results.append(
                    {
                        **item,
                        "matched_joint": matched.get("joint_name"),
                        "matched_motor_type": matched.get("motor_type"),
                    }
                )

            detected_ids = [int(item["detected_esc_id"]) for item in results]
            unexpected_ids = [item_id for item_id in detected_ids if expected_ids and item_id not in expected_ids]
            missing_ids = [item_id for item_id in sorted(expected_ids) if item_id not in detected_ids] if expected_ids else []
            summary = {
                "total_detected": len(results),
                "duplicate_esc_ids": duplicate_esc_ids,
                "detected_esc_ids": detected_ids,
                "unexpected_ids": unexpected_ids,
                "missing_ids": missing_ids,
            }
            payload = {"inventory": results, "summary": summary}
            session.last_inventory = {
                "profile_id": profile_id,
                "inventory_ids": list(inventory_ids),
                "payload": payload,
                "captured_at": time.time(),
            }
            if results:
                session.last_scan = {
                    "candidates": results,
                    "conflicts": [],
                    "summary": {
                        "detected": len(results),
                        "conflicts": 0,
                        "passed": len(results) == 1,
                    },
                    "scan_mode": "line_inventory",
                }
            return payload

    def factory_overview(self) -> Dict[str, Any]:
        with self._lock:
            FACTORY_MOTORS_DIR.mkdir(parents=True, exist_ok=True)
            FACTORY_ARMS_DIR.mkdir(parents=True, exist_ok=True)
            motors = sorted(
                [_load_json(path) for path in FACTORY_MOTORS_DIR.glob("*.json")],
                key=lambda item: (item.get("updated_at") or "", item.get("motor_sn") or ""),
                reverse=True,
            )
            arms = sorted(
                [_load_json(path) for path in FACTORY_ARMS_DIR.glob("*.json")],
                key=lambda item: (item.get("updated_at") or "", item.get("arm_cn") or ""),
                reverse=True,
            )
            zero_count = sum(len(item.get("zero_calibration_records", [])) for item in arms)
            demo_count = sum(len(item.get("demo_validation_records", [])) for item in arms)
            report_count = sum(len(item.get("factory_reports", [])) for item in arms) + sum(
                len(item.get("factory_reports", [])) for item in motors
            )
            return {
                "summary": {
                    "arm_count": len(arms),
                    "motor_count": len(motors),
                    "zero_calibration_count": zero_count,
                    "demo_validation_count": demo_count,
                    "factory_report_count": report_count,
                },
                "arms": arms[:20],
                "motors": motors[:50],
            }

    def generate_factory_arm_cn(self, role: str = "F", date_code: Optional[str] = None, sequence: int = 1) -> Dict[str, Any]:
        role_code = _factory_role_code(role)
        date_value = _factory_date_code(date_code)
        sequence_value = int(sequence)
        if sequence_value < 1 or sequence_value > 99:
            raise ValueError("sequence must be 1..99")
        arm_cn = f"OA{role_code}{date_value}{sequence_value:02d}"
        validation = self.validate_factory_arm_cn(arm_cn)
        return {"arm_cn": arm_cn, "role": role_code, "date_code": date_value, "sequence": sequence_value, "validation": validation}

    def generate_factory_motor_sn(
        self,
        motor_type: str,
        role: str = "F",
        can_id: int = 1,
        date_code: Optional[str] = None,
        sequence: int = 1,
    ) -> Dict[str, Any]:
        role_code = _factory_role_code(role)
        date_value = _factory_date_code(date_code)
        sequence_value = int(sequence)
        can_value = int(can_id)
        if sequence_value < 1 or sequence_value > 99:
            raise ValueError("sequence must be 1..99")
        if can_value < 1 or can_value > 0xFF:
            raise ValueError("can_id must be 1..255")
        model = str(motor_type or "").strip()
        if not model:
            raise ValueError("motor_type is required")
        serial_model = model[3:] if model.upper().startswith("DM-") else model
        motor_sn = f"DM-{serial_model}-{role_code}{can_value:02X}{date_value}{sequence_value:02d}"
        validation = self.validate_factory_motor_sn(motor_sn)
        return {
            "motor_sn": motor_sn,
            "motor_type": model,
            "role": role_code,
            "can_id": can_value,
            "date_code": date_value,
            "sequence": sequence_value,
            "validation": validation,
        }

    def validate_factory_arm_cn(self, arm_cn: str) -> Dict[str, Any]:
        value = str(arm_cn or "").strip().upper()
        match = re.fullmatch(r"OA([FL])(\d{6})(\d{2})", value)
        return {
            "valid": bool(match),
            "type": "arm_cn",
            "value": value,
            "message": "OK" if match else "CN 格式应为 OA{F/L}{YYMMDD}{NN}，例如 OAF26042701",
            "parts": {
                "role": match.group(1),
                "date_code": match.group(2),
                "sequence": int(match.group(3)),
            } if match else {},
        }

    def validate_factory_motor_sn(self, motor_sn: str) -> Dict[str, Any]:
        value = str(motor_sn or "").strip().upper()
        match = re.fullmatch(r"DM-([A-Z0-9]+(?:-[A-Z0-9]+)*)-([FL])([0-9A-F]{2})(\d{6})(\d{2})", value)
        return {
            "valid": bool(match),
            "type": "motor_sn",
            "value": value,
            "message": "OK" if match else "SN 格式应为 DM-{型号}-{F/L}{CANID}{YYMMDD}{NN}，例如 DM-J8009P-2EC-F0126042701",
            "parts": {
                "motor_type": match.group(1),
                "role": match.group(2),
                "can_id": int(match.group(3), 16),
                "date_code": match.group(4),
                "sequence": int(match.group(5)),
            } if match else {},
        }

    def bind_arm_identity(
        self,
        arm_cn: str,
        arm_type: str = "OpenARM Follower",
        bom_profile: str = "openarm_v1",
        left_arm_installed: bool = True,
        right_arm_installed: bool = True,
        notes: Optional[str] = None,
        product_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            arm_cn = arm_cn.strip()
            if not arm_cn:
                raise ValueError("arm_cn is required")
            validation = self.validate_factory_arm_cn(arm_cn)
            if not validation["valid"]:
                raise ValueError(validation["message"])
            FACTORY_ARMS_DIR.mkdir(parents=True, exist_ok=True)
            path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
            existing = _load_json(path, {})

            # The product version is the arm's identity, not a per-step choice: once an
            # arm is on record as 1.0 or 2.0, every later step reads it from here. It is
            # therefore write-once - changing it would retroactively reinterpret every
            # piece of evidence already collected against the other version's rules.
            existing_version = existing.get("product_version")
            if product_version is None:
                product_version = existing_version or DEFAULT_PRODUCT_VERSION
            else:
                product_version = str(product_version)
                if product_version not in self.product_registry.known_versions():
                    raise ValueError(
                        f"unknown product_version {product_version}; known: {self.product_registry.known_versions()}"
                    )
                if existing_version and existing_version != product_version:
                    raise ValueError(
                        f"arm {arm_cn} is already recorded as {existing_version}; "
                        "product version cannot be changed once evidence exists"
                    )

            record = {
                "arm_cn": arm_cn,
                "arm_type": arm_type,
                "bom_profile": bom_profile,
                "product_version": product_version,
                "product_version_source": "declared" if existing_version or product_version != DEFAULT_PRODUCT_VERSION else "default_legacy",
                "left_arm_installed": bool(left_arm_installed),
                "right_arm_installed": bool(right_arm_installed),
                "notes": notes or existing.get("notes"),
                "qc_status": existing.get("qc_status", "in_progress"),
                "delivery_status": existing.get("delivery_status", "draft"),
                "created_at": existing.get("created_at") or _now_iso(),
                "updated_at": _now_iso(),
                "joint_bindings": existing.get("joint_bindings", {}),
                "linked_jobs": existing.get("linked_jobs", []),
                "bundle_history": existing.get("bundle_history", []),
                "zero_calibration_records": existing.get("zero_calibration_records", []),
                "demo_validation_records": existing.get("demo_validation_records", []),
                "active_zero_workflow": existing.get("active_zero_workflow"),
                "active_demo_workflow": existing.get("active_demo_workflow"),
                "workflow_history": existing.get("workflow_history", []),
                "factory_reports": existing.get("factory_reports", []),
                "command_run_history": existing.get("command_run_history", []),
                "evidence_records": existing.get("evidence_records", []),
            }
            _atomic_json(path, record)
            return record

    def _job_reference(self, job: JobRecord) -> Dict[str, Any]:
        return {
            "job_id": job.job_id,
            "job_type": _public_job_type(job.job_type),
            "artifact_dir": job.artifact_dir,
            "status": job.status,
            # Stated only when the job knew its product. Links made before the product
            # registry existed carry None, and are read as "unstated", not as a conflict.
            "product_version": job.product_line,
            "linked_at": _now_iso(),
        }

    def _workflow_steps(self, workflow_type: str) -> List[Dict[str, Any]]:
        if workflow_type == "zero_calibration":
            return [
                {"id": "official_prereq", "label": "官方前置条件复核", "instruction": "确认 Step 1 电机 ID、Step 2 SocketCAN、Step 3 motor-check 已完成。"},
                {"id": "pose_align", "label": "人工摆到官方零位姿态", "instruction": "断电或安全失能后，将单侧机械臂摆到官方零位姿态；夹爪按官方说明闭合为零位。"},
                {"id": "safety_ready", "label": "动态校准安全确认", "instruction": "官方零位校准会自动移动机械臂；清空工作区，急停/断电手段保持在手边，只校准单侧手臂。"},
                {"id": "official_zero_run", "label": "运行官方动态零位命令", "instruction": "通过受控按钮执行 openarm-can-zero-position-calibration，并保存命令输出和状态。"},
                {"id": "power_cycle_verify", "label": "断电重上电复核", "instruction": "断电重上电后重新扫描，确认 ID、波特率、零位和状态可重复。"},
            ]
        if workflow_type == "demo_validation":
            return [
                {"id": "official_demo_prereq", "label": "官方 Demo 前置条件复核", "instruction": "确认 Motor IDs、SocketCAN、motor-check、官方动态零位已完成。"},
                {"id": "demo_safety_ready", "label": "Demo 安全确认", "instruction": "急停在手、工作区清空、知道快速断电方式；Demo 会 enable 并执行位置/力矩/夹爪动作。"},
                {"id": "official_demo_plan", "label": "生成并核对 Demo 命令", "instruction": "确认 openarm-can-demo 或按当前单臂配置构建后的官方 Demo 命令。"},
                {"id": "official_demo_run", "label": "运行官方 Step 5 Demo", "instruction": "通过受控按钮执行官方 Demo，记录 stdout/stderr、返回码和异常现象。"},
                {"id": "result_review", "label": "Demo 结果复核与结论", "instruction": "核对 enable、位置控制、力矩控制、夹爪、状态监测和安全失能是否完成。"},
            ]
        raise ValueError(f"unsupported workflow_type: {workflow_type}")

    def _make_workflow(
        self,
        workflow_type: str,
        arm_cn: str,
        operator: Optional[str],
        linked_job_id: Optional[str],
        notes: Optional[str],
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        linked_job = None
        if linked_job_id:
            linked_job = self._job_reference(self._job(linked_job_id))
        return {
            "workflow_id": uuid.uuid4().hex[:12],
            "workflow_type": workflow_type,
            "arm_cn": arm_cn,
            "status": "active",
            "current_step_index": 0,
            "steps": [
                {
                    **step,
                    "status": "pending" if index > 0 else "active",
                    "completed_at": None,
                    "notes": None,
                }
                for index, step in enumerate(self._workflow_steps(workflow_type))
            ],
            "operator": operator,
            "notes": notes,
            "linked_job": linked_job,
            "started_at": _now_iso(),
            "finished_at": None,
            **extra,
        }

    def _load_arm_record(self, arm_cn: str) -> tuple[Path, Dict[str, Any]]:
        path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
        record = _load_json(path, {})
        if not record:
            raise KeyError(f"arm_cn {arm_cn} not found")
        return path, record

    def _active_workflow_field(self, workflow_type: str) -> str:
        if workflow_type == "zero_calibration":
            return "active_zero_workflow"
        if workflow_type == "demo_validation":
            return "active_demo_workflow"
        raise ValueError(f"unsupported workflow_type: {workflow_type}")

    def official_command_status(self) -> Dict[str, Any]:
        commands = [
            OFFICIAL_ZERO_COMMAND,
            OFFICIAL_MOTOR_CHECK_COMMAND,
            OFFICIAL_CHANGE_BAUDRATE_COMMAND,
            OFFICIAL_DEMO_COMMAND,
            "openarm-can-configure-socketcan",
        ]
        return {
            "commands": {
                command: {
                    "available": _resolve_openarm_command(command) is not None,
                    "path": _resolve_openarm_command(command),
                }
                for command in commands
            },
            "zero_confirmations": ZERO_COMMAND_CONFIRMATIONS,
            "demo_confirmations": DEMO_COMMAND_CONFIRMATIONS,
            "motor_check_confirmations": MOTOR_CHECK_CONFIRMATIONS,
            "baudrate_confirmations": BAUDRATE_COMMAND_CONFIRMATIONS,
            "workbench_zero_confirmations": WORKBENCH_ZERO_CONFIRMATIONS,
            "supported_baudrates": OPENARM_SUPPORTED_BAUDRATES,
            "allowed_command_prefixes": list(OPENARM_ALLOWED_COMMAND_PREFIXES),
        }

    def run_official_motor_check(
        self,
        canid: int,
        recvid: int,
        socketcan: str = "can0",
        fd: bool = False,
        execute: bool = False,
        confirmations: Optional[Dict[str, bool]] = None,
        arm_cn: Optional[str] = None,
        timeout_s: int = 30,
    ) -> Dict[str, Any]:
        command = [OFFICIAL_MOTOR_CHECK_COMMAND, str(int(canid)), str(int(recvid)), str(socketcan)]
        if fd:
            command.append("-fd")
        result = self._run_factory_command(
            arm_cn=arm_cn,
            workflow_type="official_motor_check",
            command=command,
            execute=execute,
            confirmations=confirmations or {},
            required_confirmations=MOTOR_CHECK_CONFIRMATIONS,
            timeout_s=timeout_s,
            command_kind="official_motor_check",
        )
        if execute:
            recovery = self._recover_official_command_disabled_state(
                canport=socketcan,
                arm_cn=arm_cn,
                target_canid=int(canid),
                target_recvid=int(recvid),
            )
            result["post_recovery"] = recovery
            result["command_run"]["post_recovery"] = recovery
            if arm_cn:
                with self._lock:
                    self._replace_factory_command_run(arm_cn, result["command_run"])
        return result

    def run_official_baudrate_change(
        self,
        canid: int,
        baudrate: int,
        socketcan: str = "can0",
        flash: bool = False,
        execute: bool = False,
        confirmations: Optional[Dict[str, bool]] = None,
        arm_cn: Optional[str] = None,
        timeout_s: int = 60,
    ) -> Dict[str, Any]:
        baudrate = int(baudrate)
        if baudrate not in OPENARM_SUPPORTED_BAUDRATES:
            raise ValueError(f"unsupported OpenARM baudrate: {baudrate}")
        command = [
            OFFICIAL_CHANGE_BAUDRATE_COMMAND,
            "--baudrate",
            str(baudrate),
            "--canid",
            str(int(canid)),
            "--socketcan",
            str(socketcan),
        ]
        if flash:
            command.append("--flash")
        return self._run_factory_command(
            arm_cn=arm_cn,
            workflow_type="official_baudrate_change",
            command=command,
            execute=execute,
            confirmations=confirmations or {},
            required_confirmations=BAUDRATE_COMMAND_CONFIRMATIONS,
            timeout_s=timeout_s,
            command_kind="official_baudrate_change",
        )

    def run_official_zero_calibration(
        self,
        arm_cn: str,
        canport: str = "can0",
        arm_side: str = "right_arm",
        execute: bool = False,
        confirmations: Optional[Dict[str, bool]] = None,
        timeout_s: int = 180,
        max_bump_deg: Optional[float] = None,
        max_bump_time_s: Optional[float] = None,
        bump_step_deg: Optional[float] = None,
        bump_dt_s: Optional[float] = None,
        restore_initial_pose: bool = False,
        restore_max_deg: Optional[float] = None,
        skip_gripper_limit_search: bool = True,
    ) -> Dict[str, Any]:
        command = [OFFICIAL_ZERO_COMMAND, "--canport", str(canport), "--arm_side", str(arm_side)]
        if max_bump_deg is not None:
            command.extend(["--max-bump-deg", str(float(max_bump_deg))])
        if max_bump_time_s is not None:
            command.extend(["--max-bump-time-s", str(float(max_bump_time_s))])
        if bump_step_deg is not None:
            command.extend(["--bump-step-deg", str(float(bump_step_deg))])
        if bump_dt_s is not None:
            command.extend(["--bump-dt-s", str(float(bump_dt_s))])
        if restore_initial_pose:
            command.append("--restore-initial-pose")
        if restore_max_deg is not None:
            command.extend(["--restore-max-deg", str(float(restore_max_deg))])
        if skip_gripper_limit_search:
            command.append("--skip-gripper-limit-search")
        result = self._run_factory_command(
            arm_cn=arm_cn,
            workflow_type="zero_calibration",
            command=command,
            execute=execute,
            confirmations=confirmations or {},
            required_confirmations=ZERO_COMMAND_CONFIRMATIONS,
            timeout_s=timeout_s,
            command_kind="official_zero_calibration",
        )
        if result.get("executed"):
            zero_summary = _parse_official_zero_output(
                result["command_run"].get("stdout", ""),
                result["command_run"].get("stderr", ""),
            )
            if restore_initial_pose and not zero_summary.get("restore_completed"):
                zero_summary.setdefault("warning_items", []).append("restore_not_confirmed")
            result["command_run"]["zero_summary"] = zero_summary
            if not zero_summary.get("passed"):
                result["command_run"]["status"] = "failed"
                result["command_run"].setdefault("blocking_items", []).extend(zero_summary.get("blocking_items") or [])
            if zero_summary.get("warning_items"):
                result["command_run"].setdefault("warnings", []).extend(zero_summary.get("warning_items") or [])
            result["command_ok"] = result["command_run"].get("status") == "passed"
        if execute:
            recovery = self._recover_official_command_disabled_state(
                canport=canport,
                arm_cn=arm_cn,
                arm_side=arm_side,
            )
            result["post_recovery"] = recovery
            result["command_run"]["post_recovery"] = recovery
        with self._lock:
            if execute and result.get("post_recovery", {}).get("has_blocking"):
                result["command_run"].setdefault("warnings", []).append("post_recovery_not_disabled")
            if execute:
                self._replace_factory_command_run(arm_cn, result["command_run"])
            self._append_factory_workflow_command_run(arm_cn, "zero_calibration", result["command_run"])
        return result

    def run_official_demo_validation(
        self,
        arm_cn: str,
        command: str,
        execute: bool = False,
        confirmations: Optional[Dict[str, bool]] = None,
        timeout_s: int = 300,
    ) -> Dict[str, Any]:
        command_args = shlex.split(command or "")
        if not command_args:
            raise ValueError("demo command is required")
        product_version = self._arm_product_version(arm_cn)
        gripper = dict(self.product_registry.get(product_version).get("gripper") or {})
        if execute and gripper.get("hardware_verified") is False:
            # The open target drives the motor. Running it before the direction and
            # travel have been confirmed on this product can push the gripper into its
            # own hard stop, so the lock has to hold here, not just at the release gate.
            raise ValueError(
                f"{product_version} 的夹爪参数尚未真机验证，拒绝执行 Demo："
                f"{gripper.get('locked_reason') or '未说明原因'}"
            )
        command_args = _normalize_official_demo_command(command_args, arm_cn=arm_cn, gripper=gripper)
        executable = command_args[0]
        if not any(executable.startswith(prefix) for prefix in OPENARM_ALLOWED_COMMAND_PREFIXES):
            raise ValueError("only OpenARM commands are allowed in controlled demo execution")
        result = self._run_factory_command(
            arm_cn=arm_cn,
            workflow_type="demo_validation",
            command=command_args,
            execute=execute,
            confirmations=confirmations or {},
            required_confirmations=DEMO_COMMAND_CONFIRMATIONS,
            timeout_s=timeout_s,
            command_kind="official_demo_validation",
        )
        if execute and _is_official_demo_command(command_args):
            demo_summary = _parse_official_demo_stdout(result["command_run"].get("stdout", ""))
            result["command_run"]["demo_summary"] = demo_summary
            if not demo_summary.get("passed"):
                result["command_run"]["status"] = "failed"
                result["command_run"].setdefault("warnings", []).extend(demo_summary.get("warning_items") or [])
                result["command_run"].setdefault("blocking_items", []).extend(demo_summary.get("blocking_items") or [])
            with self._lock:
                self._replace_factory_command_run(arm_cn, result["command_run"])
        with self._lock:
            self._append_factory_workflow_command_run(arm_cn, "demo_validation", result["command_run"])
        return result

    def _run_factory_command(
        self,
        arm_cn: str,
        workflow_type: str,
        command: List[str],
        execute: bool,
        confirmations: Dict[str, bool],
        required_confirmations: Dict[str, str],
        timeout_s: int,
        command_kind: str,
    ) -> Dict[str, Any]:
        with self._lock:
            if arm_cn:
                self._load_arm_record(arm_cn)
            missing_confirmations = [
                {"key": key, "label": label}
                for key, label in required_confirmations.items()
                if not confirmations.get(key)
            ]
            executable_path = _resolve_openarm_command(command[0])
            resolved_command = [executable_path or command[0], *command[1:]]
            command_run = {
                "run_id": uuid.uuid4().hex[:12],
                "kind": command_kind,
                "workflow_type": workflow_type,
                "arm_cn": arm_cn,
                "command": command,
                "resolved_command": resolved_command,
                "execute": bool(execute),
                "available": executable_path is not None,
                "executable_path": executable_path,
                "confirmations": confirmations,
                "missing_confirmations": missing_confirmations,
                "started_at": _now_iso(),
                "finished_at": None,
                "status": "planned",
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "timeout_s": int(timeout_s),
            }
        if not execute:
            command_run["finished_at"] = _now_iso()
            if arm_cn:
                with self._lock:
                    self._append_factory_command_history(arm_cn, command_run)
            return {"command_run": command_run, "executed": False, "safe_to_execute": not missing_confirmations, "command_ok": False}
        if missing_confirmations:
            command_run["status"] = "blocked"
            command_run["finished_at"] = _now_iso()
            if arm_cn:
                with self._lock:
                    self._append_factory_command_history(arm_cn, command_run)
            return {"command_run": command_run, "executed": False, "safe_to_execute": False, "command_ok": False}
        if executable_path is None:
            command_run["status"] = "unavailable"
            command_run["finished_at"] = _now_iso()
            if arm_cn:
                with self._lock:
                    self._append_factory_command_history(arm_cn, command_run)
            return {"command_run": command_run, "executed": False, "safe_to_execute": True, "command_ok": False}
        try:
            completed = subprocess.run(
                resolved_command,
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_s)),
                check=False,
            )
            command_run["returncode"] = completed.returncode
            command_run["stdout"] = (completed.stdout or "")[-OFFICIAL_COMMAND_STDOUT_LIMIT:]
            command_run["stderr"] = (completed.stderr or "")[-OFFICIAL_COMMAND_STDERR_LIMIT:]
            command_run["status"] = "passed" if completed.returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            command_run["stdout"] = (exc.stdout or "")[-OFFICIAL_COMMAND_STDOUT_LIMIT:] if isinstance(exc.stdout, str) else ""
            command_run["stderr"] = (exc.stderr or "")[-OFFICIAL_COMMAND_STDERR_LIMIT:] if isinstance(exc.stderr, str) else ""
            command_run["status"] = "timeout"
        command_run["finished_at"] = _now_iso()
        if arm_cn:
            with self._lock:
                self._append_factory_command_history(arm_cn, command_run)
        return {
            "command_run": command_run,
            "executed": command_run["status"] in {"passed", "failed", "timeout"},
            "safe_to_execute": True,
            "command_ok": command_run["status"] == "passed",
        }

    def _append_factory_command_history(self, arm_cn: str, command_run: Dict[str, Any]):
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            history = list(arm.get("command_run_history", []))
            history.insert(0, command_run)
            arm["command_run_history"] = history[:50]
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)

    def _replace_factory_command_run(self, arm_cn: str, command_run: Dict[str, Any]):
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            history = list(arm.get("command_run_history", []))
            run_id = command_run.get("run_id")
            replaced = False
            for index, item in enumerate(history):
                if item.get("run_id") == run_id:
                    history[index] = command_run
                    replaced = True
                    break
            if not replaced:
                history.insert(0, command_run)
            arm["command_run_history"] = history[:50]
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)

    def _recover_official_command_disabled_state(
        self,
        canport: str,
        arm_cn: Optional[str] = None,
        arm_side: Optional[str] = None,
        target_canid: Optional[int] = None,
        target_recvid: Optional[int] = None,
    ) -> Dict[str, Any]:
        profile_id = None
        if arm_side:
            profile_id = "openarm_left_arm_v1" if arm_side == "left_arm" else "openarm_right_arm_v1"
        elif arm_cn:
            try:
                _path, arm = self._load_arm_record(arm_cn)
                profile_id = arm.get("bom_profile")
            except Exception:
                profile_id = None

        joints: List[Dict[str, Any]] = []
        if profile_id:
            try:
                profile = self.profile_manager.get_profile(profile_id)
                joints = list(profile.get("joints", []))
            except Exception:
                joints = []
        if target_canid is not None:
            matching = [joint for joint in joints if int(joint.get("target_esc_id", -1)) == int(target_canid)]
            if matching:
                joints = matching
            else:
                joints = [
                    {
                        "joint_name": f"CAN-{int(target_canid)}",
                        "motor_type": "DM-J4310-2EC",
                        "target_esc_id": int(target_canid),
                        "target_mst_id": int(target_recvid or 0),
                    }
                ]

        payload = {
            "canport": canport,
            "profile_id": profile_id,
            "target_canid": target_canid,
            "started_at": _now_iso(),
            "finished_at": None,
            "attempted": bool(joints),
            "has_blocking": False,
            "results": [],
        }
        if not joints:
            payload["finished_at"] = _now_iso()
            payload["has_blocking"] = True
            payload["error"] = "no joints available for recovery"
            return payload

        driver = DamiaoSocketCANDriver(channel=canport, bitrate=1000000)
        if not driver.connect():
            payload["finished_at"] = _now_iso()
            payload["has_blocking"] = True
            payload["error"] = "socketcan recovery connect failed"
            return payload

        try:
            for joint in joints:
                motor = Motor(
                    _motor_type_from_name(joint["motor_type"]),
                    int(joint["target_esc_id"]),
                    int(joint["target_mst_id"]),
                )
                item = {
                    "joint_name": joint.get("joint_name"),
                    "esc_id": int(joint["target_esc_id"]),
                    "mst_id": int(joint["target_mst_id"]),
                    "disable_ok": False,
                    "status": None,
                    "issues": [],
                }
                try:
                    if hasattr(driver, "ensure_motor"):
                        driver.ensure_motor(motor)
                    elif hasattr(driver, "addMotor"):
                        driver.addMotor(motor)
                    item["disable_ok"] = bool(driver.disable(motor))
                    time.sleep(0.03)
                    driver.refresh_motor_status(motor)
                    snapshot = motor.snapshot()
                    item["status"] = snapshot
                    if not item["disable_ok"]:
                        item["issues"].append("disable_failed")
                    if snapshot.get("status") != "DISABLED":
                        item["issues"].append("disable_state_not_confirmed")
                    if snapshot.get("has_error"):
                        item["issues"].append("post_recovery_motor_error")
                    elif _status_read_anomaly(snapshot):
                        item["issues"].append("post_recovery_status_read_anomaly")
                except Exception as error:
                    item["issues"].append("post_recovery_failed")
                    item["error"] = str(error)
                item["passed"] = not item["issues"]
                payload["results"].append(item)
            payload["has_blocking"] = any(not item.get("passed") for item in payload["results"])
        finally:
            try:
                driver.disconnect()
            except Exception:
                pass
        payload["finished_at"] = _now_iso()
        return payload

    def _append_factory_evidence(self, arm_cn: str, evidence_ref: Dict[str, Any]):
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            records = list(arm.get("evidence_records", []))
            records.insert(0, evidence_ref)
            arm["evidence_records"] = records[:100]
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)

    def _append_factory_workflow_command_run(
        self,
        arm_cn: str,
        workflow_type: str,
        command_run: Dict[str, Any],
    ):
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            field = self._active_workflow_field(workflow_type)
            workflow = arm.get(field)
            if workflow:
                runs = list(workflow.get("command_runs", []))
                runs.insert(0, command_run)
                workflow["command_runs"] = runs[:20]
                arm[field] = workflow
            history = [item for item in arm.get("command_run_history", []) if item.get("run_id") != command_run.get("run_id")]
            history.insert(0, command_run)
            arm["command_run_history"] = history[:50]
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)

    def start_factory_workflow(
        self,
        arm_cn: str,
        workflow_type: str,
        operator: Optional[str] = None,
        linked_job_id: Optional[str] = None,
        notes: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            field = self._active_workflow_field(workflow_type)
            active = arm.get(field)
            if active and active.get("status") == "active":
                raise ValueError(f"{workflow_type} workflow already active")
            workflow = self._make_workflow(workflow_type, arm_cn, operator, linked_job_id, notes, kwargs)
            arm[field] = workflow
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)
            return {"arm": arm, "workflow": workflow}

    def advance_factory_workflow(
        self,
        arm_cn: str,
        workflow_type: str,
        action: str,
        notes: Optional[str] = None,
        final_status: str = "passed",
    ) -> Dict[str, Any]:
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            field = self._active_workflow_field(workflow_type)
            workflow = arm.get(field)
            if not workflow or workflow.get("status") not in {"active", "awaiting_finalize"}:
                raise ValueError(f"no active {workflow_type} workflow")

            index = int(workflow.get("current_step_index", 0))
            steps = workflow.get("steps", [])
            if not steps:
                raise ValueError("workflow has no steps")

            if action == "complete_step":
                if index >= len(steps):
                    raise ValueError("workflow already finished")
                steps[index]["status"] = "completed"
                steps[index]["completed_at"] = _now_iso()
                if notes:
                    steps[index]["notes"] = notes
                next_index = index + 1
                workflow["current_step_index"] = next_index
                if next_index < len(steps):
                    steps[next_index]["status"] = "active"
                else:
                    workflow["status"] = "awaiting_finalize"
                workflow["steps"] = steps
            elif action == "mark_failed":
                if index < len(steps):
                    steps[index]["status"] = "failed"
                    if notes:
                        steps[index]["notes"] = notes
                workflow["status"] = "failed"
                workflow["finished_at"] = _now_iso()
                workflow["steps"] = steps
                workflow["failure_notes"] = notes
            elif action == "finalize":
                if workflow.get("status") not in {"active", "awaiting_finalize", "failed"}:
                    raise ValueError("workflow is not finalizable")
                normalized_status = final_status if final_status in {"passed", "warning", "failed"} else "passed"
                workflow["status"] = "completed"
                workflow["result_status"] = normalized_status
                workflow["finished_at"] = _now_iso()
                workflow["final_notes"] = notes
                if workflow_type == "zero_calibration":
                    result = self.record_zero_calibration(
                        arm_cn=arm_cn,
                        calibration_scope=workflow.get("calibration_scope", "whole_arm"),
                        status=normalized_status,
                        operator=workflow.get("operator"),
                        zero_pose_name=workflow.get("zero_pose_name", "openarm_home"),
                        linked_job_id=(workflow.get("linked_job") or {}).get("job_id"),
                        notes=notes or workflow.get("notes"),
                        joints=workflow.get("joints"),
                        command_runs=workflow.get("command_runs"),
                    )
                    record_entry = result["entry"]
                else:
                    result = self.record_demo_validation(
                        arm_cn=arm_cn,
                        demo_name=workflow.get("demo_name", "official_demo"),
                        status=normalized_status,
                        operator=workflow.get("operator"),
                        validation_scope=workflow.get("validation_scope", "official_demo"),
                        linked_job_id=(workflow.get("linked_job") or {}).get("job_id"),
                        notes=notes or workflow.get("notes"),
                        command=workflow.get("command"),
                        command_runs=workflow.get("command_runs"),
                    )
                    record_entry = result["entry"]
                history = list(arm.get("workflow_history", []))
                history.insert(0, workflow)
                arm = result["arm"]
                arm["workflow_history"] = history[:30]
                arm[field] = None
                arm["updated_at"] = _now_iso()
                _atomic_json(path, arm)
                return {"arm": arm, "workflow": workflow, "record_entry": record_entry}
            else:
                raise ValueError(f"unsupported workflow action: {action}")

            arm[field] = workflow
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)
            return {"arm": arm, "workflow": workflow}

    def _append_arm_record_entry(self, arm_cn: str, category: str, entry: Dict[str, Any]) -> str:
        record_dir = _arm_record_dir(arm_cn) / category
        record_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{entry['record_id']}.json"
        path = record_dir / file_name
        _atomic_json(path, entry)
        return str(path)

    def record_zero_calibration(
        self,
        arm_cn: str,
        calibration_scope: str,
        status: str,
        operator: Optional[str] = None,
        zero_pose_name: str = "openarm_home",
        linked_job_id: Optional[str] = None,
        notes: Optional[str] = None,
        joints: Optional[List[str]] = None,
        method: str = "manual_record",
        joint_results: Optional[List[Dict[str, Any]]] = None,
        precheck_summary: Optional[Dict[str, Any]] = None,
        command_runs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
            arm = _load_json(path, {})
            if not arm:
                raise KeyError(f"arm_cn {arm_cn} not found")
            linked_job = None
            if linked_job_id:
                linked_job = self._job_reference(self._job(linked_job_id))
            entry = {
                "record_id": uuid.uuid4().hex[:12],
                "record_type": "zero_calibration",
                "arm_cn": arm_cn,
                "calibration_scope": calibration_scope,
                "status": status,
                "zero_pose_name": zero_pose_name,
                "operator": operator,
                "notes": notes,
                "joints": joints or [],
                "method": method,
                "joint_results": joint_results or [],
                "precheck_summary": precheck_summary or {},
                "command_runs": command_runs or [],
                "linked_job": linked_job,
                "recorded_at": _now_iso(),
            }
            entry["record_path"] = self._append_arm_record_entry(arm_cn, "zero_calibration", entry)
            records = list(arm.get("zero_calibration_records", []))
            records.insert(0, entry)
            arm["zero_calibration_records"] = records[:20]
            if status == "passed":
                arm["qc_status"] = "zero_calibrated"
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)
            return {"arm": arm, "entry": entry}

    def record_demo_validation(
        self,
        arm_cn: str,
        demo_name: str,
        status: str,
        operator: Optional[str] = None,
        validation_scope: str = "official_demo",
        linked_job_id: Optional[str] = None,
        notes: Optional[str] = None,
        command: Optional[str] = None,
        command_runs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
            arm = _load_json(path, {})
            if not arm:
                raise KeyError(f"arm_cn {arm_cn} not found")
            linked_job = None
            if linked_job_id:
                linked_job = self._job_reference(self._job(linked_job_id))
            entry = {
                "record_id": uuid.uuid4().hex[:12],
                "record_type": "demo_validation",
                "arm_cn": arm_cn,
                "demo_name": demo_name,
                "validation_scope": validation_scope,
                "status": status,
                "command": command,
                "command_runs": command_runs or [],
                "operator": operator,
                "notes": notes,
                "linked_job": linked_job,
                "recorded_at": _now_iso(),
            }
            entry["record_path"] = self._append_arm_record_entry(arm_cn, "demo_validation", entry)
            records = list(arm.get("demo_validation_records", []))
            records.insert(0, entry)
            arm["demo_validation_records"] = records[:20]
            if status == "passed":
                arm["delivery_status"] = "demo_verified"
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)
            return {"arm": arm, "entry": entry}

    def capture_can_health(
        self,
        interface: str = "can0",
        arm_cn: Optional[str] = None,
        job_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            interface = str(interface or "can0")
            interfaces = self._list_socketcan_interfaces()
            snapshot = next((item for item in interfaces if item["name"] == interface), None)
            try:
                details_result = self._run_system_command(["ip", "-details", "link", "show", "dev", interface], check=False)
                raw_details = (details_result.stdout or details_result.stderr or "")[-8000:]
            except Exception as error:
                raw_details = str(error)
            checks = {
                "interface_present": snapshot is not None,
                "is_gs_usb": bool(snapshot and snapshot.get("is_gs_usb")),
                "bitrate_configured": bool(snapshot and snapshot.get("bitrate")),
                "can_state_error_active": bool(snapshot and snapshot.get("can_state") == "ERROR-ACTIVE"),
                "link_state_up": bool(snapshot and snapshot.get("state") in {"UP", "UNKNOWN"}),
                "no_bus_errors": bool(
                    snapshot
                    and int((snapshot.get("statistics") or {}).get("rx_errors") or 0) == 0
                    and int((snapshot.get("statistics") or {}).get("tx_errors") or 0) == 0
                ),
                "no_dropped_frames": bool(
                    snapshot
                    and int((snapshot.get("statistics") or {}).get("rx_dropped") or 0) == 0
                    and int((snapshot.get("statistics") or {}).get("tx_dropped") or 0) == 0
                ),
            }
            status = "passed" if all(checks.values()) else "warning"
            if not checks["interface_present"]:
                status = "failed"
            payload = {
                "evidence_id": uuid.uuid4().hex[:12],
                "evidence_type": "can_health_snapshot",
                "interface": interface,
                "arm_cn": arm_cn,
                "job_id": job_id,
                "notes": notes,
                "status": status,
                "checks": checks,
                "interface_snapshot": snapshot,
                "all_interfaces": interfaces,
                "raw_ip_details": raw_details,
                "captured_at": _now_iso(),
            }
            evidence_ref = self._write_factory_evidence(payload, arm_cn, "can_health")
            payload["evidence_ref"] = evidence_ref
            if arm_cn:
                self._append_factory_evidence(arm_cn, evidence_ref)
            return payload

    def capture_candump_evidence(
        self,
        interface: str = "can0",
        duration_s: float = 2.0,
        arm_cn: Optional[str] = None,
        job_id: Optional[str] = None,
        label: str = "factory_can_trace",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            interface = str(interface or "can0")
            duration_s = max(0.5, min(float(duration_s), 10.0))
            candump_path = shutil.which("candump")
            payload = {
                "evidence_id": uuid.uuid4().hex[:12],
                "evidence_type": "candump_trace",
                "interface": interface,
                "duration_s": duration_s,
                "arm_cn": arm_cn,
                "job_id": job_id,
                "label": label,
                "notes": notes,
                "candump_path": candump_path,
                "status": "unavailable" if candump_path is None else "pending",
                "stdout": "",
                "stderr": "",
                "returncode": None,
                "captured_at": _now_iso(),
            }
            if candump_path is None:
                payload["stderr"] = "candump not found; install can-utils to collect raw CAN evidence"
            else:
                try:
                    completed = subprocess.run(
                        [candump_path, "-L", interface],
                        capture_output=True,
                        text=True,
                        timeout=duration_s,
                        check=False,
                    )
                    payload["stdout"] = completed.stdout or ""
                    payload["stderr"] = completed.stderr or ""
                    payload["returncode"] = completed.returncode
                    payload["status"] = "captured" if completed.stdout else "empty"
                except subprocess.TimeoutExpired as error:
                    stdout = error.stdout if isinstance(error.stdout, str) else (error.stdout or b"").decode(errors="ignore")
                    stderr = error.stderr if isinstance(error.stderr, str) else (error.stderr or b"").decode(errors="ignore")
                    payload["stdout"] = stdout or ""
                    payload["stderr"] = stderr or ""
                    payload["status"] = "captured" if payload["stdout"] else "empty"
                except Exception as error:
                    payload["stderr"] = str(error)
                    payload["status"] = "failed"
            evidence_ref = self._write_factory_evidence(payload, arm_cn, "candump")
            payload["evidence_ref"] = evidence_ref
            if arm_cn:
                self._append_factory_evidence(arm_cn, evidence_ref)
            return payload

    def factory_release_gate(self, arm_cn: str) -> Dict[str, Any]:
        with self._lock:
            _path, arm = self._load_arm_record(arm_cn)
            linked_jobs = arm.get("linked_jobs", [])
            zero_records = arm.get("zero_calibration_records", [])
            demo_records = arm.get("demo_validation_records", [])
            evidence_records = arm.get("evidence_records", [])

            linked_job_evidence = [self._linked_job_evidence(item) for item in linked_jobs]
            passed_jobs = [item for item in linked_job_evidence if item.get("status") == "passed" and not item.get("has_blocking_issues")]
            blocking_items = []
            warning_items = []
            if not linked_jobs:
                blocking_items.append("缺少整臂扫描/验收任务挂载")
            if linked_jobs and not passed_jobs:
                blocking_items.append("未找到通过且无阻断问题的整臂任务")
            if not any(record.get("status") == "passed" for record in zero_records):
                blocking_items.append("缺少通过的零位校准记录")
            if not any(record.get("status") == "passed" for record in demo_records):
                blocking_items.append("缺少通过的 Demo/Follower 验证记录")
            if not any(record.get("evidence_type") == "can_health_snapshot" and record.get("status") == "passed" for record in evidence_records):
                blocking_items.append("缺少通过的 CAN 健康快照")
            has_candump = any(record.get("evidence_type") == "candump_trace" and record.get("status") == "captured" for record in evidence_records)
            if not has_candump and not self._linked_jobs_have_raw_status_frames(linked_jobs):
                warning_items.append("缺少原始 CAN 帧证据")
            if not arm.get("factory_reports"):
                warning_items.append("尚未挂载出厂报告")

            arm_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
            blocking_items.extend(self._product_version_conflicts(arm, linked_job_evidence))
            try:
                product_locks = self.product_registry.lock_reasons(arm_version)
            except KeyError:
                blocking_items.append(f"整机记录的产品版本 {arm_version} 不在产品注册表中")
                product_locks = {}
            if product_locks:
                # A product whose motion behaviour has never been confirmed on hardware
                # must not produce a formal factory report, whatever the evidence says.
                blocking_items.append(
                    f"产品版本 {arm_version} 仍有未经真机验证的锁定项：{'、'.join(sorted(product_locks))}"
                )

            release_ready = not blocking_items
            return {
                "arm_cn": arm_cn,
                "product_version": arm_version,
                "product_version_locks": product_locks,
                "release_ready": release_ready,
                "release_decision": "PASS" if release_ready else "HOLD",
                "blocking_items": blocking_items,
                "warning_items": warning_items,
                "evidence": {
                    "raw_status_frame_evidence": self._linked_jobs_have_raw_status_frames(linked_jobs),
                    "linked_jobs": linked_job_evidence,
                    "zero_records": len(zero_records),
                    "demo_records": len(demo_records),
                    "evidence_records": len(evidence_records),
                    "can_health_records": [item for item in evidence_records if item.get("evidence_type") == "can_health_snapshot"][:5],
                    "candump_records": [item for item in evidence_records if item.get("evidence_type") == "candump_trace"][:5],
                },
            }

    def generate_motor_parameter_report(
        self,
        motor_sn: str,
        job_id: Optional[str] = None,
        operator: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            motor_path = FACTORY_MOTORS_DIR / f"{_safe_name(motor_sn)}.json"
            motor = _load_json(motor_path, {})
            if not motor:
                raise KeyError(f"motor_sn {motor_sn} not found")
            job = self.jobs.get(job_id) if job_id else None
            params = {}
            if job:
                for item in job.motors.values():
                    params.update(item.get("target", {}) or {})
                    params.update(item.get("params", {}) or {})
                    current = item.get("current", {}) or {}
                    params.update(current.get("params", {}) or {})
            motor_job_payload = job.motors.get("commissioned_motor", {}) if job else {}
            parameter_rows = [
                ("Manufacturer", motor.get("vendor", "DaMiao"), "IEC 60034 style identity"),
                ("Model", motor.get("motor_type"), "motor model"),
                ("Serial Number", motor.get("motor_sn"), "traceability"),
                ("Installed Joint", motor.get("installed_joint"), "OpenARM joint"),
                ("ESC_ID", motor.get("esc_id") or params.get("ESC_ID") or params.get("target_esc_id"), "CAN sender id"),
                ("MST_ID", motor.get("mst_id") or params.get("MST_ID") or params.get("target_mst_id"), "status receiver id"),
                ("CTRL_MODE", params.get("CTRL_MODE") or params.get("target_ctrl_mode"), "operation mode"),
                ("TIMEOUT", params.get("TIMEOUT") or params.get("target_timeout"), "communication timeout"),
                ("can_br", params.get("can_br") or params.get("target_can_br"), "CAN bitrate"),
                ("Gr", params.get("Gr") or params.get("target_gr"), "gear ratio"),
                ("KT_Value", params.get("KT_Value") or params.get("target_kt_value"), "torque constant"),
                ("PMAX", params.get("PMAX") or params.get("target_pmax"), "position limit"),
                ("VMAX", params.get("VMAX") or params.get("target_vmax"), "velocity limit"),
                ("TMAX", params.get("TMAX") or params.get("target_tmax"), "torque limit"),
                ("Firmware", motor.get("fw_version") or params.get("sw_ver"), "firmware/software version"),
                ("Hardware Revision", motor.get("hw_revision"), "hardware revision"),
            ]
            if motor_job_payload.get("link_test"):
                link_test = motor_job_payload["link_test"]
                parameter_rows.extend(
                    [
                        ("Link Test", "PASS" if link_test.get("passed") else "FAIL", f"issues={','.join(link_test.get('issues', [])) or '-'}"),
                        ("Link Test Joint", link_test.get("joint_name"), "enable/disable communication check"),
                    ]
                )
            if motor_job_payload.get("micro_test"):
                micro_test = motor_job_payload["micro_test"]
                measurements = micro_test.get("measurements", {})
                parameter_rows.extend(
                    [
                        ("Micro Response Test", "PASS" if micro_test.get("passed") else "FAIL", f"issues={','.join(micro_test.get('issues', [])) or '-'}"),
                        ("Micro Response Peak Delta", measurements.get("peak_delta"), "rad"),
                        ("Micro Response Final Delta", measurements.get("final_delta"), "rad"),
                    ]
                )
            report = self._write_factory_report(
                subject_id=motor_sn,
                subject_type="motor",
                report_type="motor_parameter_report",
                title="Motor Parameter Report",
                summary={
                    "motor_sn": motor_sn,
                    "motor_type": motor.get("motor_type"),
                    "installed_joint": motor.get("installed_joint"),
                    "arm_cn": motor.get("arm_cn"),
                    "job_id": job_id,
                    "operator": operator,
                    "notes": notes,
                    "reference_standards": ["IEC 60034 style rated/nameplate parameter layout", "OpenARM Motor ID / CAN setup"],
                },
                rows=parameter_rows,
            )
            reports = list(motor.get("factory_reports", []))
            reports.insert(0, report["report_ref"])
            motor["factory_reports"] = reports[:30]
            motor["updated_at"] = _now_iso()
            _atomic_json(motor_path, motor)
            return report

    def generate_zero_calibration_report(self, arm_cn: str, operator: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            zero_records = arm.get("zero_calibration_records", [])
            rows = [
                (
                    record.get("recorded_at"),
                    record.get("calibration_scope"),
                    record.get("zero_pose_name"),
                    record.get("status"),
                    record.get("method", "manual_record"),
                    len(record.get("joint_results", [])),
                    record.get("operator"),
                    record.get("notes"),
                )
                for record in zero_records
            ]
            if not rows:
                rows = [("未记录", "-", "-", "missing", "-", 0, operator, notes)]
            report = self._write_factory_report(
                subject_id=arm_cn,
                subject_type="arm",
                report_type="zero_calibration_report",
                title="Zero Calibration Report",
                summary={
                    "arm_cn": arm_cn,
                    "operator": operator,
                    "notes": notes,
                    "reference_standards": ["OpenARM Motor Configuration", "factory zero persistence verification"],
                    "record_count": len(zero_records),
                },
                rows=rows,
                headers=["Recorded At", "Scope", "Zero Pose", "Status", "Method", "Joint Count", "Operator", "Notes"],
            )
            self._attach_report_to_arm(path, arm, report["report_ref"])
            return report

    def generate_safety_test_report(self, arm_cn: str, operator: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            linked_jobs = arm.get("linked_jobs", [])
            zero_passed = any(record.get("status") == "passed" for record in arm.get("zero_calibration_records", []))
            demo_passed = any(record.get("status") == "passed" for record in arm.get("demo_validation_records", []))
            safety_rows = [
                ("Workspace clear", "manual_required", "ISO/TS 15066 style collaborative risk check"),
                ("Emergency stop / power cut available", "manual_required", "ISO 10218 / ISO/TS 15066 safety principle"),
                ("CAN communication scan attached", "passed" if linked_jobs else "missing", f"{len(linked_jobs)} linked job(s)"),
                ("Zero calibration passed", "passed" if zero_passed else "missing", "required before demo / follower motion"),
                ("Demo / Follower validation passed", "passed" if demo_passed else "missing", "required for full factory release"),
                ("Motion limits reviewed", "manual_required", "speed / torque / workspace limit review"),
                ("No critical issue outstanding", "manual_required", "confirm latest issue scan before release"),
            ]
            report = self._write_factory_report(
                subject_id=arm_cn,
                subject_type="arm",
                report_type="safety_test_report",
                title="Safety Test Report",
                summary={
                    "arm_cn": arm_cn,
                    "operator": operator,
                    "notes": notes,
                    "reference_standards": ["ISO/TS 15066 collaborative safety guidance", "ISO 10218 robot system safety principles"],
                    "release_ready": bool(linked_jobs and zero_passed and demo_passed),
                },
                rows=safety_rows,
                headers=["Check Item", "Status", "Evidence / Requirement"],
            )
            self._attach_report_to_arm(path, arm, report["report_ref"])
            return report

    def generate_factory_acceptance_report(self, arm_cn: str, operator: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            linked_jobs = arm.get("linked_jobs", [])
            zero_records = arm.get("zero_calibration_records", [])
            demo_records = arm.get("demo_validation_records", [])
            report_manifest = self._factory_report_manifest_for_arm(arm)
            gate = self.factory_release_gate(arm_cn)
            release_ready = gate["release_ready"]
            rows = self._factory_acceptance_standard_rows(arm, gate)
            report = self._write_factory_report(
                subject_id=arm_cn,
                subject_type="arm",
                report_type="factory_acceptance_report",
                title="Whole Arm Factory Test Report",
                summary={
                    "arm_serial": arm_cn,
                    "arm_type": arm.get("arm_type"),
                    "bom_profile": arm.get("bom_profile"),
                    "operator": operator,
                    "notes": notes,
                    "reference_standards": [
                        "OpenARM Setup Step 1~5",
                        "OpenARM Motor Configuration",
                        "OpenARM Hands-On Demo Run",
                    ],
                    "release_ready": release_ready,
                    "release_gate": gate,
                    "attached_report_manifest": report_manifest,
                    "linked_job_count": len(linked_jobs),
                    "zero_record_count": len(zero_records),
                    "demo_record_count": len(demo_records),
                },
                rows=rows,
                headers=["Test Item", "Object", "Standard / Requirement", "Measured Feedback Data", "Raw Evidence", "Result"],
            )
            self._attach_report_to_arm(path, arm, report["report_ref"])
            return report

    def generate_formal_factory_acceptance_report(
        self,
        arm_cn: str,
        operator: Optional[str] = None,
        project_lead: Optional[str] = None,
        notes: Optional[str] = None,
        profile_id: Optional[str] = None,
        report_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            path, arm = self._load_arm_record(arm_cn)
            selected_profile_id = str(profile_id or arm.get("bom_profile") or "openarm_right_arm_v1")
            profile = self.profile_manager.get_profile(selected_profile_id)
            report_arm = self._formal_factory_report_arm_view(arm, selected_profile_id, profile)
            # The report states the bus the arm was tested on. Reading it from the
            # product means a 2.0 arm can never ship a report claiming CAN 2.0.
            product_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
            try:
                bus = dict(self.product_registry.get(product_version)["can"]["operation"])
            except KeyError:
                bus = dict(self.product_registry.get(DEFAULT_PRODUCT_VERSION)["can"]["operation"])
            report = render_formal_factory_report(
                root_dir=ROOT_DIR,
                reports_dir=FORMAL_REPORTS_DIR,
                arm=report_arm,
                profile=profile,
                bus=bus,
                operator=operator,
                project_lead=project_lead,
                notes=notes,
                report_date=report_date,
                pdf_writer=_write_pdf_from_html,
            )
            self._attach_report_to_arm(path, arm, report["report_ref"])
            return report

    def _formal_factory_report_arm_view(self, arm: Dict[str, Any], profile_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Build a side-specific arm record view for formal report rendering.

        Whole-arm records can contain both left and right arm history under the same serial number.
        Formal factory reports must use the requested profile's latest arm_acceptance job so static
        matrices and PASS/WARNING decisions are not polluted by the opposite side.
        """
        report_arm = dict(arm)
        report_arm["bom_profile"] = profile_id
        if profile.get("arm_side"):
            report_arm["arm_side"] = profile.get("arm_side")

        matching_jobs = []
        for linked_job in arm.get("linked_jobs") or []:
            payload = self._linked_job_payload(linked_job)
            job = payload.get("job") or {}
            linked_arm_cn = linked_job.get("arm_cn") or job.get("arm_cn") or job.get("subject_id")
            if linked_arm_cn and str(linked_arm_cn) != str(arm.get("arm_cn")):
                continue
            if job.get("profile_id") == profile_id and job.get("job_type") == "arm_acceptance":
                matching_jobs.append(linked_job)

        if matching_jobs:
            report_arm["linked_jobs"] = matching_jobs
        return report_arm

    def _linked_job_payload(self, linked_job: Dict[str, Any]) -> Dict[str, Any]:
        artifact_dir = Path(linked_job.get("artifact_dir") or "")
        if not artifact_dir:
            return {}
        return _load_json(artifact_dir / "job.json", {})

    def _factory_report_manifest_for_arm(self, arm: Dict[str, Any]) -> List[Dict[str, Any]]:
        manifest = []
        for report_ref in arm.get("factory_reports", []):
            manifest.append({"owner": arm.get("arm_cn"), **report_ref})
        return manifest

    def _factory_acceptance_standard_rows(self, arm: Dict[str, Any], gate: Dict[str, Any]) -> List[tuple]:
        rows: List[tuple] = []
        arm_cn = arm.get("arm_cn")
        rows.append(_report_section_row("1. General Information"))
        rows.append(("Traceability", "Whole arm", "Only whole-arm serial is reported", f"arm_serial={arm_cn}", "-", "PASS" if arm_cn else "FAIL"))
        rows.append(("Release Gate", "Whole arm", "No blocking items for shipment", f"blocking={gate.get('blocking_items') or []}; warnings={gate.get('warning_items') or []}", "-", gate.get("release_decision", "HOLD")))

        evidence_records = arm.get("evidence_records", [])
        if evidence_records:
            rows.append(_report_section_row("2. Bus And Raw Evidence"))
        for record in evidence_records:
            if record.get("evidence_type") == "can_health_snapshot":
                payload = _load_json(Path(record.get("json_path", "")), {})
                checks = payload.get("checks", {})
                snapshot = payload.get("interface_snapshot") or {}
                rows.append((
                    "CAN Health",
                    payload.get("interface") or record.get("interface") or "-",
                    "interface present, bitrate configured, ERROR-ACTIVE",
                    f"state={snapshot.get('can_state')}; bitrate={snapshot.get('bitrate')}; checks={checks}",
                    record.get("json_path"),
                    str(payload.get("status") or record.get("status") or "-").upper(),
                ))
            elif record.get("evidence_type") == "candump_trace":
                payload = _load_json(Path(record.get("json_path", "")), {})
                if payload.get("status") != "captured":
                    continue
                rows.append((
                    "Raw CAN Trace",
                    payload.get("interface") or record.get("interface") or "-",
                    "candump evidence captured for tested bus",
                    f"duration_s={payload.get('duration_s')}; bytes={len(payload.get('stdout') or '')}; status={payload.get('status')}",
                    record.get("log_path") or record.get("json_path"),
                    "PASS" if payload.get("status") == "captured" else "WARNING",
                ))

        rows.append(_report_section_row("3. Arm-Level And Per-Motor Electrical Tests"))
        for linked_job in arm.get("linked_jobs", []):
            rows.extend(self._factory_rows_from_linked_job(linked_job))

        rows.append(_report_section_row("4. Official Dynamic Zero Calibration"))
        for record in arm.get("zero_calibration_records", []):
            command_runs = record.get("command_runs") or []
            rows.append((
                "Official Dynamic Zero Calibration",
                record.get("calibration_scope") or "whole_arm",
                "OpenARM Step 4 dynamic zero completed and recorded",
                f"status={record.get('status')}; pose={record.get('zero_pose_name')}; method={record.get('method')}; command_runs={len(command_runs)}",
                record.get("record_path"),
                str(record.get("status") or "missing").upper(),
            ))
            for run in command_runs:
                rows.append(self._factory_row_from_command_run("Official Zero Command", run))

        rows.append(_report_section_row("5. Official Demo Test"))
        for record in arm.get("demo_validation_records", []):
            command_runs = record.get("command_runs") or []
            demo_summaries = [run.get("demo_summary") for run in command_runs if run.get("demo_summary")]
            rows.append((
                "Official Step 5 Demo",
                record.get("validation_scope") or "official_demo",
                "enable confirmation, low-gain hold, explicit gripper open/close, status monitoring, no COMM_LOST, safe disable",
                f"status={record.get('status')}; demo={record.get('demo_name')}; command={record.get('command')}; command_runs={len(command_runs)}; demo_summaries={json.dumps(demo_summaries, ensure_ascii=False)[:900]}",
                record.get("record_path"),
                str(record.get("status") or "missing").upper(),
            ))
            for run in command_runs:
                rows.append(self._factory_row_from_command_run("Official Demo Command", run))

        return rows

    def _factory_row_from_command_run(self, item: str, run: Dict[str, Any]) -> tuple:
        stdout = " ".join(str(run.get("stdout") or "").split())[:500]
        stderr = " ".join(str(run.get("stderr") or "").split())[:240]
        demo_summary = run.get("demo_summary") or {}
        if demo_summary:
            measured = (
                f"status={run.get('status')}; returncode={run.get('returncode')}; "
                f"enabled={demo_summary.get('enabled_count')}/7; disabled={demo_summary.get('disabled_count')}/7; "
                f"id16_special_frames={demo_summary.get('id16_special_frame_count')}; "
                f"keepalive_frames={demo_summary.get('keepalive_frames')}; "
                f"gripper_travel={demo_summary.get('gripper_travel_rad')}; "
                f"blocking={demo_summary.get('blocking_items')}; warnings={demo_summary.get('warning_items')}"
            )
        else:
            measured = f"status={run.get('status')}; returncode={run.get('returncode')}; stdout={stdout}; stderr={stderr}"
        return (
            item,
            run.get("kind") or run.get("workflow_type") or "-",
            "official command returns 0 and records stdout/stderr",
            measured,
            " ".join(str(part) for part in run.get("command") or []),
            "PASS" if run.get("status") == "passed" else str(run.get("status") or "MISSING").upper(),
        )

    def _factory_rows_from_linked_job(self, linked_job: Dict[str, Any]) -> List[tuple]:
        rows: List[tuple] = []
        artifact_value = linked_job.get("artifact_dir")
        artifact_dir = Path(artifact_value) if artifact_value else None
        job_payload = _load_json(artifact_dir / "job.json", {}) if artifact_dir and artifact_dir.exists() else {}
        metrics = job_payload.get("summary") or {}
        if not metrics and job_payload.get("candidates"):
            metrics = job_payload.get("summary") or {}
        rows.append((
            "Linked Workstation Job",
            linked_job.get("job_id"),
            "job artifacts are attached and status is passed",
            f"type={linked_job.get('job_type')}; status={linked_job.get('status')}; artifact_dir={artifact_value}",
            str(artifact_dir / "job.json") if artifact_dir else "-",
            "PASS" if linked_job.get("status") == "passed" else str(linked_job.get("status") or "INFO").upper(),
        ))
        summary = job_payload.get("summary") or (job_payload.get("metrics") or {}).get("summary") or {}
        if summary:
            rows.append((
                "Arm Scan Summary",
                linked_job.get("job_id"),
                "all expected joints present, no blocking mismatch/fault",
                json.dumps(summary, ensure_ascii=False, sort_keys=True)[:1000],
                str(artifact_dir / "job.json") if artifact_dir else "-",
                "PASS" if summary.get("passed") or summary.get("release_decision") == "PASS" else "REVIEW",
            ))
        candidates = job_payload.get("candidates") or (job_payload.get("metrics") or {}).get("joints") or []
        if not candidates:
            candidates = (job_payload.get("motors") or {}).values()
        for item in candidates:
            rows.extend(self._factory_rows_from_joint_payload(item))
        return rows

    def _factory_rows_from_joint_payload(self, item: Any) -> List[tuple]:
        if not isinstance(item, dict):
            return []
        current = item.get("current") if "current" in item else item
        target = item.get("target") or item.get("expected") or {}
        joint_name = item.get("joint_name") or target.get("joint_name") or current.get("joint_name") or "-"
        params = item.get("params") or current.get("params") or {}
        verification = item.get("verification") or {}
        status = item.get("status") or current.get("status") or {}
        matrix = item.get("consistency_matrix") or []
        issues = item.get("issues") or item.get("mismatches") or []
        result = item.get("result_label") or ("PASS" if not issues else "FAIL")
        feedback = {
            "position": status.get("position"),
            "velocity": status.get("velocity"),
            "torque": status.get("torque"),
            "t_mos": status.get("t_mos"),
            "t_rotor": status.get("t_rotor"),
            "status": status.get("status"),
            "status_code": status.get("status_code"),
            "has_error": status.get("has_error"),
            "raw_frame": status.get("last_status_frame"),
        }
        rows = [
            (
                "Motor Status Feedback",
                joint_name,
                "joint present, status parsed, no fault",
                json.dumps(feedback, ensure_ascii=False, sort_keys=True),
                f"issues={issues}",
                result,
            ),
            (
                "Motor ID Parameters",
                joint_name,
                "ESC_ID and MST_ID match profile",
                f"ESC_ID={params.get('ESC_ID') or verification.get('ESC_ID')}; MST_ID={params.get('MST_ID') or verification.get('MST_ID')}; target={target.get('target_esc_id')}/{target.get('target_mst_id')}",
                "read_param ESC_ID/MST_ID",
                "PASS" if not any(issue in issues for issue in ["missing", "esc_id_mismatch", "mst_id_mismatch"]) else "FAIL",
            ),
            (
                "Motor Control Parameters",
                joint_name,
                "CTRL_MODE=MIT, can_br=1Mbps, TIMEOUT per profile",
                f"CTRL_MODE={params.get('CTRL_MODE') or verification.get('CTRL_MODE')}; can_br={params.get('can_br') or verification.get('can_br')}; TIMEOUT={params.get('TIMEOUT') or verification.get('TIMEOUT')}",
                "read_param CTRL_MODE/TIMEOUT/can_br",
                "PASS" if not any(issue in issues for issue in ["ctrl_mode_mismatch", "can_br_mismatch", "timeout_mismatch"]) else "FAIL",
            ),
            (
                "Motor Limit / Constants",
                joint_name,
                "Gr, KT_Value, PMAX, VMAX, TMAX match profile",
                f"Gr={params.get('Gr') or verification.get('Gr')}; KT={params.get('KT_Value') or verification.get('KT_Value')}; PMAX={params.get('PMAX') or verification.get('PMAX')}; VMAX={params.get('VMAX') or verification.get('VMAX')}; TMAX={params.get('TMAX') or verification.get('TMAX')}",
                f"consistency_matrix={matrix}",
                "PASS" if not matrix and not any("mismatch" in str(issue) for issue in issues) else result,
            ),
        ]
        if item.get("link_test"):
            link_test = item["link_test"]
            rows.append((
                "Motor Link Test",
                joint_name,
                "enable/disable communication check completes without fault",
                json.dumps(link_test, ensure_ascii=False, sort_keys=True)[:800],
                "link_test",
                "PASS" if link_test.get("passed") else "FAIL",
            ))
        if item.get("micro_test"):
            micro_test = item["micro_test"]
            rows.append((
                "Motor Micro Response Test",
                joint_name,
                "small response within safe threshold and no fault",
                json.dumps(micro_test, ensure_ascii=False, sort_keys=True)[:800],
                "micro_test",
                "PASS" if micro_test.get("passed") else "FAIL",
            ))
        return rows

    def _attach_report_to_arm(self, path: Path, arm: Dict[str, Any], report_ref: Dict[str, Any]):
        report_id = report_ref.get("report_id")
        json_path = report_ref.get("json_path")
        reports = [
            item for item in arm.get("factory_reports", [])
            if item.get("report_id") != report_id and item.get("json_path") != json_path
        ]
        reports.insert(0, report_ref)
        arm["factory_reports"] = reports[:50]
        arm["updated_at"] = _now_iso()
        _atomic_json(path, arm)

    def _write_factory_report(
        self,
        subject_id: str,
        subject_type: str,
        report_type: str,
        title: str,
        summary: Dict[str, Any],
        rows: List[Iterable[Any]],
        headers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        report_id = uuid.uuid4().hex[:12]
        report_dir = FACTORY_REPORTS_DIR / _safe_name(subject_type) / _safe_name(subject_id) / report_type
        report_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{report_id}"
        json_path = report_dir / f"{base_name}.json"
        html_path = report_dir / f"{base_name}.html"
        pdf_path = report_dir / f"{base_name}.pdf"
        payload = {
            "report_id": report_id,
            "report_type": report_type,
            "title": title,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "summary": summary,
            "headers": headers or ["Parameter", "Value", "Note"],
            "rows": [list(row) for row in rows],
            "generated_at": _now_iso(),
        }
        _atomic_json(json_path, payload)
        is_acceptance_report = report_type == "factory_acceptance_report"
        if is_acceptance_report:
            html = _html_factory_acceptance_report(title, payload)
        else:
            summary_for_table = [(key, value) for key, value in summary.items() if key != "attached_report_manifest"]
            manifest_html = _html_report_manifest(summary.get("attached_report_manifest", [])) if summary.get("attached_report_manifest") is not None else ""
            html_rows = ""
            for row in payload["rows"]:
                if row and str(row[0]).strip() and all(not str(value).strip() for value in row[1:]):
                    html_rows += f"<tr class='section-row'><td colspan='{len(payload['headers'])}'>{escape(str(row[0]))}</td></tr>"
                else:
                    html_rows += "<tr>" + "".join(f"<td>{escape(str(value if value is not None else '-'))}</td>" for value in row) + "</tr>"
            html = f"""
            <!DOCTYPE html>
            <html lang="zh-CN">
            <head>
                <meta charset="utf-8">
                <title>{escape(title)}</title>
                <style>
                    @page {{ size: A4 landscape; margin: 12mm; }}
                    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; font-size: 12px; }}
                    h1 {{ margin-bottom: 4px; font-size: 22px; }}
                    h2 {{ margin: 18px 0 8px; font-size: 15px; }}
                    .meta, table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
                    td, th {{ border: 1px solid #c9d1d9; padding: 5px 6px; text-align: left; vertical-align: top; }}
                    th {{ background: #eef3f8; font-weight: 700; }}
                    .muted {{ color: #637083; }}
                    .manifest-section {{ margin-top: 24px; page-break-inside: avoid; }}
                    .section-row td, .section-row {{ background: #dbeafe; font-weight: 700; color: #1e3a8a; }}
                    tbody tr {{ page-break-inside: avoid; }}
                </style>
            </head>
            <body>
                <h1>{escape(title)}</h1>
                <div class="muted">Report ID: {escape(report_id)} · Generated: {escape(payload["generated_at"])}</div>
                <table class="meta">
                    <tbody>{_html_table(summary_for_table)}</tbody>
                </table>
                {manifest_html}
                <table>
                    <thead><tr>{''.join(f'<th>{escape(str(header))}</th>' for header in payload["headers"])}</tr></thead>
                    <tbody>{html_rows}</tbody>
                </table>
            </body>
            </html>
            """
        _atomic_text(html_path, html)
        if not (is_acceptance_report and _write_pdf_from_html(html_path, pdf_path)):
            _write_simple_pdf(pdf_path, title, payload)
        report_ref = {
            "report_id": report_id,
            "report_type": report_type,
            "title": title,
            "json_path": str(json_path),
            "html_path": str(html_path),
            "pdf_path": str(pdf_path),
            "generated_at": payload["generated_at"],
        }
        return {"report": payload, "report_ref": report_ref}

    def _write_factory_evidence(self, payload: Dict[str, Any], arm_cn: Optional[str], category: str) -> Dict[str, Any]:
        subject = _safe_name(arm_cn or "unbound")
        evidence_dir = FACTORY_EVIDENCE_DIR / subject / _safe_name(category)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{payload['evidence_id']}"
        json_path = evidence_dir / f"{base_name}.json"
        log_path = None
        if payload.get("evidence_type") == "candump_trace":
            log_path = evidence_dir / f"{base_name}.log"
            _atomic_text(log_path, payload.get("stdout", ""))
        _atomic_json(json_path, payload)
        return {
            "evidence_id": payload["evidence_id"],
            "evidence_type": payload["evidence_type"],
            "status": payload.get("status"),
            "interface": payload.get("interface"),
            "arm_cn": arm_cn,
            "job_id": payload.get("job_id"),
            "json_path": str(json_path),
            "log_path": str(log_path) if log_path else None,
            "captured_at": payload.get("captured_at"),
        }

    def _linked_job_evidence(self, linked_job: Dict[str, Any]) -> Dict[str, Any]:
        artifact_value = linked_job.get("artifact_dir")
        artifact_dir = Path(artifact_value) if artifact_value else None
        has_artifacts = bool(artifact_dir and artifact_dir.exists())
        job_payload = _load_json(artifact_dir / "job.json", {}) if has_artifacts else {}
        issues_payload = _load_json(artifact_dir / "issues.json", {}) if has_artifacts else {}
        issue_summary = issues_payload.get("summary", {})
        return {
            "job_id": linked_job.get("job_id"),
            "job_type": linked_job.get("job_type"),
            "status": linked_job.get("status") or job_payload.get("job", {}).get("status"),
            "product_version": self._linked_job_product_version(linked_job, job_payload),
            "artifact_dir": linked_job.get("artifact_dir"),
            "has_artifacts": has_artifacts,
            "has_blocking_issues": bool(issue_summary.get("has_blocking")),
            "issue_summary": issue_summary,
        }

    def _linked_job_product_version(self, linked_job: Dict[str, Any], job_payload: Dict[str, Any]) -> Optional[str]:
        """The product this job was run for, or None when it predates the registry."""
        stated = linked_job.get("product_version") or job_payload.get("job", {}).get("product_line")
        return str(stated) if stated else None

    def _product_version_conflicts(self, arm: Dict[str, Any], linked_job_evidence: List[Dict[str, Any]]) -> List[str]:
        """Evidence recorded under a different product version must never be mixed in.

        A 1.0 job proves nothing about a 2.0 arm: different bus mode, different gripper
        travel, different acceptance thresholds. Only a *stated* version that disagrees
        is a conflict - evidence from before the registry existed states nothing, and
        holding those arms would be rewriting history, not catching a mistake.
        """
        arm_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
        conflicts = []
        for item in linked_job_evidence:
            stated = item.get("product_version")
            if stated and stated != arm_version:
                conflicts.append(f"任务 {item.get('job_id')} 记录为 {stated}，与整机 {arm_version} 不一致")
        return conflicts

    def _linked_jobs_have_raw_status_frames(self, linked_jobs: List[Dict[str, Any]]) -> bool:
        for linked_job in linked_jobs:
            artifact_value = linked_job.get("artifact_dir")
            artifact_dir = Path(artifact_value) if artifact_value else None
            if not artifact_dir or not artifact_dir.exists():
                continue
            job_payload = _load_json(artifact_dir / "job.json", {})
            candidates = job_payload.get("candidates") or (job_payload.get("metrics") or {}).get("joints") or []
            if not candidates:
                candidates = (job_payload.get("motors") or {}).values()
            if any(((item.get("status") or {}).get("last_status_frame")) for item in candidates if isinstance(item, dict)):
                return True
        return False

    def bind_motor_identity(
        self,
        motor_sn: str,
        motor_type: str,
        installed_joint: Optional[str] = None,
        arm_cn: Optional[str] = None,
        esc_id: Optional[int] = None,
        mst_id: Optional[int] = None,
        vendor: str = "DaMiao",
        hw_revision: Optional[str] = None,
        fw_version: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            motor_sn = motor_sn.strip()
            if not motor_sn:
                raise ValueError("motor_sn is required")
            validation = self.validate_factory_motor_sn(motor_sn)
            if not validation["valid"]:
                raise ValueError(validation["message"])
            FACTORY_MOTORS_DIR.mkdir(parents=True, exist_ok=True)
            path = FACTORY_MOTORS_DIR / f"{_safe_name(motor_sn)}.json"
            existing = _load_json(path, {})
            record = {
                "motor_sn": motor_sn,
                "motor_type": motor_type,
                "vendor": vendor,
                "hw_revision": hw_revision or existing.get("hw_revision"),
                "fw_version": fw_version or existing.get("fw_version"),
                "received_date": existing.get("received_date"),
                "installed_joint": installed_joint or existing.get("installed_joint"),
                "arm_cn": arm_cn or existing.get("arm_cn"),
                "esc_id": int(esc_id) if esc_id is not None else existing.get("esc_id"),
                "mst_id": int(mst_id) if mst_id is not None else existing.get("mst_id"),
                "status": existing.get("status", "registered"),
                "notes": notes or existing.get("notes"),
                "created_at": existing.get("created_at") or _now_iso(),
                "updated_at": _now_iso(),
                "linked_jobs": existing.get("linked_jobs", []),
                "factory_reports": existing.get("factory_reports", []),
            }
            _atomic_json(path, record)
            if arm_cn and installed_joint:
                self.assign_joint_motor(
                    arm_cn=arm_cn,
                    joint_name=installed_joint,
                    motor_sn=motor_sn,
                    esc_id=record.get("esc_id"),
                    mst_id=record.get("mst_id"),
                    motor_type=record["motor_type"],
                    persist_motor=False,
                )
            return record

    def assign_joint_motor(
        self,
        arm_cn: str,
        joint_name: str,
        motor_sn: str,
        esc_id: Optional[int] = None,
        mst_id: Optional[int] = None,
        motor_type: Optional[str] = None,
        persist_motor: bool = True,
    ) -> Dict[str, Any]:
        with self._lock:
            arm_path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
            arm = _load_json(arm_path, {})
            if not arm:
                arm = self.bind_arm_identity(arm_cn=arm_cn)
            joint_bindings = dict(arm.get("joint_bindings", {}))
            joint_bindings[joint_name] = {
                "motor_sn": motor_sn,
                "esc_id": int(esc_id) if esc_id is not None else None,
                "mst_id": int(mst_id) if mst_id is not None else None,
                "motor_type": motor_type,
                "updated_at": _now_iso(),
            }
            arm["joint_bindings"] = joint_bindings
            arm["updated_at"] = _now_iso()
            _atomic_json(arm_path, arm)

            if persist_motor:
                motor = self.bind_motor_identity(
                    motor_sn=motor_sn,
                    motor_type=motor_type or "UNKNOWN",
                    installed_joint=joint_name,
                    arm_cn=arm_cn,
                    esc_id=esc_id,
                    mst_id=mst_id,
                )
            else:
                motor_path = FACTORY_MOTORS_DIR / f"{_safe_name(motor_sn)}.json"
                motor = _load_json(motor_path, {})
                if motor:
                    motor["installed_joint"] = joint_name
                    motor["arm_cn"] = arm_cn
                    if esc_id is not None:
                        motor["esc_id"] = int(esc_id)
                    if mst_id is not None:
                        motor["mst_id"] = int(mst_id)
                    if motor_type:
                        motor["motor_type"] = motor_type
                    motor["updated_at"] = _now_iso()
                    _atomic_json(motor_path, motor)
            return {"arm": arm, "motor": motor}

    def attach_job_to_motor(self, motor_sn: str, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            path = FACTORY_MOTORS_DIR / f"{_safe_name(motor_sn)}.json"
            record = _load_json(path, {})
            if not record:
                raise KeyError(f"motor_sn {motor_sn} not found")
            linked_jobs = list(record.get("linked_jobs", []))
            entry = self._job_reference(job)
            linked_jobs = [item for item in linked_jobs if item.get("job_id") != job.job_id]
            linked_jobs.insert(0, entry)
            record["linked_jobs"] = linked_jobs[:20]
            record["updated_at"] = _now_iso()
            _atomic_json(path, record)
            return record

    def attach_job_to_arm(self, arm_cn: str, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
            record = _load_json(path, {})
            if not record:
                raise KeyError(f"arm_cn {arm_cn} not found")
            linked_jobs = list(record.get("linked_jobs", []))
            entry = self._job_reference(job)
            linked_jobs = [item for item in linked_jobs if item.get("job_id") != job.job_id]
            linked_jobs.insert(0, entry)
            record["linked_jobs"] = linked_jobs[:50]
            record["updated_at"] = _now_iso()
            _atomic_json(path, record)
            return record

    def build_factory_bundle(self, arm_cn: str) -> Dict[str, Any]:
        with self._lock:
            arm_path = FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json"
            arm = _load_json(arm_path, {})
            if not arm:
                raise KeyError(f"arm_cn {arm_cn} not found")

            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            bundle_dir = FACTORY_BUNDLES_DIR / f"{_safe_name(arm_cn)}_{stamp}"
            bundle_dir.mkdir(parents=True, exist_ok=True)

            _atomic_json(bundle_dir / "arm_identity.json", arm)
            _atomic_json(bundle_dir / "zero_calibration_records.json", arm.get("zero_calibration_records", []))
            _atomic_json(bundle_dir / "demo_validation_records.json", arm.get("demo_validation_records", []))
            motor_reports_dir = bundle_dir / "motor_records"
            motor_reports_dir.mkdir(parents=True, exist_ok=True)
            for joint_name, binding in sorted((arm.get("joint_bindings") or {}).items()):
                motor_sn = binding.get("motor_sn")
                if not motor_sn:
                    continue
                motor_path = FACTORY_MOTORS_DIR / f"{_safe_name(motor_sn)}.json"
                motor = _load_json(motor_path, {})
                if motor:
                    _atomic_json(motor_reports_dir / f"{_safe_name(joint_name)}_{_safe_name(motor_sn)}.json", motor)

            arm_record_source_dir = _arm_record_dir(arm_cn)
            if arm_record_source_dir.exists():
                bundle_record_dir = bundle_dir / "factory_records"
                shutil.copytree(arm_record_source_dir, bundle_record_dir, dirs_exist_ok=True)

            factory_reports_dir = bundle_dir / "factory_reports"
            factory_reports_dir.mkdir(parents=True, exist_ok=True)
            for report_ref in arm.get("factory_reports", []):
                for path_key in ("json_path", "html_path", "pdf_path"):
                    src = Path(report_ref.get(path_key, ""))
                    if src.exists():
                        shutil.copy2(src, factory_reports_dir / src.name)
            for binding in (arm.get("joint_bindings") or {}).values():
                motor_sn = binding.get("motor_sn")
                if not motor_sn:
                    continue
                motor = _load_json(FACTORY_MOTORS_DIR / f"{_safe_name(motor_sn)}.json", {})
                for report_ref in motor.get("factory_reports", []):
                    for path_key in ("json_path", "html_path", "pdf_path"):
                        src = Path(report_ref.get(path_key, ""))
                        if src.exists():
                            shutil.copy2(src, factory_reports_dir / f"{_safe_name(motor_sn)}_{src.name}")

            evidence_dir = bundle_dir / "factory_evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            for evidence_ref in arm.get("evidence_records", []):
                for path_key in ("json_path", "log_path"):
                    src = Path(evidence_ref.get(path_key) or "")
                    if src.exists():
                        shutil.copy2(src, evidence_dir / src.name)

            linked_jobs_dir = bundle_dir / "linked_jobs"
            linked_jobs_dir.mkdir(parents=True, exist_ok=True)
            linked_job_entries = {item.get("job_id"): item for item in arm.get("linked_jobs", []) if item.get("job_id")}
            for record in arm.get("zero_calibration_records", []) + arm.get("demo_validation_records", []):
                linked = record.get("linked_job") or {}
                job_id = linked.get("job_id")
                if job_id and job_id not in linked_job_entries:
                    linked_job_entries[job_id] = linked
            for item in linked_job_entries.values():
                artifact_dir = item.get("artifact_dir")
                if not artifact_dir:
                    continue
                source = Path(artifact_dir)
                if not source.exists():
                    continue
                target = linked_jobs_dir / f"{item.get('job_id', 'job')}"
                target.mkdir(parents=True, exist_ok=True)
                for name in ["job.json", "issues.json", "events.jsonl", "report.html"]:
                    src = source / name
                    if src.exists():
                        shutil.copy2(src, target / name)

            summary = {
                "arm_cn": arm_cn,
                "generated_at": _now_iso(),
                "joint_count": len(arm.get("joint_bindings", {})),
                "linked_job_count": len(linked_job_entries),
                "zero_calibration_count": len(arm.get("zero_calibration_records", [])),
                "demo_validation_count": len(arm.get("demo_validation_records", [])),
                "factory_report_count": len(list(factory_reports_dir.glob("*"))),
                "factory_evidence_count": len(list(evidence_dir.glob("*"))),
                "bundle_dir": str(bundle_dir),
            }
            _atomic_json(bundle_dir / "bundle_summary.json", summary)

            archive_base = FACTORY_BUNDLES_DIR / f"{_safe_name(arm_cn)}_{stamp}"
            archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=bundle_dir)

            bundle_history = list(arm.get("bundle_history", []))
            bundle_history.insert(
                0,
                {
                    "generated_at": _now_iso(),
                    "bundle_dir": str(bundle_dir),
                    "archive_path": archive_path,
                },
            )
            arm["bundle_history"] = bundle_history[:20]
            arm["updated_at"] = _now_iso()
            _atomic_json(arm_path, arm)
            return {
                "arm_cn": arm_cn,
                "bundle_dir": str(bundle_dir),
                "archive_path": archive_path,
                "summary": summary,
            }

    def probe_joint_params(
        self,
        session_id: str,
        joint_name: str,
        profile_id: str = "openarm_v1",
        timeout_per_param: float = 0.4,
        force_inventory: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            profile_joint = dict(self.profile_manager.get_joint(profile_id, joint_name))
            expected_esc_id = int(profile_joint["target_esc_id"])
            expected_mst_id = int(profile_joint["target_mst_id"])

            inventory_payload = session.last_inventory.get("payload", {})
            cached_profile_id = session.last_inventory.get("profile_id")
            inventory_items = inventory_payload.get("inventory", [])
            if force_inventory or not inventory_items or cached_profile_id not in {None, profile_id}:
                inventory_payload = self.line_inventory(session_id, profile_id)
                inventory_items = inventory_payload.get("inventory", [])

            discovered = next(
                (item for item in inventory_items if int(item.get("detected_esc_id", -1)) == expected_esc_id),
                None,
            )

            motor = Motor(
                _motor_type_from_name(profile_joint["motor_type"]),
                expected_esc_id,
                int(discovered.get("detected_mst_id") or expected_mst_id) if discovered else expected_mst_id,
            )
            params = {
                "ESC_ID": discovered.get("params", {}).get("ESC_ID") if discovered else None,
                "MST_ID": discovered.get("params", {}).get("MST_ID") if discovered else None,
            }
            param_results = []
            probe_rids = [
                DM_variable.CTRL_MODE,
                DM_variable.TIMEOUT,
                DM_variable.can_br,
                DM_variable.Gr,
                DM_variable.KT_Value,
                DM_variable.PMAX,
                DM_variable.VMAX,
                DM_variable.TMAX,
            ]
            effective_timeout = max(0.05, float(timeout_per_param))

            if discovered:
                for rid in probe_rids:
                    started = time.perf_counter()
                    try:
                        value = session.driver.read_motor_param(motor, rid, timeout=effective_timeout)
                        ok = value is not None
                    except Exception as error:
                        value = None
                        ok = False
                        param_results.append(
                            {
                                "field": rid.name,
                                "ok": False,
                                "value": None,
                                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                                "error": str(error),
                            }
                        )
                        continue

                    params[rid.name] = value
                    param_results.append(
                        {
                            "field": rid.name,
                            "ok": ok,
                            "value": value,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                        }
                    )

            status = self._refresh_and_snapshot(session, motor, ignore_errors=True) if discovered else motor.snapshot()
            failed_fields = [item["field"] for item in param_results if not item["ok"]]
            issues = []
            if not discovered:
                issues.append("missing")
            if failed_fields:
                issues.append("param_read_failed")
            if discovered and params.get("MST_ID") is not None and int(params["MST_ID"]) != expected_mst_id:
                issues.append("mst_id_mismatch")
            if discovered and params.get("can_br") is not None and not _can_br_matches(params["can_br"], profile_joint["target_can_br"]):
                issues.append("can_br_mismatch")
            expected_ctrl_mode = int(_control_from_value(profile_joint.get("expected_ctrl_mode", profile_joint.get("target_ctrl_mode", "MIT"))))
            if discovered and params.get("CTRL_MODE") is not None and int(params["CTRL_MODE"]) != expected_ctrl_mode:
                issues.append("ctrl_mode_mismatch")
            if status.get("has_error"):
                issues.append("motor_error")
            elif _status_read_anomaly(status):
                issues.append("status_read_anomaly")

            payload = {
                "joint_name": joint_name,
                "profile_id": profile_id,
                "expected": profile_joint,
                "present": bool(discovered),
                "inventory_candidate": discovered,
                "params": params,
                "param_results": param_results,
                "failed_fields": failed_fields,
                "issues": issues,
                "status": status,
                "passed": bool(discovered) and not issues,
                "result_label": _motor_result_label(bool(discovered), issues),
            }
            return payload

    def joint_link_test(
        self,
        session_id: str,
        joint_name: str,
        profile_id: str = "openarm_v1",
        force_inventory: bool = False,
        allow_enable: bool = False,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            resolved = self._resolve_joint_for_runtime(
                session,
                joint_name=joint_name,
                profile_id=profile_id,
                force_inventory=force_inventory,
            )
            motor = resolved["motor"]
            if not resolved["present"]:
                return self._record_joint_runtime_result(job_id, "link_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": False,
                    "passed": False,
                    "issues": ["missing"],
                    "pre_status": motor.snapshot(),
                    "after_enable": None,
                    "after_disable": None,
                })

            pre_status = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            if not allow_enable:
                issues = []
                if pre_status.get("has_error"):
                    issues.append("motor_error")
                elif _status_read_anomaly(pre_status):
                    issues.append("status_read_anomaly")
                passed = not issues
                return self._record_joint_runtime_result(job_id, "link_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": True,
                    "passed": passed,
                    "issues": issues,
                    "mode": "read_only_status_check",
                    "motion_command_sent": False,
                    "pre_status": pre_status,
                    "after_enable": None,
                    "after_disable": pre_status,
                    "status": pre_status,
                })

            try:
                enable_ok = bool(session.driver.enable(motor))
                after_enable = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                disable_ok = bool(session.driver.disable(motor))
                after_disable = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            except Exception as error:
                try:
                    session.driver.disable(motor)
                except Exception:
                    pass
                return self._record_joint_runtime_result(job_id, "link_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": True,
                    "passed": False,
                    "issues": ["link_test_failed"],
                    "error": str(error),
                    "pre_status": pre_status,
                    "after_enable": None,
                    "after_disable": None,
                })

            issues = []
            if not enable_ok:
                issues.append("enable_failed")
            if not disable_ok:
                issues.append("disable_failed")
            if after_enable.get("has_error"):
                issues.append("motor_error")
            if after_disable.get("has_error"):
                issues.append("motor_error")
            passed = not issues
            return self._record_joint_runtime_result(job_id, "link_test", {
                "joint_name": joint_name,
                "profile_id": profile_id,
                "present": True,
                "passed": passed,
                "issues": issues,
                "pre_status": pre_status,
                "after_enable": after_enable,
                "after_disable": after_disable,
            })

    def joint_micro_response_test(
        self,
        session_id: str,
        joint_name: str,
        profile_id: str = "openarm_v1",
        force_inventory: bool = False,
        q_offset: float = 0.02,
        kp: float = 6.0,
        kd: float = 0.12,
        dwell_ms: int = 120,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            resolved = self._resolve_joint_for_runtime(
                session,
                joint_name=joint_name,
                profile_id=profile_id,
                force_inventory=force_inventory,
            )
            motor = resolved["motor"]
            if not resolved["present"]:
                return self._record_joint_runtime_result(job_id, "micro_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": False,
                    "passed": False,
                    "issues": ["missing"],
                    "measurements": {},
                })

            start = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            if start.get("has_error"):
                return self._record_joint_runtime_result(job_id, "micro_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": True,
                    "passed": False,
                    "issues": ["motor_error"],
                    "measurements": {"start": start},
                })
            if float(start.get("t_mos", 0.0)) >= TEMP_LIMITS["mos"]:
                return self._record_joint_runtime_result(job_id, "micro_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": True,
                    "passed": False,
                    "issues": ["mos_overtemp"],
                    "measurements": {"start": start},
                })
            if float(start.get("t_rotor", 0.0)) >= TEMP_LIMITS["rotor"]:
                return self._record_joint_runtime_result(job_id, "micro_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": True,
                    "passed": False,
                    "issues": ["rotor_overtemp"],
                    "measurements": {"start": start},
                })

            dwell_s = max(0.05, min(float(dwell_ms) / 1000.0, 0.4))
            offset = max(0.005, min(abs(float(q_offset)), 0.03))
            start_q = float(start["position"])
            target_q = start_q + offset

            enable_ok = False
            try:
                enable_ok = bool(session.driver.enable(motor))
                deadline = time.time() + dwell_s
                while time.time() < deadline:
                    if hasattr(session.driver, "controlMIT_fast"):
                        session.driver.controlMIT_fast(motor, kp=kp, kd=kd, q=target_q, dq=0.0, tau=0.0)
                    else:
                        session.driver.controlMIT(motor, kp=kp, kd=kd, q=target_q, dq=0.0, tau=0.0)
                    if hasattr(session.driver, "_drain"):
                        session.driver._drain(0.002)
                    time.sleep(0.005)
                peak = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                deadline = time.time() + dwell_s
                while time.time() < deadline:
                    if hasattr(session.driver, "controlMIT_fast"):
                        session.driver.controlMIT_fast(motor, kp=kp, kd=kd, q=start_q, dq=0.0, tau=0.0)
                    else:
                        session.driver.controlMIT(motor, kp=kp, kd=kd, q=start_q, dq=0.0, tau=0.0)
                    if hasattr(session.driver, "_drain"):
                        session.driver._drain(0.002)
                    time.sleep(0.005)
                returned = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            except Exception as error:
                try:
                    session.driver.disable(motor)
                except Exception:
                    pass
                return self._record_joint_runtime_result(job_id, "micro_test", {
                    "joint_name": joint_name,
                    "profile_id": profile_id,
                    "present": True,
                    "passed": False,
                    "issues": ["micro_response_failed"],
                    "error": str(error),
                    "measurements": {"start": start},
                })
            finally:
                try:
                    session.driver.disable(motor)
                except Exception:
                    pass

            final = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            peak_delta = abs(float(peak["position"]) - start_q)
            return_delta = abs(float(returned["position"]) - start_q)
            final_delta = abs(float(final["position"]) - start_q)

            issues = []
            if not enable_ok:
                issues.append("enable_failed")
            if peak.get("has_error") or returned.get("has_error") or final.get("has_error"):
                issues.append("motor_error")
            if peak_delta < 0.003:
                issues.append("response_too_small")
            if peak_delta > 0.08:
                issues.append("response_too_large")
            if final_delta > 0.05:
                issues.append("return_not_settled")
            if float(final.get("t_mos", 0.0)) >= TEMP_LIMITS["mos"]:
                issues.append("mos_overtemp")
            if float(final.get("t_rotor", 0.0)) >= TEMP_LIMITS["rotor"]:
                issues.append("rotor_overtemp")

            return self._record_joint_runtime_result(job_id, "micro_test", {
                "joint_name": joint_name,
                "profile_id": profile_id,
                "present": True,
                "passed": not issues,
                "issues": issues,
                "measurements": {
                    "start": start,
                    "peak": peak,
                    "returned": returned,
                    "final": final,
                    "target_q": target_q,
                    "start_q": start_q,
                    "peak_delta": peak_delta,
                    "return_delta": return_delta,
                    "final_delta": final_delta,
                    "q_offset": offset,
                    "dwell_ms": int(round(dwell_s * 1000.0)),
                },
            })

    def arm_status_check(
        self,
        session_id: str,
        profile_id: str = "openarm_right_arm_v1",
        sample_count: int = 1,
        sample_delay_ms: int = 80,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            profile = self.profile_manager.get_profile(profile_id)
            samples_requested = max(1, min(int(sample_count), 5))
            sample_delay_s = max(0.02, min(int(sample_delay_ms) / 1000.0, 0.5))
            results = []
            for joint in profile["joints"]:
                motor = Motor(
                    _motor_type_from_name(joint["motor_type"]),
                    int(joint["target_esc_id"]),
                    int(joint["target_mst_id"]),
                )
                item = {
                    "joint_name": joint["joint_name"],
                    "esc_id": motor.SlaveID,
                    "mst_id": motor.MasterID,
                    "expected_timeout": int(joint["target_timeout"]),
                    "present": False,
                    "timeout": None,
                    "status": None,
                    "params": {},
                    "samples": [],
                    "issues": [],
                    "metadata_notes": [],
                    "passed": False,
                }
                try:
                    session.driver.ensure_motor(motor)
                    params = session.driver.read_params(motor, HEALTH_REPORT_RIDS, timeout=0.5)
                    timeout_value = params.get("TIMEOUT")
                    item["present"] = timeout_value is not None
                    item["timeout"] = timeout_value
                    item["params"] = params
                    for sample_index in range(samples_requested):
                        snapshot = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                        sample = {
                            "sample_index": sample_index + 1,
                            "sampled_at": _now_iso(),
                            "status": snapshot,
                        }
                        item["samples"].append(sample)
                        item["status"] = snapshot
                        if sample_index < samples_requested - 1:
                            time.sleep(sample_delay_s)
                    if not item["present"]:
                        item["issues"].append("missing")
                    else:
                        actual_esc_id = params.get("ESC_ID")
                        actual_mst_id = params.get("MST_ID")
                        actual_ctrl_mode = params.get("CTRL_MODE")
                        actual_can_br = params.get("can_br")
                        expected_ctrl_mode = int(
                            _control_from_value(
                                joint.get("expected_ctrl_mode", joint.get("target_ctrl_mode", "MIT"))
                            )
                        )
                        if actual_esc_id is not None and int(actual_esc_id) != int(joint["target_esc_id"]):
                            item["issues"].append("esc_id_mismatch")
                        if actual_mst_id is not None and int(actual_mst_id) != int(joint["target_mst_id"]):
                            item["issues"].append("mst_id_mismatch")
                        if actual_ctrl_mode is not None and int(actual_ctrl_mode) != expected_ctrl_mode:
                            item["issues"].append("ctrl_mode_mismatch")
                        if timeout_value is not None and int(timeout_value) != int(joint["target_timeout"]):
                            item["issues"].append("timeout_mismatch")
                        if actual_can_br is not None and not _can_br_matches(actual_can_br, joint["target_can_br"]):
                            item["issues"].append("can_br_mismatch")
                    if item["status"].get("has_error"):
                        item["issues"].append("motor_error")
                    elif _status_read_anomaly(item["status"]):
                        item["issues"].append("status_read_anomaly")
                    item["passed"] = item["present"] and not item["issues"]
                except Exception as error:
                    item["issues"].append("status_check_failed")
                    item["error"] = str(error)
                results.append(item)
            return {
                "profile_id": profile_id,
                "motion_command_sent": False,
                "sample_count": samples_requested,
                "sample_delay_ms": int(round(sample_delay_s * 1000)),
                "summary": {
                    "total_expected": len(profile["joints"]),
                    "total_present": sum(1 for item in results if item["present"]),
                    "passed": sum(1 for item in results if item["passed"]),
                    "failed": sum(1 for item in results if not item["passed"]),
                },
                "results": results,
                "ok": all(item["passed"] for item in results),
            }

    def arm_timeout_standardization(
        self,
        session_id: str,
        profile_id: str = "openarm_right_arm_v1",
        save_flash: bool = True,
        confirmed: bool = False,
        arm_cn: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not confirmed:
            return {
                "ok": False,
                "status": "blocked",
                "missing_confirmations": [
                    {
                        "key": "confirmed",
                        "label": "确认已完成静态扫描、当前为整臂验收阶段且急停/断电可用",
                    }
                ],
                "results": [],
            }

        def _as_int(value: Any) -> Optional[int]:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        with self._lock:
            session = self._session(session_id)
            profile = self.profile_manager.get_profile(profile_id)
            timeout_targets = {}
            for joint in profile["joints"]:
                target_timeout = _as_int(joint.get("target_timeout"))
                if target_timeout is None or target_timeout <= 0:
                    raise ValueError(
                        f"profile {profile_id} has invalid target_timeout for {joint['joint_name']}"
                    )
                timeout_targets[joint["joint_name"]] = target_timeout

            results = []
            for joint in profile["joints"]:
                target_timeout = timeout_targets[joint["joint_name"]]
                motor = Motor(
                    _motor_type_from_name(joint["motor_type"]),
                    int(joint["target_esc_id"]),
                    int(joint["target_mst_id"]),
                )
                item = {
                    "joint_name": joint["joint_name"],
                    "esc_id": motor.SlaveID,
                    "mst_id": motor.MasterID,
                    "target_timeout": target_timeout,
                    "before": None,
                    "after_write": None,
                    "after_save": None,
                    "status_before": None,
                    "status_after": None,
                    "disable_ok": False,
                    "write_ok": False,
                    "save_ok": None,
                    "issues": [],
                    "ok": False,
                    "passed": False,
                }
                try:
                    session.driver.ensure_motor(motor)
                    item["status_before"] = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                    if item["status_before"].get("has_error"):
                        item["issues"].append("motor_error_before_write")
                    if item["status_before"].get("is_enabled"):
                        item["disable_ok"] = bool(session.driver.disable(motor))
                    else:
                        item["disable_ok"] = True
                    if not item["disable_ok"]:
                        item["issues"].append("disable_failed")

                    item["before"] = _as_int(session.driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.8))
                    if not item["issues"]:
                        item["write_ok"] = bool(
                            session.driver.change_motor_param(motor, DM_variable.TIMEOUT, target_timeout)
                        )
                        item["after_write"] = _as_int(
                            session.driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.8)
                        )
                        if not item["write_ok"] or item["after_write"] != target_timeout:
                            item["issues"].append("timeout_write_verify_failed")
                        elif save_flash:
                            item["save_ok"] = bool(session.driver.save_motor_param(motor))
                            item["after_save"] = _as_int(
                                session.driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.8)
                            )
                            if not item["save_ok"] or item["after_save"] != target_timeout:
                                item["issues"].append("timeout_save_verify_failed")
                        else:
                            item["save_ok"] = None
                            item["after_save"] = item["after_write"]
                    item["status_after"] = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                    if item["status_after"].get("is_enabled"):
                        item["issues"].append("not_disabled_after_write")
                    if item["status_after"].get("has_error"):
                        item["issues"].append("motor_error_after_write")
                    item["issues"] = list(dict.fromkeys(item["issues"]))
                    item["ok"] = not item["issues"] and item["after_save"] == target_timeout
                    item["passed"] = item["ok"]
                except Exception as error:
                    item["issues"].append("timeout_standardization_failed")
                    item["error"] = str(error)
                    try:
                        session.driver.disable(motor)
                    except Exception:
                        pass
                results.append(item)
            ok = all(item["ok"] for item in results) and len(results) == len(profile["joints"])
            payload = {
                "profile_id": profile_id,
                "arm_side": profile.get("arm_side"),
                "timeout_standardization": True,
                "timeout_source": "profile_per_joint",
                "timeout_targets": timeout_targets,
                "save_flash": bool(save_flash),
                "motion_command_sent": False,
                "status": "passed" if ok else "failed",
                "summary": {
                    "total_expected": len(profile["joints"]),
                    "passed": sum(1 for item in results if item["ok"]),
                    "failed": sum(1 for item in results if not item["ok"]),
                    "all_disabled_after_write": all(
                        not (item.get("status_after") or {}).get("is_enabled")
                        for item in results
                    ),
                },
                "results": results,
                "ok": ok,
            }
            self._record_arm_step_run(arm_cn, "arm_timeout_standardization", payload)
            return payload

    def arm_safe_enable_check(
        self,
        session_id: str,
        profile_id: str = "openarm_right_arm_v1",
        hold_ms: int = 300,
        arm_cn: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            profile = self.profile_manager.get_profile(profile_id)
            hold_s = max(0.05, min(float(hold_ms) / 1000.0, 0.4))
            if session.transport == "socketcan":
                arm_side = profile.get("arm_side") or ("left_arm" if "left" in profile_id else "right_arm")
                python_bin = ROOT_DIR / ".venv" / "bin" / "python"
                command = [
                    str(python_bin if python_bin.exists() else "python3"),
                    "-u",
                    str(ROOT_DIR / "tools" / "openarm_official_enable_check.py"),
                    "--canport",
                    str(session.connection.get("channel", "can0")),
                    "--arm-side",
                    str(arm_side),
                    "--hold-ms",
                    str(max(50, int(hold_ms))),
                ]
                completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=90)
                summary = _parse_official_enable_stdout(completed.stdout, len(profile["joints"]))
                results = []
                for joint in profile["joints"]:
                    recv_id = int(joint["target_mst_id"])
                    enable_match = re.search(rf"ENABLE recv_id=0x{recv_id:X} status=(.*)", completed.stdout)
                    disable_match = re.search(rf"DISABLE recv_id=0x{recv_id:X} status=(.*)", completed.stdout)
                    issues = []
                    enable_status = enable_match.group(1) if enable_match else ""
                    disable_status = disable_match.group(1) if disable_match else ""
                    id16_special = (
                        int(joint["target_esc_id"]) == 16
                        and "'status': 'STATE_FRAME_ID16_UNTAGGED'" in enable_status
                        and "'status': 'STATE_FRAME_ID16_UNTAGGED'" in disable_status
                    )
                    if not enable_match:
                        issues.append("enable_state_not_observed")
                    elif "'status': 'ENABLED'" not in enable_status and not id16_special:
                        issues.append("enable_state_not_confirmed")
                    if not disable_match:
                        issues.append("disable_state_not_observed")
                    elif "'status': 'DISABLED'" not in disable_status and not id16_special:
                        issues.append("disable_state_not_confirmed")
                    if "COMM_LOST" in enable_status:
                        issues.append("after_enable_motor_error")
                    if "COMM_LOST" in disable_status:
                        issues.append("after_disable_motor_error")
                    results.append(
                        {
                            "joint_name": joint["joint_name"],
                            "esc_id": int(joint["target_esc_id"]),
                            "mst_id": recv_id,
                            "present": not issues,
                            "pre_status": None,
                            "after_enable": enable_status or None,
                            "after_disable": disable_status or None,
                            "enable_ok": bool(enable_match and ("'status': 'ENABLED'" in enable_status or id16_special)),
                            "disable_ok": bool(disable_match and ("'status': 'DISABLED'" in disable_status or id16_special)),
                            "id16_special_frame": id16_special,
                            "keepalive_mode": "official_openarm_can_enable_all",
                            "keepalive_period_ms": None,
                            "keepalive_frames_sent": summary.get("keepalive_frames"),
                            "aborted": False,
                            "issues": issues,
                            "passed": not issues,
                        }
                    )
                payload = {
                    "profile_id": profile_id,
                    "arm_side": profile.get("arm_side"),
                    "hold_ms": int(hold_ms),
                    "motion_command_sent": False,
                    "control_keepalive_sent": True,
                    "official_command": command,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-12000:],
                    "stderr": completed.stderr[-4000:],
                    "aborted": False,
                    "abort_reason": None if summary.get("passed") else "official_enable_check_failed",
                    "summary": {
                        "total_expected": len(profile["joints"]),
                        "total_present": sum(1 for item in results if item["passed"]),
                        "passed": sum(1 for item in results if item["passed"]),
                        "failed": sum(1 for item in results if not item["passed"]),
                        "all_disabled_after_check": all(item["disable_ok"] for item in results),
                        **summary,
                    },
                    "results": results,
                    "ok": completed.returncode == 0 and summary.get("passed"),
                }
                self._record_arm_step_run(arm_cn, "arm_safe_enable_check", payload)
                return payload
            results = []
            motors: list[tuple[dict[str, Any], Motor, dict[str, Any]]] = []
            for joint in profile["joints"]:
                motor = Motor(
                    _motor_type_from_name(joint["motor_type"]),
                    int(joint["target_esc_id"]),
                    int(joint["target_mst_id"]),
                )
                item = {
                    "joint_name": joint["joint_name"],
                    "esc_id": motor.SlaveID,
                    "mst_id": motor.MasterID,
                    "present": False,
                    "pre_status": None,
                    "after_enable": None,
                    "after_disable": None,
                    "enable_ok": False,
                    "disable_ok": False,
                    "keepalive_mode": "official_low_gain_current_position",
                    "keepalive_period_ms": 5,
                    "keepalive_frames_sent": 0,
                    "aborted": False,
                    "issues": [],
                    "passed": False,
                }
                try:
                    session.driver.ensure_motor(motor)
                    timeout_value = session.driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.5)
                    item["present"] = timeout_value is not None
                    if not item["present"]:
                        item["issues"].append("missing")
                        results.append(item)
                        continue
                    item["pre_status"] = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                    if item["pre_status"].get("has_error"):
                        item["issues"].append("precheck_motor_error")
                        results.append(item)
                        continue
                    if _status_read_anomaly(item["pre_status"]):
                        item["issues"].append("precheck_status_read_anomaly")
                        results.append(item)
                        continue

                    motors.append((joint, motor, item))
                    results.append(item)
                except Exception as error:
                    item["issues"].append("precheck_failed")
                    item["error"] = str(error)
                    results.append(item)

            active_items = [item for _, _, item in motors if item["present"] and not item["issues"]]
            if active_items:
                try:
                    for _, motor, item in motors:
                        if item["issues"]:
                            continue
                        if hasattr(session.driver, "enable_fast"):
                            item["enable_ok"] = bool(session.driver.enable_fast(motor))
                        else:
                            item["enable_ok"] = bool(session.driver.enable(motor))
                    time.sleep(0.03)
                    start_positions = {
                        item["joint_name"]: float(item["pre_status"].get("position", 0.0))
                        for _, _, item in motors
                        if not item["issues"]
                    }
                    deadline = time.time() + hold_s
                    while time.time() < deadline:
                        for joint, motor, item in motors:
                            if item["issues"]:
                                continue
                            start_q = start_positions.get(item["joint_name"], 0.0)
                            if str(joint.get("joint_name", "")).endswith("J8"):
                                kp, kd = 1.0, 0.1
                            else:
                                kp, kd = 2.0, 0.15
                            if hasattr(session.driver, "controlMIT_fast"):
                                session.driver.controlMIT_fast(motor, kp=kp, kd=kd, q=start_q, dq=0.0, tau=0.0)
                            else:
                                session.driver.controlMIT(motor, kp=kp, kd=kd, q=start_q, dq=0.0, tau=0.0)
                            item["keepalive_frames_sent"] += 1
                        if hasattr(session.driver, "_drain"):
                            session.driver._drain(0.002)
                        time.sleep(0.005)
                    for _, motor, item in motors:
                        if item["issues"]:
                            continue
                        item["after_enable"] = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                except Exception as error:
                    for _, _, item in motors:
                        if not item["issues"]:
                            item["issues"].append("enable_check_failed")
                            item["error"] = str(error)
                finally:
                    for _, motor, item in motors:
                        if item["issues"] and not item["enable_ok"]:
                            continue
                        try:
                            if hasattr(session.driver, "disable_fast"):
                                item["disable_ok"] = bool(session.driver.disable_fast(motor))
                            else:
                                item["disable_ok"] = bool(session.driver.disable(motor))
                        except Exception as error:
                            item["disable_ok"] = False
                            item.setdefault("error", str(error))
                            item["issues"].append("disable_failed")
                    if hasattr(session.driver, "_drain"):
                        session.driver._drain(0.4)
                    else:
                        time.sleep(0.4)
                    for _, motor, item in motors:
                        if item["issues"] and not item["disable_ok"]:
                            continue
                        try:
                            item["after_disable"] = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                        except Exception as error:
                            item["disable_ok"] = False
                            item.setdefault("error", str(error))
                            item["issues"].append("disable_failed")

            for item in results:
                if not item["present"]:
                    continue
                if not item["enable_ok"] and "precheck" not in ",".join(item["issues"]):
                    item["issues"].append("enable_failed")
                if not item["disable_ok"] and item["enable_ok"]:
                    item["issues"].append("disable_failed")
                for key in ("after_enable", "after_disable"):
                    snapshot = item.get(key) or {}
                    if snapshot.get("has_error"):
                        item["issues"].append(f"{key}_motor_error")
                    elif snapshot and _status_read_anomaly(snapshot):
                        item["issues"].append(f"{key}_status_read_anomaly")
                if item.get("after_enable") and item.get("after_enable", {}).get("status") != "ENABLED":
                    item["issues"].append("enable_state_not_confirmed")
                if item.get("after_disable") and item.get("after_disable", {}).get("status") != "DISABLED":
                    item["issues"].append("disable_state_not_confirmed")
                item["issues"] = list(dict.fromkeys(item["issues"]))
                item["passed"] = item["present"] and not item["issues"]

            aborted = any(
                item["present"] and any("motor_error" in issue or "comm" in issue.lower() for issue in item["issues"])
                for item in results
            )
            failed_joint = next(
                (
                    item
                    for item in results
                    if item["present"] and any("motor_error" in issue or "comm" in issue.lower() for issue in item["issues"])
                ),
                None,
            )
            abort_reason = (
                f"{failed_joint['joint_name']} failed with {','.join(failed_joint['issues'])}" if failed_joint else None
            )
            payload = {
                "profile_id": profile_id,
                "arm_side": profile.get("arm_side"),
                "hold_ms": int(round(hold_s * 1000.0)),
                "motion_command_sent": False,
                "control_keepalive_sent": True,
                "aborted": aborted,
                "abort_reason": abort_reason,
                "summary": {
                    "total_expected": len(profile["joints"]),
                    "total_present": sum(1 for item in results if item["present"]),
                    "passed": sum(1 for item in results if item["passed"]),
                    "failed": sum(1 for item in results if not item["passed"]),
                    "all_disabled_after_check": all(
                        (item.get("after_disable") or {}).get("status") == "DISABLED"
                        for item in results
                        if item.get("present")
                    ),
                },
                "results": results,
                "ok": all(item["passed"] for item in results),
            }
            self._record_arm_step_run(arm_cn, "arm_safe_enable_check", payload)
            return payload

    def _record_arm_step_run(self, arm_cn: Optional[str], kind: str, payload: Dict[str, Any]):
        """Note on the arm record that a wizard step ran, and how it went.

        Without this, TIMEOUT standardization and the low-gain enable check leave no
        machine-readable trace anywhere on the arm - the three arms already shipped
        have none - so nothing can tell whether they were done. Writing to the arm is
        skipped entirely when no arm_cn is given, which is how every existing caller
        behaves.
        """
        if not arm_cn:
            return
        try:
            path, arm = self._load_arm_record(str(arm_cn))
        except (KeyError, ValueError, TypeError):
            return
        history = list(arm.get("command_run_history") or [])
        history.append(
            {
                "run_id": uuid.uuid4().hex[:12],
                "kind": kind,
                "arm_cn": str(arm_cn),
                "profile_id": payload.get("profile_id"),
                "arm_side": payload.get("arm_side"),
                "status": "passed" if payload.get("ok") else "failed",
                "motion_command_sent": bool(payload.get("motion_command_sent")),
                "summary": payload.get("summary"),
                "finished_at": _now_iso(),
            }
        )
        arm["command_run_history"] = history
        arm["updated_at"] = _now_iso()
        _atomic_json(path, arm)

    def _record_joint_runtime_result(self, job_id: Optional[str], result_key: str, result: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if not job_id or job_id not in self.jobs:
                return result
            job = self.jobs[job_id]
            job.motors.setdefault("commissioned_motor", {})[result_key] = result
            self._log_event(job, "info", result_key, f"{result_key} recorded for {result.get('joint_name')}")
            self._persist_job(job)
            return result

    def calibrate_arm_zero(
        self,
        session_id: str,
        profile_id: str = "openarm_right_arm_v1",
        arm_cn: Optional[str] = None,
        operator: Optional[str] = None,
        notes: Optional[str] = None,
        confirmations: Optional[Dict[str, bool]] = None,
        save_flash: bool = True,
        zero_pose_name: str = "openarm_home",
    ) -> Dict[str, Any]:
        confirmations = confirmations or {}
        missing_confirmations = [
            {"key": key, "label": label}
            for key, label in WORKBENCH_ZERO_CONFIRMATIONS.items()
            if not confirmations.get(key)
        ]
        if missing_confirmations:
            return {
                "calibrated": False,
                "status": "blocked",
                "missing_confirmations": missing_confirmations,
                "joint_results": [],
                "record_entry": None,
            }

        with self._lock:
            session = self._session(session_id)
            profile = self.profile_manager.get_profile(profile_id)
            arm_scan = self._scan_arm_with_stability(session, profile_id, repeat_count=1)
            if not arm_scan["summary"].get("passed"):
                return {
                    "calibrated": False,
                    "status": "blocked_by_comm_scan",
                    "missing_confirmations": [],
                    "precheck_summary": arm_scan["summary"],
                    "blocking_reasons": self._zero_blocking_reasons(arm_scan["summary"]),
                    "joint_results": [],
                    "record_entry": None,
                }

            joint_results: List[Dict[str, Any]] = []
            for item in arm_scan["results"]:
                joint = item["expected"]
                motor = Motor(
                    _motor_type_from_name(joint["motor_type"]),
                    int(joint["target_esc_id"]),
                    int(joint["target_mst_id"]),
                )
                before = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                issues = []
                if before.get("has_error"):
                    issues.append("motor_error_before_zero")
                if float(before.get("t_mos", 0.0)) >= TEMP_LIMITS["mos"]:
                    issues.append("mos_overtemp")
                if float(before.get("t_rotor", 0.0)) >= TEMP_LIMITS["rotor"]:
                    issues.append("rotor_overtemp")

                disable_ok = False
                zero_ok = False
                save_ok = None
                after = before
                final = before
                if not issues:
                    try:
                        disable_ok = bool(session.driver.disable(motor))
                        if not disable_ok:
                            issues.append("disable_failed")
                        else:
                            zero_ok = bool(session.driver.set_zero_position(motor))
                            time.sleep(0.15)
                            after = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                            if not zero_ok:
                                issues.append("zero_command_failed")
                            if abs(float(after.get("position", 999.0))) > 0.05:
                                retry_ok = bool(session.driver.set_zero_position(motor))
                                time.sleep(0.15)
                                after = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                                if retry_ok:
                                    zero_ok = True
                                    issues = [issue for issue in issues if issue != "zero_command_failed"]
                                elif "zero_command_failed" not in issues:
                                    issues.append("zero_command_failed")
                            if abs(float(after.get("position", 999.0))) > 0.05:
                                issues.append("zero_verify_failed")
                            if after.get("has_error"):
                                issues.append("motor_error_after_zero")
                            if save_flash and not issues:
                                save_ok = bool(session.driver.save_motor_param(motor))
                                if not save_ok:
                                    issues.append("save_flash_failed")
                            final = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                    except Exception as error:
                        issues.append("zero_runtime_failed")
                        try:
                            session.driver.disable(motor)
                        except Exception:
                            pass
                        final = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                        joint_results.append(
                            {
                                "joint_name": item["joint_name"],
                                "motor_type": joint["motor_type"],
                                "esc_id": int(joint["target_esc_id"]),
                                "mst_id": int(joint["target_mst_id"]),
                                "passed": False,
                                "issues": issues,
                                "error": str(error),
                                "before": before,
                                "after": after,
                                "final": final,
                                "save_flash": save_flash,
                                "save_ok": save_ok,
                            }
                        )
                        continue

                joint_results.append(
                    {
                        "joint_name": item["joint_name"],
                        "motor_type": joint["motor_type"],
                        "esc_id": int(joint["target_esc_id"]),
                        "mst_id": int(joint["target_mst_id"]),
                        "passed": not issues,
                        "issues": issues,
                        "before": before,
                        "after": after,
                        "final": final,
                        "measured_position": final.get("position"),
                        "save_flash": save_flash,
                        "save_ok": save_ok,
                    }
                )

            post_recovery = self._recover_session_disabled_state(session, profile["joints"])
            recovery_by_joint = {item.get("joint_name"): item for item in post_recovery.get("results", [])}
            for item in joint_results:
                recovery = recovery_by_joint.get(item["joint_name"])
                if recovery:
                    item["post_recovery"] = recovery
                    if not recovery.get("passed"):
                        item["issues"] = list(dict.fromkeys([*item.get("issues", []), "post_zero_disable_recovery_failed"]))
                        item["passed"] = False

            passed = (
                all(item["passed"] for item in joint_results)
                and len(joint_results) == len(profile["joints"])
                and not post_recovery.get("has_blocking")
            )
            status = "passed" if passed else "failed"
            record_entry = None
            if arm_cn:
                record = self.record_zero_calibration(
                    arm_cn=arm_cn,
                    calibration_scope=profile.get("arm_side", profile_id),
                    status=status,
                    operator=operator,
                    zero_pose_name=zero_pose_name,
                    notes=notes,
                    joints=[item["joint_name"] for item in joint_results],
                    method="workbench_native_zero",
                    joint_results=joint_results,
                    precheck_summary=arm_scan["summary"],
                )
                record_entry = record["entry"]

            return {
                "calibrated": passed,
                "status": status,
                "profile_id": profile_id,
                "arm_side": profile.get("arm_side"),
                "zero_pose_name": zero_pose_name,
                "precheck_summary": arm_scan["summary"],
                "post_recovery": post_recovery,
                "joint_results": joint_results,
                "record_entry": record_entry,
            }

    def _recover_session_disabled_state(self, session: DeviceSession, joints: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {
            "started_at": _now_iso(),
            "finished_at": None,
            "attempted": bool(joints),
            "has_blocking": False,
            "results": [],
        }
        for joint in joints:
            motor = Motor(
                _motor_type_from_name(joint["motor_type"]),
                int(joint["target_esc_id"]),
                int(joint["target_mst_id"]),
            )
            item = {
                "joint_name": joint.get("joint_name"),
                "esc_id": int(joint["target_esc_id"]),
                "mst_id": int(joint["target_mst_id"]),
                "disable_ok": False,
                "status": None,
                "issues": [],
            }
            try:
                if hasattr(session.driver, "ensure_motor"):
                    session.driver.ensure_motor(motor)
                elif hasattr(session.driver, "addMotor"):
                    session.driver.addMotor(motor)
                item["disable_ok"] = bool(session.driver.disable(motor))
                time.sleep(0.03)
                snapshot = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                item["status"] = snapshot
                if not item["disable_ok"]:
                    item["issues"].append("disable_failed")
                if snapshot.get("status") != "DISABLED":
                    item["issues"].append("disable_state_not_confirmed")
                if snapshot.get("has_error"):
                    item["issues"].append("post_recovery_motor_error")
                elif _status_read_anomaly(snapshot):
                    item["issues"].append("post_recovery_status_read_anomaly")
            except Exception as error:
                item["issues"].append("post_recovery_failed")
                item["error"] = str(error)
            item["passed"] = not item["issues"]
            payload["results"].append(item)
        payload["has_blocking"] = any(not item.get("passed") for item in payload["results"])
        payload["finished_at"] = _now_iso()
        return payload

    def _zero_blocking_reasons(self, summary: Dict[str, Any]) -> List[str]:
        reasons = []
        for key in ["missing", "unhealthy", "bitrate_mismatches", "ctrl_mode_mismatches", "bus_mismatches", "duplicate_esc_ids", "unexpected_ids"]:
            values = summary.get(key) or []
            if values:
                reasons.append(f"{key}:{values}")
        if summary.get("total_mismatches"):
            reasons.append(f"mismatches:{summary.get('total_mismatches')}")
        return reasons

    def _list_socketcan_interfaces(self) -> List[Dict[str, Any]]:
        base = Path("/sys/class/net")
        if not base.exists():
            return []

        interfaces = []
        for iface_dir in sorted(base.iterdir(), key=lambda item: item.name):
            try:
                if (iface_dir / "type").read_text(encoding="utf-8").strip() != "280":
                    continue
            except Exception:
                continue

            details = self._ip_link_details(iface_dir.name)
            device_path = iface_dir / "device"
            driver_name = self._driver_name(device_path)
            usb_meta = self._usb_metadata(device_path)
            identity_blob = " ".join(filter(None, [driver_name, *usb_meta.values()])).lower()
            adapter_kind = "gsusb1002enc" if "gsusb1002enc" in identity_blob else ("gs_usb" if "gs_usb" in identity_blob else None)
            interfaces.append(
                {
                    "name": iface_dir.name,
                    "driver": driver_name,
                    "adapter_kind": adapter_kind,
                    "is_gs_usb": "gs_usb" in identity_blob,
                    "bitrate": details.get("bitrate"),
                    "dbitrate": details.get("dbitrate"),
                    "fd_enabled": details.get("fd_enabled"),
                    "can_state": details.get("can_state"),
                    "berr_tx": details.get("berr_tx"),
                    "berr_rx": details.get("berr_rx"),
                    "state": details.get("state") or self._safe_read_text(iface_dir / "operstate"),
                    "mtu": self._safe_read_text(iface_dir / "mtu"),
                    "manufacturer": usb_meta.get("manufacturer"),
                    "product": usb_meta.get("product"),
                    "serial": usb_meta.get("serial"),
                    "interface_label": usb_meta.get("interface"),
                    "bus_info": usb_meta.get("bus_info"),
                    "statistics": self._interface_statistics(iface_dir),
                }
            )
        return interfaces

    def _interface_statistics(self, iface_dir: Path) -> Dict[str, Optional[int]]:
        stat_dir = iface_dir / "statistics"
        keys = ["rx_packets", "tx_packets", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped"]
        stats = {}
        for key in keys:
            value = self._safe_read_text(stat_dir / key)
            try:
                stats[key] = int(value) if value is not None else None
            except ValueError:
                stats[key] = None
        rx_packets = stats.get("rx_packets") or 0
        tx_packets = stats.get("tx_packets") or 0
        rx_errors = stats.get("rx_errors") or 0
        tx_errors = stats.get("tx_errors") or 0
        rx_dropped = stats.get("rx_dropped") or 0
        tx_dropped = stats.get("tx_dropped") or 0
        total_packets = rx_packets + tx_packets
        stats["total_packets"] = total_packets
        stats["total_errors"] = rx_errors + tx_errors
        stats["total_dropped"] = rx_dropped + tx_dropped
        stats["error_rate"] = (stats["total_errors"] / total_packets) if total_packets else 0.0
        stats["drop_rate"] = (stats["total_dropped"] / total_packets) if total_packets else 0.0
        return stats

    def _ip_link_details(self, interface_name: str) -> Dict[str, Any]:
        try:
            result = self._run_system_command(["ip", "-details", "link", "show", "dev", interface_name], check=False)
        except Exception:
            return {}
        if result.returncode != 0:
            return {}
        output = result.stdout
        bitrate_match = re.search(r"\bbitrate\s+(\d+)", output)
        dbitrate_match = re.search(r"\bdbitrate\s+(\d+)", output)
        state_match = re.search(r"\bstate\s+([A-Z_]+)", output)
        can_state_match = re.search(r"\bcan state\s+([A-Z-]+)", output)
        berr_match = re.search(r"\bberr-counter\s+tx\s+(\d+)\s+rx\s+(\d+)", output)
        fd_enabled = bool(re.search(r"\bfd\b", output) or dbitrate_match)
        return {
            "bitrate": int(bitrate_match.group(1)) if bitrate_match else None,
            "dbitrate": int(dbitrate_match.group(1)) if dbitrate_match else None,
            "fd_enabled": fd_enabled,
            "state": state_match.group(1) if state_match else None,
            "can_state": can_state_match.group(1) if can_state_match else None,
            "berr_tx": int(berr_match.group(1)) if berr_match else None,
            "berr_rx": int(berr_match.group(2)) if berr_match else None,
        }

    def _run_system_command(self, cmd: List[str], check: bool = True):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as error:
            raise RuntimeError(f"system command not found: {cmd[0]}") from error
        except Exception as error:
            raise RuntimeError(f"failed to run system command: {' '.join(cmd)}") from error
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip() or "system command failed"
            raise RuntimeError(message)
        return result

    def _require_interface(self, name: str):
        if not any(item["name"] == name for item in self._list_socketcan_interfaces()):
            raise KeyError(f"interface {name} not found")

    def _interface_snapshot(self, name: str) -> Dict[str, Any]:
        for item in self._list_socketcan_interfaces():
            if item["name"] == name:
                return item
        raise KeyError(f"interface {name} not found")

    def _driver_name(self, device_path: Path) -> Optional[str]:
        try:
            driver_path = (device_path / "driver").resolve()
            return driver_path.name
        except Exception:
            return None

    def _usb_metadata(self, device_path: Path) -> Dict[str, Optional[str]]:
        meta = {
            "manufacturer": None,
            "product": None,
            "serial": None,
            "interface": None,
            "bus_info": None,
        }
        try:
            resolved = device_path.resolve()
        except Exception:
            return meta

        candidates = [resolved, resolved.parent, resolved.parent.parent]
        for candidate in candidates:
            if not candidate or not candidate.exists():
                continue
            for key, file_name in [("manufacturer", "manufacturer"), ("product", "product"), ("serial", "serial"), ("interface", "interface")]:
                if meta[key] is None:
                    meta[key] = self._safe_read_text(candidate / file_name)
            if meta["bus_info"] is None:
                meta["bus_info"] = candidate.name if "-" in candidate.name or ":" in candidate.name else None
        return meta

    def _safe_read_text(self, path: Path) -> Optional[str]:
        try:
            value = path.read_text(encoding="utf-8").strip()
            return value or None
        except Exception:
            return None

    def create_job(
        self,
        job_type: str,
        session_id: str,
        profile_id: Optional[str] = None,
        target_joint: Optional[str] = None,
        expert_mode: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            canonical_job_type = _canonical_job_type(job_type)
            job_id = uuid.uuid4().hex[:12]
            artifact_dir = ARTIFACTS_DIR / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{job_id}"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            job = JobRecord(
                job_id=job_id,
                job_type=canonical_job_type,
                device_session_id=session_id,
                artifact_dir=str(artifact_dir),
                profile_id=profile_id,
                target_joint=target_joint,
                expert_mode=expert_mode,
                status="device_connected",
                current_step="device_connected",
            )
            self.jobs[job_id] = job
            self._log_event(job, "info", "job_created", "任务已创建")
            self._persist_job(job)
            return {
                "job_id": job.job_id,
                "status": job.status,
                "allowed_actions": self._allowed_actions(job),
            }

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            return self._job_payload(job)

    def apply_profile(self, job_id: str, target_joint: Optional[str], profile_id: str, overrides: Optional[Dict[str, Any]] = None):
        with self._lock:
            job = self._job(job_id)
            if job.job_type not in {"single_id_config", "single_param_config"}:
                raise ValueError("apply_profile is only valid for single_id_config or single_param_config")
            session = self._session(job.device_session_id)
            candidate = self._select_single_candidate(session)
            current_motor = self._motor_from_candidate(candidate)
            current_params = self._read_params(session, current_motor, PARAM_CONFIG_RIDS)
            current_status = self._refresh_and_snapshot(session, current_motor)
            joint = self._build_single_target_config(
                job.job_type,
                profile_id,
                target_joint,
                candidate,
                current_params,
            )
            if overrides:
                for key, value in overrides.items():
                    if value is not None and key in joint:
                        joint[key] = value
            job.target_joint = target_joint
            job.profile_id = profile_id
            job.candidate = candidate
            job.target_config = joint
            job.motors = {
                "commissioned_motor": {
                    "current": {
                        "candidate": candidate,
                        "params": current_params,
                        "status": current_status,
                    },
                    "target": joint,
                }
            }
            job.status = "profile_selected"
            job.current_step = "profile_selected"
            self._log_event(job, "info", "profile_selected", f"已加载目标配置 {target_joint or 'auto-match'}")
            self._persist_job(job)
            return {"target_config": joint, "current_snapshot": job.motors["commissioned_motor"]["current"]}

    def write_params(self, job_id: str, target_config: Dict[str, Any]):
        with self._lock:
            job = self._job(job_id)
            session = self._session(job.device_session_id)
            self._require_capability(session, "write_params")
            if job.status != "profile_selected":
                raise ValueError("write_params requires profile_selected state")
            motor = self._motor_from_candidate(job.candidate)
            if not self._disable_for_parameter_write(session, motor):
                self._fail_job(job, "disable 失败，禁止写入参数")
                raise RuntimeError("disable failed before parameter write")
            self._write_single_target(
                session,
                motor,
                target_config,
                allow_service_params=job.expert_mode,
            )
            job.target_config = target_config
            job.status = "params_written"
            job.current_step = "params_written"
            self._log_event(job, "info", "params_written", "参数写入完成，等待回读校验")
            self._persist_job(job)
            return {"written": True, "verification_required": True}

    def verify_params(self, job_id: str):
        with self._lock:
            job = self._job(job_id)
            session = self._session(job.device_session_id)
            motor = self._motor_from_candidate(job.candidate)
            verify_rids = [DM_variable.ESC_ID] + list(PARAM_TARGET_FIELD_MAP.values())
            verification = self._read_params(session, motor, verify_rids)
            mismatches = self._single_param_mismatches(job.target_config, verification)

            job.motors.setdefault("commissioned_motor", {}).setdefault("verification", verification)
            job.motors["commissioned_motor"]["mismatches"] = mismatches
            if mismatches:
                self._fail_job(job, f"参数回读不一致: {mismatches}")
                return {"verified": False, "mismatches": mismatches}

            job.status = "params_verified"
            job.current_step = "params_verified"
            self._log_event(job, "info", "params_verified", "参数回读校验通过")
            self._persist_job(job)
            return {"verified": True, "mismatches": []}

    def save_flash(self, job_id: str):
        with self._lock:
            job = self._job(job_id)
            session = self._session(job.device_session_id)
            self._require_capability(session, "save_flash")
            if job.status != "params_verified":
                raise ValueError("save_flash requires params_verified state")
            motor = self._motor_from_candidate(job.candidate)
            if not session.driver.disable(motor):
                self._fail_job(job, "disable 失败，禁止保存 Flash")
                raise RuntimeError("disable failed")
            if not session.driver.save_motor_param(motor):
                self._fail_job(job, "save flash 失败")
                raise RuntimeError("save flash failed")
            job.status = "params_saved"
            job.current_step = "params_saved"
            self._log_event(job, "info", "params_saved", "参数已保存到 Flash")
            self._persist_job(job)
            return {"saved": True, "save_timestamp": _now_iso()}

    def zero(self, job_id: str, confirmed: bool):
        with self._lock:
            job = self._job(job_id)
            session = self._session(job.device_session_id)
            self._require_capability(session, "zero")
            if not confirmed:
                raise ValueError("zero requires confirmed=true")
            if job.job_type != "single_id_config" or not job.expert_mode:
                raise ValueError("loose-motor zero save requires an expert single_id_config job")
            if job.status != "params_saved":
                raise ValueError("zero requires params_saved state")
            motor = self._motor_from_candidate(job.candidate)
            if not self._zero_precheck(session, motor):
                self._fail_job(job, "零位前置条件不满足")
                raise RuntimeError("zero precheck failed")

            last_snapshot = None
            for attempt in range(2):
                session.driver.disable(motor)
                session.driver.set_zero_position(motor)
                time.sleep(0.5)
                last_snapshot = self._refresh_and_snapshot(session, motor)
                if self._zero_passed(last_snapshot):
                    job.status = "zeroed"
                    job.current_step = "zeroed"
                    job.motors["commissioned_motor"]["zero"] = last_snapshot
                    self._log_event(job, "info", "zeroed", f"零位成功，attempt={attempt + 1}")
                    self._persist_job(job)
                    return {"zeroed": True, "measured_position": last_snapshot["position"]}

            self._fail_job(job, "零位失败")
            return {"zeroed": False, "measured_position": last_snapshot["position"] if last_snapshot else None}

    def test(
        self,
        job_id: str,
        confirmed: bool,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
        allow_motion: bool = False,
    ):
        with self._lock:
            job = self._job(job_id)
            session = self._session(job.device_session_id)
            if job.job_type == "single_id_config":
                if not confirmed:
                    raise ValueError("test requires confirmed=true")
                if job.status == "zeroed":
                    # Motion ping targets absolute q=0, so it is only meaningful after an expert zero save.
                    self._require_capability(session, "test")
                    result = self._safe_mit_ping(session, self._motor_from_candidate(job.candidate))
                    failure_reason = "测试未通过"
                elif job.status == "params_saved":
                    result = self._single_saved_readback(job, session)
                    failure_reason = "测试未通过: 保存后只读复核失败"
                else:
                    raise ValueError("single test requires zeroed or params_saved state")
                job.motors["commissioned_motor"]["test"] = result
                if not result["passed"]:
                    self._fail_job(job, failure_reason)
                    record = self._save_single_motor_record(job, result)
                    return {"tested": False, "metrics": result, "record": record}
                job.status = "passed"
                job.current_step = "tested"
                job.finished_at = _now_iso()
                self._log_event(job, "info", "tested", "测试通过，单电机记录已保存")
                self._persist_job(job)
                record = self._save_single_motor_record(job, result)
                return {"tested": True, "metrics": result, "record": record}

            if job.job_type == "single_param_config":
                if job.status != "params_saved":
                    raise ValueError("single_param_config requires params_saved state")
                job.status = "passed"
                job.current_step = "reported"
                job.finished_at = _now_iso()
                self._log_event(job, "info", "reported", "参数配置流程完成")
                self._persist_job(job)
                self._write_report(job)
                return {"tested": True, "metrics": {"passed": True, "mode": "param_config"}}

            if job.job_type == "single_comm_check":
                if not confirmed:
                    raise ValueError("run_comm_check requires confirmed=true")
                result = self._run_single_comm_check(job, session)
                if result["passed"]:
                    job.status = "passed"
                    job.current_step = "checked"
                    job.finished_at = _now_iso()
                    self._log_event(job, "info", "checked", "单电机通信校验通过")
                else:
                    self._fail_job(job, "单电机通信校验失败")
                self._persist_job(job)
                self._write_report(job)
                return {"tested": result["passed"], "metrics": result}

            if job.job_type == "arm_comm_scan":
                result = self._run_arm_comm_scan(
                    job,
                    session,
                    repeat_count=repeat_count,
                    repeat_delay_ms=repeat_delay_ms,
                    allow_motion=allow_motion,
                )
                if result["passed"]:
                    job.status = "passed"
                    job.current_step = "reported"
                    job.finished_at = _now_iso()
                    self._log_event(job, "info", "arm_scanned", "整臂 CAN2.0 通信扫描通过")
                else:
                    self._fail_job(job, "整臂 CAN2.0 通信扫描失败")
                self._persist_job(job)
                self._write_report(job)
                return {"tested": result["passed"], "metrics": result}

            if job.job_type == "arm_acceptance":
                result = self._run_arm_acceptance(
                    job,
                    session,
                    repeat_count=repeat_count,
                    repeat_delay_ms=repeat_delay_ms,
                    allow_motion=allow_motion,
                )
                if result["passed"]:
                    job.status = "passed"
                    job.current_step = "reported"
                    job.finished_at = _now_iso()
                    self._log_event(job, "info", "arm_acceptance", "整臂 CAN2.0 验收通过")
                else:
                    self._fail_job(job, "整臂 CAN2.0 验收失败")
                self._persist_job(job)
                self._write_report(job)
                return {"tested": result["passed"], "metrics": result}

            raise ValueError("unsupported job type")

    def report(self, job_id: str):
        with self._lock:
            job = self._job(job_id)
            self._write_report(job)
            artifact_dir = Path(job.artifact_dir)
            return {
                "artifact_dir": str(artifact_dir),
                "files": [
                    "job.json",
                    "issues.json",
                    "events.jsonl",
                    "report.html",
                    *[str(path.relative_to(artifact_dir)) for path in sorted((artifact_dir / "motors").glob("*.json"))],
                ],
            }

    def run_comm_check(self, job_id: str, confirmed: bool = True):
        return self.test(job_id, confirmed=confirmed)

    def run_arm_scan(
        self,
        job_id: str,
        confirmed: bool = True,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
        allow_motion: bool = False,
    ):
        return self.test(
            job_id,
            confirmed=confirmed,
            repeat_count=repeat_count,
            repeat_delay_ms=repeat_delay_ms,
            allow_motion=allow_motion,
        )

    def run_arm_acceptance(
        self,
        job_id: str,
        confirmed: bool = True,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
        allow_motion: bool = False,
    ):
        return self.test(
            job_id,
            confirmed=confirmed,
            repeat_count=repeat_count,
            repeat_delay_ms=repeat_delay_ms,
            allow_motion=allow_motion,
        )

    def issues(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            issues = self._collect_job_issues(job)
            severity_counts = {"critical": 0, "warning": 0, "info": 0}
            for item in issues:
                severity_counts[item["severity"]] = severity_counts.get(item["severity"], 0) + 1
            summary = {
                "total": len(issues),
                "critical": severity_counts["critical"],
                "warning": severity_counts["warning"],
                "info": severity_counts["info"],
                "has_blocking": severity_counts["critical"] > 0,
            }
            return {
                "issues": issues,
                "summary": summary,
                "severity_counts": severity_counts,
                "playbooks": self._diagnostic_playbooks(job, issues),
            }

    def cancel(self, job_id: str):
        with self._lock:
            job = self._job(job_id)
            if job.status in {"passed", "failed", "cancelled"}:
                raise ValueError("job already finished")
            if job.status == "params_saved":
                raise ValueError("cancel is not allowed after params_saved")
            job.status = "cancelled"
            job.current_step = "cancelled"
            job.finished_at = _now_iso()
            self._log_event(job, "warning", "cancelled", "任务已取消")
            self._persist_job(job)
            return {"cancelled": True}

    # ---- Single-motor records (consumed later by whole-arm factory reporting) ----

    def _single_motor_records_dir(self) -> Path:
        return FACTORY_DIR / "single_motor_records"

    def _save_single_motor_record(self, job: JobRecord, result: Dict[str, Any]) -> Dict[str, Any]:
        motor_payload = job.motors.get("commissioned_motor", {})
        before = dict(motor_payload.get("current", {}).get("params", {}) or {})
        after = dict(result.get("readback") or {})
        target = job.target_config
        status = result.get("final_status") or {}
        record = {
            "record_id": f"smr_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{job.job_id}",
            "record_type": "single_motor_commissioning",
            "created_at": _now_iso(),
            "workstation_version": WORKSTATION_VERSION,
            "result": "PASS" if result.get("passed") else "FAIL",
            # Damiao's SN register is not unique per motor (live batch 2026-09-17 read the same value on
            # different motors), so it is kept only as raw evidence, never as a motor identity key.
            "sn_register": after.get("SN") if after.get("SN") is not None else before.get("SN"),
            "motor_type": target.get("motor_type"),
            "model_check": _infer_motor_model(before, target.get("motor_type")),
            "product_line": job.product_line,
            "product_line_label": SINGLE_WIZARD_PRODUCT_LINES.get(job.product_line or "", job.product_line),
            "arm_side": target.get("arm_side"),
            "joint_name": target.get("joint_name") or job.target_joint,
            "profile_id": job.profile_id,
            "job_id": job.job_id,
            "job_artifact_dir": job.artifact_dir,
            "check_mode": result.get("mode"),
            "motion_performed": bool(result.get("motion", "peak_position" in result)),
            "zero_saved": "zero" in motor_payload,
            "target": {
                "ESC_ID": target.get("target_esc_id"),
                "MST_ID": target.get("target_mst_id"),
                "CTRL_MODE": target.get("target_ctrl_mode"),
                "can_br": target.get("target_can_br"),
            },
            "before": before,
            "after": after,
            # Human-readable values actually read back from the motor after save (not the targets).
            "verified": {
                "ESC_ID": after.get("ESC_ID"),
                "MST_ID": after.get("MST_ID"),
                "CTRL_MODE": _control_name(after["CTRL_MODE"]) if after.get("CTRL_MODE") is not None else None,
                "can_br": _normalize_can_br(after.get("can_br")),
                "can_br_code": after.get("can_br"),
                # Single-motor ID commissioning happens on the product's commissioning
                # bus, which is classic CAN for both versions today. Read it rather
                # than assert it, so a product that commissions on FD records the truth.
                "can_mode": self._can_mode_label(job.product_line, "commissioning"),
            },
            "timeout_recorded": after.get("TIMEOUT", before.get("TIMEOUT")),
            "firmware": {"sw_ver": before.get("sw_ver"), "sub_ver": before.get("sub_ver")},
            "final_status": {
                key: status.get(key)
                for key in ("status", "status_code", "has_error", "is_enabled", "t_mos", "t_rotor")
            },
            "mismatches": result.get("mismatches", []),
            "issues": result.get("issues", []),
            "failure_reason": job.failure_reason,
        }
        records_dir = self._single_motor_records_dir()
        records_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(records_dir / f"{_safe_name(record['record_id'])}.json", record)
        return record

    def _migrate_legacy_single_motor_records(self, records_dir: Path):
        # 0.8.0 grouped records by the (non-unique) SN register; split them into one file per record.
        legacy_dir = records_dir / "_legacy_by_sn"
        for path in sorted(records_dir.glob("*.json")):
            payload = _load_json(path, {}) or {}
            if "history" not in payload:
                continue
            for record in payload.get("history", []):
                target_path = records_dir / f"{_safe_name(record['record_id'])}.json"
                if target_path.exists():
                    continue
                migrated = dict(record)
                migrated["sn_register"] = migrated.pop("motor_hw_sn", None)
                migrated.pop("sn_available", None)
                migrated.setdefault("model_check", _infer_motor_model(migrated.get("before") or {}, migrated.get("motor_type")))
                migrated["migrated_from"] = f"_legacy_by_sn/{path.name}"
                _atomic_json(target_path, migrated)
            legacy_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(legacy_dir / path.name))

    def _load_single_motor_records(self) -> List[Dict[str, Any]]:
        records_dir = self._single_motor_records_dir()
        if not records_dir.exists():
            return []
        self._migrate_legacy_single_motor_records(records_dir)
        records = [_load_json(path, {}) or {} for path in records_dir.glob("*.json")]
        records = [item for item in records if item.get("record_type") == "single_motor_commissioning"]
        records.sort(key=lambda item: (item.get("created_at") or "", item.get("record_id") or ""), reverse=True)
        return records

    def list_single_motor_records(self, limit: int = 50) -> Dict[str, Any]:
        with self._lock:
            records = self._load_single_motor_records()
            joints: Dict[str, Dict[str, Any]] = {}
            for record in records:
                if record.get("result") != "PASS":
                    continue
                key = f"{record.get('product_line')}:{record.get('joint_name')}"
                joints.setdefault(key, record)
            return {
                "records": records[: max(1, int(limit))],
                "total_records": len(records),
                "configured_joints": sorted(
                    ({"product_line": item.get("product_line"), "joint_name": item.get("joint_name"), "record_id": item.get("record_id"), "created_at": item.get("created_at")} for item in joints.values()),
                    key=lambda item: (item["product_line"] or "", item["joint_name"] or ""),
                ),
            }

    def _joints_matching_ids(self, esc_id: Any, mst_id: Any) -> List[str]:
        if esc_id is None or mst_id is None or int(mst_id) == 0:
            return []
        names = []
        for meta in SINGLE_WIZARD_ARM_PROFILES.values():
            for joint in self.profile_manager.get_profile(meta["profile_id"])["joints"]:
                if int(joint["target_esc_id"]) == int(esc_id) and int(joint["target_mst_id"]) == int(mst_id):
                    names.append(joint["joint_name"])
        return names

    # ---- Beginner single-motor wizard ----

    def single_wizard_options(self) -> Dict[str, Any]:
        arms = []
        for arm_side, meta in SINGLE_WIZARD_ARM_PROFILES.items():
            profile = self.profile_manager.get_profile(meta["profile_id"])
            arms.append(
                {
                    "arm_side": arm_side,
                    "label": meta["label"],
                    "joints": [
                        {
                            "joint": str(joint["joint_name"]).split("-", 1)[-1],
                            "joint_name": joint["joint_name"],
                            "motor_type": joint.get("motor_type"),
                            "target_esc_id": int(joint["target_esc_id"]),
                            "target_mst_id": int(joint["target_mst_id"]),
                            "target_ctrl_mode": joint.get("target_ctrl_mode"),
                            "target_can_br": int(joint.get("target_can_br") or 1000000),
                        }
                        for joint in profile["joints"]
                    ],
                }
            )
        return {
            "arms": arms,
            "product_lines": [{"id": key, "label": label} for key, label in SINGLE_WIZARD_PRODUCT_LINES.items()],
            "defaults": {"channel": "can0", "bitrate": 1000000, "arm_side": "right_arm", "joint": "J1", "product_line": "openarm_2_0"},
        }

    # ---- Beginner link wizard (tab 01) ----

    # ---- Beginner whole-arm wizard (tabs 03/04) ----
    #
    # The official acceptance order, one step per screen, matching the flow the link
    # and single-motor wizards already use. This layer only sequences and guards; every
    # step delegates to the same method the engineer tools have always called, so a 1.0
    # arm is judged by exactly the code that judged the three arms already shipped.
    #
    # `products` limits a step to the product versions it applies to. A step whose
    # product section is unverified is shown but locked, with the reason spelled out -
    # that is how 2.0 keeps its place in the flow while its hardware is out of reach.
    ARM_WIZARD_GROUPS: List[Dict[str, str]] = [
        {
            "id": "static",
            "label": "静态测试",
            "purpose": "机械臂通电但不运动。建档、连通、核对参数，全部做完再进入动态。",
        },
        {
            "id": "dynamic",
            "label": "动态测试",
            "purpose": "在装配好的整臂上做。带红色标记的步骤会让机械臂运动，做之前要清场。",
        },
        {
            "id": "release",
            "label": "出厂放行",
            "purpose": "核对证据是否齐全，出具正式报告。只读，不动电机。",
        },
    ]

    ARM_WIZARD_STEPS: List[Dict[str, Any]] = [
        {
            "id": "identity",
            "group": "static",
            "label": "整机建档",
            "purpose": "给这台臂建立档案，确定它是 1.0 还是 2.0。版本一经确定不可更改。",
            "motion": False,
        },
        {
            "id": "link",
            "group": "static",
            "label": "连接自检",
            "purpose": "确认 CAN 口可用、总线上能看到电机。只读，不动电机。",
            "motion": False,
        },
        {
            "id": "static",
            "group": "static",
            "label": "静态验收",
            "purpose": "逐关节核对 ID、模式、波特率、故障和温度，并复扫确认通信稳定。只读。",
            "motion": False,
        },
        {
            "id": "timeout",
            "group": "static",
            "label": "参数标准化",
            "purpose": "按 Profile 给每个关节写入 TIMEOUT 并保存。会写入电机，但不发运动指令。",
            "motion": False,
            "writes": True,
        },
        {
            "id": "fd_switch",
            "group": "static",
            "label": "切换 CAN-FD",
            "purpose": "把整臂从 1 Mbps 经典 CAN 切到 CAN-FD 1M/5M，逐关节写入并保存。",
            "motion": False,
            "writes": True,
            "products": ["openarm_2_0"],
            "lock_section": "can.operation",
        },
        {
            "id": "enable",
            "group": "dynamic",
            "label": "低增益使能检查",
            "purpose": "逐关节低增益使能再失能，确认链路正常且无故障。电机会有极轻微动作。",
            "motion": True,
        },
        {
            "id": "zero",
            "group": "dynamic",
            "label": "零位校准",
            "purpose": "保存整臂零点。做法按产品版本不同，页面会说明这一次会不会动。",
            "motion": True,
            # 1.0 searches the limits, which moves the arm. 2.0 clamps it in the Cell
            # jig and writes the current position as zero, which does not. Telling the
            # operator "the arm will move" when it will not is how a warning stops
            # being read, so the flag follows the product.
            "motion_from": "zero",
            "lock_section": "zero",
        },
        {
            "id": "gripper",
            "group": "dynamic",
            "label": "夹爪测试",
            "purpose": "按本产品的方向和行程开合夹爪，记录实测行程。夹爪会运动。",
            "motion": True,
            "lock_section": "gripper",
        },
        {
            "id": "camera",
            "group": "dynamic",
            "label": "相机测试",
            "purpose": "枚举相机、检查分辨率与帧率并留存快照。不动电机。",
            "motion": False,
            "products": ["openarm_2_0"],
            "lock_section": "camera.gripper",
        },
        {
            "id": "demo",
            "group": "dynamic",
            "label": "官方 Demo",
            "purpose": "跑官方 Demo 验证整臂动作，结束后强制失能。机械臂会运动。",
            "motion": True,
            "lock_section": "gripper",
        },
        {
            "id": "gate",
            "group": "release",
            "label": "放行检查",
            "purpose": "核对证据是否齐全、版本是否一致，给出 PASS 或 HOLD。只读。",
            "motion": False,
        },
        {
            "id": "report",
            "group": "release",
            "label": "报告签核",
            "purpose": "生成正式出厂报告并归档证据。只读。",
            "motion": False,
        },
    ]

    def _arm_wizard_step_view(self, step: Dict[str, Any], product_version: str) -> Dict[str, Any]:
        """One step, resolved for a product: applicable, locked or not, and whether it moves."""
        applies = product_version in step.get("products", [product_version])
        lock_reason = None
        if applies and step.get("lock_section"):
            lock_reason = self.product_registry.lock_reasons(product_version).get(step["lock_section"])

        motion = bool(step.get("motion"))
        section = step.get("motion_from")
        if section:
            node = self.product_registry.get(product_version).get(section)
            if isinstance(node, dict) and node.get("motion") is not None:
                motion = bool(node["motion"])

        return {
            "id": step["id"],
            "label": step["label"],
            "group": step["group"],
            "purpose": step["purpose"],
            "motion": motion,
            "writes": bool(step.get("writes")),
            "applies": applies,
            "locked": bool(lock_reason),
            "locked_reason": lock_reason,
        }

    def arm_wizard_options(self, product_version: Optional[str] = None) -> Dict[str, Any]:
        """Everything the arm wizard page needs to draw itself before any hardware."""
        with self._lock:
            selected = str(product_version or DEFAULT_PRODUCT_VERSION)
            if selected not in self.product_registry.known_versions():
                raise ValueError(f"unknown product_version {selected}")
            product = self.product_registry.get(selected)
            return {
                "product_versions": [
                    {
                        "product_version": item["product_version"],
                        "label": item["label"],
                        "hardware_verified": bool(item.get("hardware_verified")),
                    }
                    for item in self.product_registry.list_products()
                ],
                "selected_product_version": selected,
                "arm_sides": [
                    {"id": side, "label": "右臂" if side == "right_arm" else "左臂", "expected_bus": arm["expected_bus"]}
                    for side, arm in product["arms"].items()
                ],
                "groups": [dict(group) for group in self.ARM_WIZARD_GROUPS],
                "steps": [self._arm_wizard_step_view(step, selected) for step in self.ARM_WIZARD_STEPS],
                "operation_bus": dict(product["can"]["operation"]),
                "locked_sections": self.product_registry.lock_reasons(selected),
                "defaults": {"channel": "can0", "arm_side": "right_arm"},
            }

    def arm_wizard_arms(self) -> Dict[str, Any]:
        """Arms already on file, newest first, for the wizard's picker."""
        with self._lock:
            FACTORY_ARMS_DIR.mkdir(parents=True, exist_ok=True)
            arms = []
            for path in FACTORY_ARMS_DIR.glob("*.json"):
                arm = _load_json(path, {})
                if not arm.get("arm_cn"):
                    continue
                product_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
                try:
                    label = self.product_registry.get(product_version)["label"]
                except KeyError:
                    label = product_version
                try:
                    decision = self.factory_release_gate(arm["arm_cn"])["release_decision"]
                except Exception:
                    decision = "HOLD"
                reports = len(arm.get("factory_reports") or [])
                arms.append(
                    {
                        "arm_cn": arm["arm_cn"],
                        "arm_type": arm.get("arm_type"),
                        "product_version": product_version,
                        "product_label": label,
                        "updated_at": arm.get("updated_at"),
                        "attached_motor_records": len(arm.get("single_motor_records") or []),
                        "release_decision": decision,
                        "report_count": reports,
                        # Finished means released with a report filed. Those arms have
                        # shipped; the wizard is for the arm being built now, so they
                        # are kept on record but out of the way.
                        "completed": decision == "PASS" and reports > 0,
                    }
                )
            arms.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            return {
                "ok": True,
                "arms": [item for item in arms if not item["completed"]],
                "completed_arms": [item for item in arms if item["completed"]],
                "next_arm_cn": self._suggest_arm_cn(),
            }

    def _suggest_arm_cn(self) -> str:
        """The next free Follower serial for today, so building a new arm is one click."""
        date_code = _factory_date_code(None)
        taken = {path.stem for path in FACTORY_ARMS_DIR.glob("*.json")}
        for sequence in range(1, 100):
            candidate = f"OAF{date_code}{sequence:02d}"
            if candidate not in taken:
                return candidate
        return f"OAF{date_code}01"

    def arm_wizard_create(
        self,
        arm_cn: str,
        product_version: str,
        arm_type: str = "OpenARM Follower",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Step 1: open the file for a new arm. This is the wizard's own first step."""
        with self._lock:
            arm_cn = str(arm_cn or "").strip().upper()
            validation = self.validate_factory_arm_cn(arm_cn)
            if not validation.get("valid"):
                return self._wizard_problem("arm_cn_invalid", validation.get("message"))
            if (FACTORY_ARMS_DIR / f"{_safe_name(arm_cn)}.json").exists():
                return self._wizard_problem("arm_cn_taken", f"arm_cn={arm_cn}")
            if product_version not in self.product_registry.known_versions():
                return self._wizard_problem(
                    "arm_cn_invalid", f"unknown product_version {product_version}"
                )
            record = self.bind_arm_identity(
                arm_cn=arm_cn,
                arm_type=arm_type,
                notes=notes,
                product_version=product_version,
            )
            return {"ok": True, "arm_cn": record["arm_cn"], "product_version": record["product_version"]}

    ARM_EVIDENCE_FIELDS = (
        "linked_jobs",
        "zero_calibration_records",
        "demo_validation_records",
        "evidence_records",
        "factory_reports",
        "command_run_history",
        "single_motor_records",
        "workflow_history",
        "bundle_history",
    )

    def _arm_evidence_count(self, arm: Dict[str, Any]) -> int:
        """How much has been recorded against this arm. Zero means nothing was tested."""
        return sum(len(arm.get(field) or []) for field in self.ARM_EVIDENCE_FIELDS) + len(
            arm.get("joint_bindings") or {}
        )

    ARM_DELETE_MODES = ("archive", "purge")

    def arm_wizard_delete(self, arm_cn: str, mode: str = "archive") -> Dict[str, Any]:
        """Discard an archive created by mistake - wrong product version, wrong serial.

        Two ways, because they answer different questions. `archive` takes the arm out
        of the wizard but keeps its file under `deleted_arms/`, which is what you want
        when a serial might come back or someone may ask what happened to it. `purge`
        removes the file, for a serial typed wrong thirty seconds ago that should leave
        no trace at all.

        Either way it is refused the moment anything has been recorded against the arm:
        at that point the archive is evidence, and evidence is not something an operator
        deletes from a wizard.
        """
        with self._lock:
            if mode not in self.ARM_DELETE_MODES:
                raise ValueError(f"mode must be one of {self.ARM_DELETE_MODES}")
            try:
                path, arm = self._load_arm_record(arm_cn)
            except KeyError:
                return self._wizard_problem("arm_not_found", f"arm_cn={arm_cn}")
            evidence = self._arm_evidence_count(arm)
            if evidence:
                return self._wizard_problem(
                    "arm_has_evidence", f"{arm_cn} 上已有 {evidence} 条记录"
                )

            kept_at = None
            if mode == "archive":
                target_dir = FACTORY_DIR / "deleted_arms"
                target_dir.mkdir(parents=True, exist_ok=True)
                arm["deleted_at"] = _now_iso()
                arm["deleted_mode"] = mode
                _atomic_json(target_dir / f"{_safe_name(arm_cn)}.json", arm)
                kept_at = str(target_dir)
            path.unlink(missing_ok=True)
            return {"ok": True, "arm_cn": arm_cn, "mode": mode, "kept_at": kept_at}

    def arm_wizard_status(self, arm_cn: str) -> Dict[str, Any]:
        """Where this arm stands: which steps are done, which is next, what blocks it."""
        with self._lock:
            try:
                _path, arm = self._load_arm_record(arm_cn)
            except KeyError:
                return self._wizard_problem("arm_not_found", f"arm_cn={arm_cn}")
            product_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
            gate = self.factory_release_gate(arm_cn)
            done = self._arm_wizard_completed_steps(arm, gate)

            # An arm that already cleared the release gate is finished, whatever traces
            # its individual steps left. TIMEOUT standardization and the low-gain enable
            # check wrote nothing to the arm record before 0.16.0, so the three arms
            # already shipped have no evidence of them - pointing an operator at those
            # steps would have them redo a Flash write on a passed arm.
            released = gate["release_decision"] == "PASS"

            steps = []
            next_step = None
            for step in self.ARM_WIZARD_STEPS:
                view = self._arm_wizard_step_view(step, product_version)
                view["done"] = step["id"] in done
                if not view["applies"]:
                    view["state"] = "skipped"
                elif view["done"]:
                    view["state"] = "done"
                elif view["locked"]:
                    view["state"] = "locked"
                elif released:
                    view["state"] = "no_record"
                elif next_step is None:
                    view["state"] = "current"
                    next_step = step["id"]
                else:
                    view["state"] = "pending"
                steps.append(view)

            evidence = self._arm_evidence_count(arm)
            return {
                "ok": True,
                "arm_cn": arm_cn,
                "product_version": product_version,
                "product_label": self.product_registry.get(product_version)["label"],
                "groups": [dict(group) for group in self.ARM_WIZARD_GROUPS],
                "evidence_count": evidence,
                # Only an archive with nothing in it can be discarded; once a test has
                # recorded anything against this arm, that evidence is the record.
                "deletable": evidence == 0,
                "arm_type": arm.get("arm_type"),
                "steps": steps,
                "next_step": next_step,
                "release_decision": gate["release_decision"],
                "blocking_items": gate["blocking_items"],
                "warning_items": gate["warning_items"],
                "motor_records": self._arm_attached_motor_records(arm),
            }

    def _arm_wizard_completed_steps(self, arm: Dict[str, Any], gate: Dict[str, Any]) -> set:
        """Which steps this arm already has evidence for.

        Read from the evidence that is already on record, so an arm tested through the
        engineer tools before this wizard existed shows its real progress rather than
        starting from zero.
        """
        done = {"identity"}
        linked = gate["evidence"]["linked_jobs"]
        if any(item.get("status") == "passed" for item in linked):
            done.add("link")
            done.add("static")
        if any(record.get("status") == "passed" for record in arm.get("zero_calibration_records") or []):
            done.add("zero")
        demo_records = arm.get("demo_validation_records") or []
        if any(record.get("status") == "passed" for record in demo_records):
            done.add("demo")
            done.add("gripper")
        for run in arm.get("command_run_history") or []:
            if run.get("kind") == "arm_timeout_standardization" and run.get("status") == "passed":
                done.add("timeout")
            if run.get("kind") == "arm_safe_enable_check" and run.get("status") == "passed":
                done.add("enable")
        if gate["release_decision"] == "PASS":
            done.add("gate")
        if arm.get("factory_reports"):
            done.add("report")
        return done

    def _arm_attached_motor_records(self, arm: Dict[str, Any]) -> List[Dict[str, Any]]:
        attached = arm.get("single_motor_records") or []
        return [
            {
                "record_id": item.get("record_id"),
                "joint_name": item.get("joint_name"),
                "motor_type": item.get("motor_type"),
                "result": item.get("result"),
                # When the motor was commissioned, as opposed to when it was linked to
                # this arm. The page shows the former: that is the evidence date.
                "created_at": item.get("commissioned_at"),
                "attached_at": item.get("attached_at"),
            }
            for item in attached
        ]

    def arm_wizard_attach_motor_record(self, arm_cn: str, record_id: str) -> Dict[str, Any]:
        """Attach one commissioned motor's record to a joint of this arm.

        The 16 motors configured on 2026-09-17 are the only evidence that each was set
        up and read back on hardware, and that evidence has to reach the arm's report.
        Damiao's SN register is not unique across motors, so the record id is the key,
        never the SN.
        """
        with self._lock:
            try:
                path, arm = self._load_arm_record(arm_cn)
            except KeyError:
                return self._wizard_problem("arm_not_found", f"arm_cn={arm_cn}")

            record = next(
                (item for item in self._load_single_motor_records() if item.get("record_id") == record_id),
                None,
            )
            if record is None:
                return self._wizard_problem("arm_motor_record_mismatch", f"record_id={record_id} not found")

            arm_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
            record_version = str(record.get("product_line") or DEFAULT_PRODUCT_VERSION)
            if record_version != arm_version:
                return self._wizard_problem(
                    "arm_motor_record_mismatch",
                    f"记录属于 {record_version}，这台臂是 {arm_version}",
                )
            if record.get("result") != "PASS":
                return self._wizard_problem(
                    "arm_motor_record_mismatch", f"记录结果是 {record.get('result')}，只有 PASS 的记录可以挂载"
                )

            joint_name = str(record.get("joint_name") or "")
            attached = [item for item in (arm.get("single_motor_records") or []) if item.get("joint_name") != joint_name]
            attached.append(
                {
                    "record_id": record_id,
                    "joint_name": joint_name,
                    "arm_side": record.get("arm_side"),
                    "motor_type": record.get("motor_type"),
                    "result": record.get("result"),
                    "product_version": record_version,
                    "commissioned_at": record.get("created_at"),
                    "attached_at": _now_iso(),
                }
            )
            arm["single_motor_records"] = sorted(attached, key=lambda item: str(item.get("joint_name")))
            arm["updated_at"] = _now_iso()
            _atomic_json(path, arm)
            return {"ok": True, "arm_cn": arm_cn, "attached": arm["single_motor_records"]}

    def arm_wizard_available_motor_records(self, arm_cn: str) -> Dict[str, Any]:
        """The commissioned motors that could belong to this arm, newest first."""
        with self._lock:
            try:
                _path, arm = self._load_arm_record(arm_cn)
            except KeyError:
                return self._wizard_problem("arm_not_found", f"arm_cn={arm_cn}")
            arm_version = str(arm.get("product_version") or DEFAULT_PRODUCT_VERSION)
            taken = {item.get("record_id") for item in (arm.get("single_motor_records") or [])}
            candidates = [
                {
                    "record_id": record.get("record_id"),
                    "joint_name": record.get("joint_name"),
                    "arm_side": record.get("arm_side"),
                    "motor_type": record.get("motor_type"),
                    "created_at": record.get("created_at"),
                    "attached": record.get("record_id") in taken,
                }
                for record in self._load_single_motor_records()
                if str(record.get("product_line") or DEFAULT_PRODUCT_VERSION) == arm_version
                and record.get("result") == "PASS"
            ]
            return {
                "ok": True,
                "arm_cn": arm_cn,
                "product_version": arm_version,
                "records": sorted(candidates, key=lambda item: str(item.get("joint_name"))),
            }

    def link_wizard_detect(self) -> Dict[str, Any]:
        """Step 1: list the CAN ports this machine has, with beginner-readable health."""
        with self._lock:
            payload = self.system_can_interfaces()
            interfaces = payload.get("interfaces") or []
            if not interfaces:
                return self._wizard_problem("adapter_missing", "no socketcan interface in /sys/class/net")
            return {
                "ok": True,
                "interfaces": [self._link_interface_view(item) for item in interfaces],
                "recommended_channel": payload.get("recommended_channel"),
                "detected_at": _now_iso(),
            }

    def link_wizard_prepare(self, channel: str = "can0", mode: str = "can20", bitrate: int = 1000000, dbitrate: Optional[int] = None) -> Dict[str, Any]:
        """Step 2: configure the port to the requested mode/bitrate and bring it up."""
        with self._lock:
            try:
                self._require_interface(channel)
            except Exception as error:
                return self._wizard_problem("can_interface_missing", str(error))
            try:
                self.configure_can_interface(name=channel, mode=mode, bitrate=int(bitrate), dbitrate=dbitrate, fd_enabled=mode == "canfd")
                self.can_interface_up(channel)
            except Exception as error:
                return self._wizard_problem("interface_prepare_failed", str(error))
            iface = self._interface_snapshot(channel)
            can_state = str(iface.get("can_state") or "").upper()
            if can_state in {"BUS-OFF", "ERROR-PASSIVE"}:
                return self._wizard_problem("can_bus_error", f"can_state={can_state}")
            return {"ok": True, "interface": self._link_interface_view(iface), "prepared_at": _now_iso()}

    def link_wizard_connect(self, channel: str = "can0", bitrate: int = 1000000) -> Dict[str, Any]:
        """Step 3: open the workstation device session on the prepared port."""
        with self._lock:
            problem = self._wizard_can_precheck(channel, int(bitrate))
            if problem:
                return problem
            try:
                session = self._wizard_session(channel, int(bitrate))
            except Exception as error:
                return self._wizard_problem("connect_failed", str(error))
            return {
                "ok": True,
                "device_session_id": session.session_id,
                "channel": channel,
                "bitrate": int(bitrate),
                "capabilities": asdict(session.capabilities),
                "interface": self._link_interface_view(self._interface_snapshot(channel)),
                "connected_at": _now_iso(),
            }

    def link_wizard_bus_check(self, channel: str = "can0", bitrate: int = 1000000) -> Dict[str, Any]:
        """Step 4: read-only bus inventory so the operator sees who answers before any test."""
        with self._lock:
            problem = self._wizard_can_precheck(channel, int(bitrate))
            if problem:
                return problem
            try:
                session, candidates, duplicate_ids, _ = self._wizard_scan(channel, int(bitrate), DEFAULT_ARM_SCAN_IDS)
            except WizardConnectError as error:
                return self._wizard_problem("connect_failed", str(error))
            if not candidates:
                return self._wizard_problem("bus_no_motor", f"channel={channel}")
            motors = []
            for candidate in candidates:
                params = candidate.get("params") or {}
                status = candidate.get("status") or {}
                motors.append(
                    {
                        "esc_id": candidate.get("detected_esc_id"),
                        "mst_id": candidate.get("detected_mst_id"),
                        "matched_joints": self._joints_matching_ids(params.get("ESC_ID"), params.get("MST_ID")),
                        "factory_default_ids": int(params.get("MST_ID") or 0) == 0,
                        "status": status.get("status"),
                        "has_error": bool(status.get("has_error")),
                        "t_mos": status.get("t_mos"),
                        "t_rotor": status.get("t_rotor"),
                    }
                )
            faulted = [item["esc_id"] for item in motors if item["has_error"]]
            return {
                "ok": True,
                "read_only": True,
                "channel": channel,
                "scanned_range": "0x01-0x20",
                "motors": motors,
                "duplicate_esc_ids": sorted(duplicate_ids),
                "faulted_esc_ids": faulted,
                "checked_at": _now_iso(),
            }

    def link_wizard_disconnect(self, channel: str = "can0") -> Dict[str, Any]:
        with self._lock:
            closed = []
            for session in list(self.sessions.values()):
                if session.transport == "socketcan" and session.connection.get("channel") == channel and session.connection_state != "disconnected":
                    self.disconnect_device(session.session_id)
                    closed.append(session.session_id)
            return {"ok": True, "closed_sessions": closed}

    def _link_interface_view(self, iface: Dict[str, Any]) -> Dict[str, Any]:
        state = str(iface.get("state") or "").upper()
        can_state = str(iface.get("can_state") or "").upper()
        # Any adapter Linux exposes as SocketCAN works here; the driver is shown as
        # information, not as a requirement.
        healthy = state == "UP" and can_state == "ERROR-ACTIVE"
        if state != "UP":
            health_text = "未启动"
        elif can_state and can_state != "ERROR-ACTIVE":
            health_text = f"总线状态 {can_state}"
        else:
            health_text = "正常"
        return {
            **iface,
            "healthy": healthy,
            "health_text": health_text,
            "bitrate_text": f"{int(iface['bitrate']) / 1000000:g} Mbps" if iface.get("bitrate") else "未设置",
            "mode_text": "CAN FD" if iface.get("fd_enabled") else "CAN 2.0",
        }

    def single_motor_inspect(self, channel: str = "can0", bitrate: int = 1000000) -> Dict[str, Any]:
        """Read-only view of every motor answering on one CAN port.

        Sends parameter reads and status refreshes only: no enable, no parameter
        write, no Flash save, no zero. Safe to run at any time, including on an
        already commissioned motor.
        """
        with self._lock:
            problem = self._wizard_can_precheck(channel, int(bitrate))
            if problem:
                return problem
            try:
                session, candidates, duplicate_ids, _ = self._wizard_scan(channel, int(bitrate), DEFAULT_ARM_SCAN_IDS)
            except WizardConnectError as error:
                return self._wizard_problem("connect_failed", str(error))

            if not candidates:
                return self._wizard_problem("no_motor_found")

            motors = []
            for candidate in candidates:
                motor = self._motor_from_candidate(candidate)
                params = self._read_params(session, motor, SINGLE_INSPECT_RIDS, ignore_errors=True)
                status = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                motors.append(
                    {
                        "esc_id": params.get("ESC_ID") if params.get("ESC_ID") is not None else candidate.get("detected_esc_id"),
                        "mst_id": params.get("MST_ID") if params.get("MST_ID") is not None else candidate.get("detected_mst_id"),
                        "matched_joints": self._joints_matching_ids(params.get("ESC_ID"), params.get("MST_ID")),
                        "factory_default_ids": int(params.get("MST_ID") or 0) == 0,
                        "model_check": _infer_motor_model(params, None),
                        "rows": self._inspect_rows(params),
                        "raw_params": params,
                        "status": status,
                    }
                )
            return {
                "ok": True,
                "read_only": True,
                "channel": channel,
                "bitrate": int(bitrate),
                "scanned_range": "0x01-0x20",
                "duplicate_esc_ids": sorted(duplicate_ids),
                "inspected_at": _now_iso(),
                "motors": motors,
            }

    def _inspect_rows(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = []
        for field, _rid, label, group in SINGLE_INSPECT_FIELDS:
            value = params.get(field)
            rows.append(
                {
                    "field": field,
                    "label": label,
                    "group": group,
                    "value": value,
                    "display": self._inspect_display(field, value),
                }
            )
        return rows

    def _inspect_display(self, field: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        if field in {"ESC_ID", "MST_ID"}:
            return f"0x{int(value):02X}（{int(value)}）"
        if field == "CTRL_MODE":
            return f"{_control_name(value)}（{int(value)}）"
        if field == "can_br":
            # Motors answer with the register code (e.g. 4); some drivers already decode it.
            bitrate = _normalize_can_br(value)
            if not bitrate:
                return str(value)
            decoded = f"{bitrate / 1000000:g} Mbps"
            return decoded if int(value) == int(bitrate) else f"{decoded}（代码 {int(value)}）"
        if field == "TIMEOUT":
            return "0（未启用）" if int(value) == 0 else str(int(value))
        return str(value)

    def _wizard_problem(self, code: str, detail: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        meta = SINGLE_MOTOR_PROBLEMS.get(code) or SINGLE_MOTOR_PROBLEMS["unknown_error"]
        return {
            "ok": False,
            "problem": {
                "code": code,
                **meta,
                "blocking": code in BLOCKING_PROBLEM_CODES,
                "detail": detail,
                **extra,
            },
        }

    def _wizard_error_code(self, error: Exception, default: str) -> str:
        text = str(error).lower()
        if "disable" in text:
            return "disable_failed"
        if "failed to write" in text:
            return "write_failed"
        if "save flash" in text:
            return "save_failed"
        if "requires" in text and "state" in text:
            return "job_state_invalid"
        return default

    def _wizard_can_precheck(self, channel: str, bitrate: int) -> Optional[Dict[str, Any]]:
        interfaces = {item["name"]: item for item in self._list_socketcan_interfaces()}
        iface = interfaces.get(channel)
        if iface is None:
            return self._wizard_problem("can_interface_missing", f"{channel} not in {sorted(interfaces)}")
        state = str(iface.get("state") or "").upper()
        can_state = str(iface.get("can_state") or "").upper()
        needs_restart = state != "UP" or int(iface.get("bitrate") or 0) != int(bitrate) or can_state in {"BUS-OFF", "STOPPED"}
        if needs_restart:
            self._invalidate_socketcan_sessions(channel)
            try:
                for cmd in (
                    ["ip", "link", "set", channel, "down"],
                    ["ip", "link", "set", channel, "type", "can", "bitrate", str(int(bitrate))],
                    ["ip", "link", "set", channel, "up"],
                ):
                    self._run_system_command(["sudo", "-n", *cmd])
            except Exception as error:
                return self._wizard_problem("can_interface_down", str(error))
            iface = self._interface_snapshot(channel)
            can_state = str(iface.get("can_state") or "").upper()
        if can_state in {"BUS-OFF", "ERROR-PASSIVE"}:
            return self._wizard_problem("can_bus_error", f"can_state={can_state}")
        return None

    def _interface_ifindex(self, name: str) -> Optional[int]:
        raw = self._safe_read_text(Path("/sys/class/net") / name / "ifindex")
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    def _invalidate_socketcan_sessions(self, channel: str) -> int:
        """Close every open socketcan session bound to ``channel``.

        A socket opened before the link went down keeps answering "nothing on the
        bus" after it comes back, which reads exactly like a dead motor and sends
        the operator hunting for power or wiring faults. Anything that restarts the
        link closes the sockets first so the next step reconnects for real.
        """
        closed = 0
        for session in self.sessions.values():
            if (
                session.transport == "socketcan"
                and session.connection_state != "disconnected"
                and session.connection.get("channel") == channel
            ):
                try:
                    session.driver.disconnect()
                except Exception:
                    pass
                session.connection_state = "disconnected"
                closed += 1
        return closed

    def _reusable_socketcan_session(self, channel: str, bitrate: int) -> Optional[DeviceSession]:
        live_ifindex = self._interface_ifindex(channel)
        for session in self.sessions.values():
            if not (
                session.transport == "socketcan"
                and session.connection_state != "disconnected"
                and session.connection.get("channel") == channel
                and int(session.connection.get("bitrate", 0)) == int(bitrate)
            ):
                continue
            bound_ifindex = session.connection.get("ifindex")
            if live_ifindex is not None and bound_ifindex is not None and int(bound_ifindex) != int(live_ifindex):
                # The adapter was unplugged and replugged: the socket is bound to an
                # interface that no longer exists.
                self._invalidate_socketcan_sessions(channel)
                return None
            return session
        return None

    def _wizard_session_ex(self, channel: str, bitrate: int, *, force_new: bool = False) -> Tuple[DeviceSession, bool]:
        """Return the wizard session for ``channel`` plus whether it was reused."""
        if force_new:
            self._invalidate_socketcan_sessions(channel)
        else:
            session = self._reusable_socketcan_session(channel, int(bitrate))
            if session is not None:
                return session, True
        try:
            payload = self.connect_device("socketcan", {"channel": channel, "bitrate": int(bitrate)})
        except Exception as error:
            raise WizardConnectError(str(error)) from error
        session = self._session(payload["device_session_id"])
        session.connection["ifindex"] = self._interface_ifindex(channel)
        return session, False

    def _wizard_session(self, channel: str, bitrate: int, *, force_new: bool = False) -> DeviceSession:
        session, _ = self._wizard_session_ex(channel, int(bitrate), force_new=force_new)
        return session

    def _wizard_scan(
        self, channel: str, bitrate: int, scan_ids: List[int]
    ) -> Tuple[DeviceSession, List[Dict[str, Any]], List[int], bool]:
        """Inventory-scan the bus, rebuilding a reused session once if nobody answers.

        An empty scan on a session we did not just open is ambiguous: the motor may
        be off, or our socket may have gone deaf behind an interface restart we did
        not make. Reconnecting once rules out the second case before we blame the
        hardware. Returns ``(session, candidates, duplicate_ids, reconnected)``.
        """
        session, reused = self._wizard_session_ex(channel, int(bitrate))
        candidates, duplicate_ids = self._inventory_scan(session, scan_ids)
        if candidates or not reused:
            return session, candidates, duplicate_ids, False
        session, _ = self._wizard_session_ex(channel, int(bitrate), force_new=True)
        candidates, duplicate_ids = self._inventory_scan(session, scan_ids)
        return session, candidates, duplicate_ids, True

    def single_wizard_identify(
        self,
        channel: str = "can0",
        bitrate: int = 1000000,
        arm_side: str = "right_arm",
        joint: str = "J1",
        product_line: str = "openarm_2_0",
    ) -> Dict[str, Any]:
        with self._lock:
            if arm_side not in SINGLE_WIZARD_ARM_PROFILES:
                raise ValueError("arm_side must be right_arm or left_arm")
            if product_line not in SINGLE_WIZARD_PRODUCT_LINES:
                raise ValueError("unsupported product_line")
            arm_meta = SINGLE_WIZARD_ARM_PROFILES[arm_side]
            profile_id = arm_meta["profile_id"]
            joint_name = f"{arm_meta['prefix']}-{joint}"
            self.profile_manager.get_joint(profile_id, joint_name)

            problem = self._wizard_can_precheck(channel, int(bitrate))
            if problem:
                return problem
            try:
                session, candidates, duplicate_ids, _ = self._wizard_scan(channel, int(bitrate), DEFAULT_ARM_SCAN_IDS)
            except WizardConnectError as error:
                return self._wizard_problem("connect_failed", str(error))

            if not candidates:
                return self._wizard_problem("no_motor_found")
            if len(candidates) > 1 or duplicate_ids:
                found = sorted(int(item["detected_esc_id"]) for item in candidates)
                return self._wizard_problem("multiple_motors", f"found ESC_IDs {found}", found_esc_ids=found)
            session.last_scan = {
                "candidates": candidates,
                "conflicts": [],
                "summary": {"detected": 1, "conflicts": 0, "passed": True},
                "scan_mode": "single_safe_scan",
            }
            status = candidates[0].get("status") or {}
            if status.get("has_error"):
                return self._wizard_problem("motor_fault", f"status={status.get('status')}")
            if str(status.get("status", "")).startswith("UNKNOWN"):
                return self._wizard_problem("status_read_anomaly", f"status={status.get('status')}")
            if float(status.get("t_mos") or 0.0) >= TEMP_LIMITS["mos"] or float(status.get("t_rotor") or 0.0) >= TEMP_LIMITS["rotor"]:
                return self._wizard_problem("motor_overtemp", f"t_mos={status.get('t_mos')} t_rotor={status.get('t_rotor')}")

            created = self.create_job("single_id_config", session.session_id, profile_id, joint_name)
            job = self._job(created["job_id"])
            job.product_line = product_line
            try:
                applied = self.apply_profile(job.job_id, joint_name, profile_id)
            except Exception as error:
                self._fail_job(job, f"识别后读取参数失败: {error}")
                return self._wizard_problem("write_failed" if "write" in str(error).lower() else "unknown_error", str(error))
            return {"ok": True, **self._single_wizard_state(job)}

    def _single_wizard_state(self, job: JobRecord) -> Dict[str, Any]:
        motor_payload = job.motors.get("commissioned_motor", {})
        current = motor_payload.get("current", {}) or {}
        params = current.get("params", {}) or {}
        status = current.get("status", {}) or {}
        target = job.target_config
        rows = []
        for field_name, target_key in (("ESC_ID", "target_esc_id"), ("MST_ID", "target_mst_id"), ("CTRL_MODE", "target_ctrl_mode"), ("can_br", "target_can_br")):
            current_value = params.get(field_name)
            target_value = target.get(target_key)
            if field_name == "CTRL_MODE" and current_value is not None:
                display_current = _control_name(current_value)
                same = display_current == _control_name(target_value)
            elif field_name == "can_br" and current_value is not None:
                display_current = _normalize_can_br(current_value)
                same = display_current == _normalize_can_br(target_value)
            else:
                display_current = current_value
                same = current_value is not None and int(current_value) == int(target_value)
            rows.append({"field": field_name, "current": display_current, "target": target_value, "changes": not same, "written": True})
        rows.append({"field": "TIMEOUT", "current": params.get("TIMEOUT"), "target": "只记录", "changes": False, "written": False})
        joint_name = target.get("joint_name") or job.target_joint
        # Motors have no unique readable serial, so "already configured" is judged from the IDs the motor carries now.
        configured_as = self._joints_matching_ids(params.get("ESC_ID"), params.get("MST_ID"))
        joint_taken_by = []
        if joint_name not in configured_as:
            joint_taken_by = [
                {"record_id": item.get("record_id"), "created_at": item.get("created_at")}
                for item in self._load_single_motor_records()
                if item.get("result") == "PASS"
                and item.get("joint_name") == joint_name
                and item.get("product_line") == job.product_line
            ][:1]
        return {
            "job_id": job.job_id,
            "status": job.status,
            "model_check": _infer_motor_model(params, target.get("motor_type")),
            "joint_taken_by": joint_taken_by,
            "joint_name": joint_name,
            "motor_type": target.get("motor_type"),
            "product_line": job.product_line,
            "configured_as": configured_as,
            "factory_default_ids": params.get("MST_ID") == 0,
            "motor": {
                "firmware": params.get("sw_ver"),
                "status": status.get("status"),
                "t_mos": status.get("t_mos"),
                "t_rotor": status.get("t_rotor"),
            },
            "param_rows": rows,
            "needs_write": any(row["changes"] for row in rows),
        }

    def single_wizard_write(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            if job.status != "profile_selected":
                return self._wizard_problem("job_state_invalid", f"status={job.status}")
            try:
                self.write_params(job_id, dict(job.target_config))
            except Exception as error:
                if job.status != "failed":
                    self._fail_job(job, f"参数写入失败: {error}")
                return self._wizard_problem(self._wizard_error_code(error, "write_failed"), str(error))
            try:
                verification = self.verify_params(job_id)
            except Exception as error:
                if job.status != "failed":
                    self._fail_job(job, f"参数回读失败: {error}")
                return self._wizard_problem("param_mismatch", str(error))
            if not verification["verified"]:
                return self._wizard_problem("param_mismatch", None, mismatches=verification["mismatches"])
            return {"ok": True, **self._single_wizard_state(job)}

    def single_wizard_save(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            if job.status != "params_verified":
                return self._wizard_problem("job_state_invalid", f"status={job.status}")
            try:
                self.save_flash(job_id)
            except Exception as error:
                return self._wizard_problem(self._wizard_error_code(error, "save_failed"), str(error))
            return {"ok": True, **self._single_wizard_state(job)}

    def single_wizard_finish(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            if job.job_type != "single_id_config" or job.status != "params_saved":
                return self._wizard_problem("job_state_invalid", f"status={job.status}")
            session = self._session(job.device_session_id)
            motor = self._motor_from_candidate(job.candidate)
            probe = self._read_params(session, motor, [DM_variable.ESC_ID], ignore_errors=True)
            if probe.get("ESC_ID") is None:
                # Motor may still be booting after the power cycle; keep the job retryable.
                return self._wizard_problem("readback_no_response", f"ESC_ID {motor.SlaveID} did not answer")
            result = self.test(job_id, confirmed=True)
            metrics = result["metrics"]
            if not result["tested"]:
                issues = metrics.get("issues", [])
                if "motor_error" in issues:
                    code = "motor_fault"
                elif "mos_overtemp" in issues or "rotor_overtemp" in issues:
                    code = "motor_overtemp"
                elif "motor_enabled" in issues:
                    code = "disable_failed"
                else:
                    code = "readback_mismatch"
                return self._wizard_problem(code, None, mismatches=metrics.get("mismatches", []), record=result.get("record"))
            return {"ok": True, **self._single_wizard_state(job), "record": result.get("record")}

    def _session(self, session_id: str) -> DeviceSession:
        if session_id not in self.sessions:
            raise KeyError("session not found")
        return self.sessions[session_id]

    def _job(self, job_id: str) -> JobRecord:
        if job_id not in self.jobs:
            raise KeyError("job not found")
        return self.jobs[job_id]

    def _allowed_actions(self, job: JobRecord) -> List[str]:
        session = self._session(job.device_session_id)
        actions = []
        if job.job_type == "single_id_config":
            if job.status == "device_connected":
                actions.append("apply_profile")
            if job.status == "profile_selected" and session.capabilities.write_params:
                actions.append("write_params")
            if job.status == "params_written":
                actions.append("verify_params")
            if job.status == "params_verified" and session.capabilities.save_flash:
                actions.append("save_flash")
            if job.status == "params_saved" and job.expert_mode and session.capabilities.zero:
                actions.append("zero")
            if job.status == "params_saved":
                actions.append("test")
            if job.status == "zeroed" and session.capabilities.test:
                actions.append("test")
            if job.status in ["device_connected", "profile_selected", "params_written", "params_verified", "params_saved"] and session.capabilities.communication_check:
                actions.append("run_comm_check")
        elif job.job_type == "single_param_config":
            if job.status == "device_connected":
                actions.append("apply_profile")
            if job.status == "profile_selected" and session.capabilities.write_params:
                actions.append("write_params")
            if job.status == "params_written":
                actions.append("verify_params")
            if job.status == "params_verified" and session.capabilities.save_flash:
                actions.append("save_flash")
            if job.status == "params_saved":
                actions.append("test")
        elif job.job_type == "single_comm_check" and job.status == "device_connected":
            actions.append("run_comm_check")
        elif job.job_type == "arm_comm_scan" and job.status == "device_connected":
            actions.append("run_arm_scan")
        elif job.job_type == "arm_acceptance" and job.status == "device_connected":
            actions.append("run_arm_acceptance")
        return actions

    def _scan_single(self, session: DeviceSession, current_id: Optional[int]) -> List[Dict[str, Any]]:
        ids = [current_id] if current_id else DEFAULT_SCAN_IDS
        candidates, _ = self._inventory_scan(session, ids)
        if not candidates:
            cached_inventory = session.last_inventory.get("payload", {}).get("inventory", [])
            if current_id:
                candidates = [
                    item
                    for item in cached_inventory
                    if int(item.get("current_id", -1)) == int(current_id)
                    or int(item.get("detected_esc_id", -1)) == int(current_id)
                ]
            elif cached_inventory:
                candidates = list(cached_inventory)
        return candidates

    def _inventory_scan(self, session: DeviceSession, ids: Iterable[int]) -> tuple[List[Dict[str, Any]], List[int]]:
        seen = set()
        candidates = []
        duplicate_esc_ids = set()
        inventory_by_esc: Dict[int, Dict[str, Any]] = {}
        for candidate_id in ids:
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            # OpenARM factory profiles use Receiver/Master ID = ESC_ID + 0x10.
            # Left-arm L-J8 has ESC_ID 0x10 and MST_ID 0x20; keeping MasterID
            # equal to candidate_id for IDs >= 0x10 makes scans miss that joint.
            motor = Motor(DM_Motor_Type.DM4310, candidate_id, candidate_id + 0x10)
            timeout = getattr(session.driver, "fast_param_read_timeout", 0.15)
            params = self._read_params(session, motor, FAST_SCAN_RIDS, ignore_errors=True, timeout=timeout)
            if params["ESC_ID"] is None and params["MST_ID"] is None:
                continue
            snapshot = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            detected_esc_id = int(params["ESC_ID"] or candidate_id)
            candidate = {
                "current_id": candidate_id,
                "detected_esc_id": detected_esc_id,
                "detected_mst_id": params["MST_ID"],
                "params": params,
                "status": snapshot,
            }
            if detected_esc_id in inventory_by_esc:
                duplicate_esc_ids.add(detected_esc_id)
                continue
            inventory_by_esc[detected_esc_id] = candidate
            candidates.append(candidate)
        return candidates, sorted(duplicate_esc_ids)

    def _expected_matrix_value(self, joint: Dict[str, Any], field_name: str, target_key: str) -> Any:
        value = joint.get(target_key)
        if value is None:
            return None
        if field_name == "CTRL_MODE":
            return int(_control_from_value(value))
        if field_name == "can_br":
            return _normalize_can_br(value)
        if field_name in {"Gr", "KT_Value", "PMAX", "VMAX", "TMAX"}:
            return float(value)
        return int(value)

    def _build_consistency_matrix(self, joint: Dict[str, Any], params: Dict[str, Any]) -> List[Dict[str, Any]]:
        matrix = []
        for field_name, target_key in ARM_MATRIX_FIELDS:
            actual = params.get(field_name)
            expected = self._expected_matrix_value(joint, field_name, target_key)
            if field_name == "CTRL_MODE" and actual is not None:
                actual = int(actual)
            if field_name == "can_br" and actual is not None:
                actual = _normalize_can_br(actual)
            if field_name in {"Gr", "KT_Value", "PMAX", "VMAX", "TMAX"} and actual is not None:
                actual = float(actual)
            matches = None
            if expected is not None and actual is not None:
                if isinstance(expected, float):
                    matches = abs(float(actual) - expected) <= 1e-6
                else:
                    matches = int(actual) == int(expected)
            matrix.append({"field": field_name, "actual": actual, "expected": expected, "matches": matches})
        return matrix

    def _scan_arm_with_stability(
        self,
        session: DeviceSession,
        profile_id: str,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
    ) -> Dict[str, Any]:
        runs = []
        for index in range(repeat_count):
            runs.append(self._scan_arm(session, profile_id))
            if index < repeat_count - 1 and repeat_delay_ms > 0:
                time.sleep(repeat_delay_ms / 1000.0)
        final_scan = runs[-1]
        if repeat_count <= 1:
            final_scan["summary"]["stability"] = {
                "repeat_count": 1,
                "stable_joint_count": len(final_scan["results"]),
                "flaky_joint_count": 0,
                "flaky_joints": [],
                "presence_flaky_joints": [],
                "parameter_flaky_joints": [],
            }
            for item in final_scan["results"]:
                item["stability"] = {
                    "repeat_count": 1,
                    "stable": True,
                    "present_count": 1 if item["present"] else 0,
                    "presence_changed": False,
                    "parameter_changed_fields": [],
                    "issue_variants": [item["issues"]],
                }
            return final_scan

        runs_by_joint = [{item["joint_name"]: item for item in run["results"]} for run in runs]
        flaky_joints = []
        presence_flaky_joints = []
        parameter_flaky_joints = []
        stable_joint_count = 0
        for final_item in final_scan["results"]:
            joint_name = final_item["joint_name"]
            observed_items = [run[joint_name] for run in runs_by_joint]
            present_values = [bool(item["present"]) for item in observed_items]
            presence_changed = len(set(present_values)) > 1
            parameter_changed_fields = []
            issue_variants = []
            for field_name, _target_key in ARM_MATRIX_FIELDS:
                observed_values = []
                for item in observed_items:
                    value = item.get("params", {}).get(field_name)
                    if field_name in {"Gr", "KT_Value", "PMAX", "VMAX", "TMAX"} and value is not None:
                        value = round(float(value), 6)
                    observed_values.append(value)
                if len(set(observed_values)) > 1:
                    parameter_changed_fields.append(field_name)
            for item in observed_items:
                issue_variant = tuple(sorted(item.get("issues", [])))
                if issue_variant not in issue_variants:
                    issue_variants.append(issue_variant)
            stable = not presence_changed and not parameter_changed_fields and len(issue_variants) == 1
            if stable:
                stable_joint_count += 1
            else:
                flaky_joints.append(joint_name)
            if presence_changed:
                presence_flaky_joints.append(joint_name)
            if parameter_changed_fields:
                parameter_flaky_joints.append(joint_name)
            final_item["stability"] = {
                "repeat_count": repeat_count,
                "stable": stable,
                "present_count": sum(1 for value in present_values if value),
                "presence_changed": presence_changed,
                "parameter_changed_fields": parameter_changed_fields,
                "issue_variants": [list(item) for item in issue_variants],
            }

        final_scan["summary"]["stability"] = {
            "repeat_count": repeat_count,
            "stable_joint_count": stable_joint_count,
            "flaky_joint_count": len(flaky_joints),
            "flaky_joints": flaky_joints,
            "presence_flaky_joints": presence_flaky_joints,
            "parameter_flaky_joints": parameter_flaky_joints,
        }
        return final_scan

    def _scan_arm(self, session: DeviceSession, profile_id: str) -> Dict[str, Any]:
        profile = self.profile_manager.get_profile(profile_id)
        expected_ids = {int(joint["target_esc_id"]) for joint in profile["joints"]}
        scan_ids = sorted(expected_ids)
        inventory, duplicate_esc_ids = self._inventory_scan(session, scan_ids)
        cached_inventory = session.last_inventory.get("payload", {}).get("inventory", [])
        cached_profile_id = session.last_inventory.get("profile_id")
        if not inventory and cached_inventory and cached_profile_id in {None, profile_id}:
            inventory = [item for item in cached_inventory if int(item.get("detected_esc_id", -1)) in expected_ids]
            duplicate_esc_ids = list(session.last_inventory.get("payload", {}).get("summary", {}).get("duplicate_esc_ids", []))
        discovered_by_esc = {int(item["detected_esc_id"]): item for item in inventory}
        results = []
        missing = []
        unhealthy = []
        mismatches = []
        bitrate_mismatches = []
        ctrl_mode_mismatches = []
        bus_mismatches = []
        matrix_mismatch_joints = []
        total_present = 0
        total_comm_ok = 0
        status_read_anomalies = []
        active_channel = session.connection.get("channel")
        for joint in profile["joints"]:
            expected_esc_id = int(joint["target_esc_id"])
            expected_mst_id = int(joint["target_mst_id"])
            discovered = discovered_by_esc.get(expected_esc_id)
            motor = Motor(
                _motor_type_from_name(joint["motor_type"]),
                expected_esc_id,
                int(discovered.get("detected_mst_id") or expected_mst_id) if discovered else expected_mst_id,
            )
            params = {rid.name: None for rid in ARM_VERIFY_RIDS}
            if discovered:
                params["ESC_ID"] = discovered.get("params", {}).get("ESC_ID") or discovered.get("detected_esc_id")
                params["MST_ID"] = discovered.get("params", {}).get("MST_ID") or discovered.get("detected_mst_id")
                detail_timeout = getattr(session.driver, "arm_scan_param_read_timeout", 0.25)
                detailed_params = self._read_params(
                    session,
                    motor,
                    ARM_VERIFY_RIDS,
                    ignore_errors=True,
                    timeout=detail_timeout,
                )
                for key, value in detailed_params.items():
                    if value is not None:
                        params[key] = value
            status = motor.snapshot()
            if discovered:
                fresh_status = self._refresh_and_snapshot(session, motor, ignore_errors=True)
                status = fresh_status if fresh_status.get("last_status_frame") else dict(discovered.get("status") or status)
            status["protocol_motor_type"] = status.get("motor_type")
            status["motor_type"] = joint["motor_type"]
            present = bool(discovered)
            issues = []
            if not present:
                issues.append("missing")
                missing.append(joint["joint_name"])
            else:
                total_present += 1
                actual_mst_id = params.get("MST_ID")
                actual_can_br = params.get("can_br")
                actual_ctrl_mode = params.get("CTRL_MODE")
                if any(params.get(name) is None for name in ARM_REQUIRED_SCAN_FIELDS):
                    issues.append("param_read_failed")
                if actual_mst_id is not None and int(actual_mst_id) != expected_mst_id:
                    issues.append("mst_id_mismatch")
                if actual_can_br is not None and not _can_br_matches(actual_can_br, joint["target_can_br"]):
                    issues.append("can_br_mismatch")
                    bitrate_mismatches.append(joint["joint_name"])
                expected_ctrl_mode = int(_control_from_value(joint.get("expected_ctrl_mode", joint.get("target_ctrl_mode", "MIT"))))
                if actual_ctrl_mode is not None and int(actual_ctrl_mode) != expected_ctrl_mode:
                    issues.append("ctrl_mode_mismatch")
                    ctrl_mode_mismatches.append(joint["joint_name"])
                if active_channel and joint.get("expected_bus") and joint["expected_bus"] != active_channel:
                    issues.append("bus_mismatch")
                    bus_mismatches.append(joint["joint_name"])
                if status["has_error"]:
                    issues.append("motor_error")
                    unhealthy.append(joint["joint_name"])
                elif _status_read_anomaly(status):
                    issues.append("status_read_anomaly")
                    status_read_anomalies.append(joint["joint_name"])
            consistency_matrix = self._build_consistency_matrix(joint, params)
            matrix_mismatch_fields = [row["field"] for row in consistency_matrix if row["matches"] is False]
            if matrix_mismatch_fields:
                matrix_mismatch_joints.append({"joint_name": joint["joint_name"], "fields": matrix_mismatch_fields})
                matrix_issue_names = {
                    "ESC_ID": "esc_id_mismatch",
                    "MST_ID": "mst_id_mismatch",
                    "CTRL_MODE": "ctrl_mode_mismatch",
                    "TIMEOUT": "timeout_mismatch",
                    "can_br": "can_br_mismatch",
                }
                for field_name in matrix_mismatch_fields:
                    issue_name = matrix_issue_names.get(field_name, f"{field_name.lower()}_mismatch")
                    if issue_name not in issues:
                        issues.append(issue_name)
            if issues:
                mismatch_record = {"joint_name": joint["joint_name"], "issues": list(issues)}
                if matrix_mismatch_fields:
                    mismatch_record["matrix_fields"] = matrix_mismatch_fields
                mismatches.append(mismatch_record)
            else:
                total_comm_ok += 1
            results.append(
                {
                    "joint_name": joint["joint_name"],
                    "expected": joint,
                    "present": present,
                    "params": params,
                    "consistency_matrix": consistency_matrix,
                    "status": status,
                    "issues": issues,
                    "comm_ok": present and not issues,
                    "result_label": _motor_result_label(present, issues),
                }
            )
        unexpected = [item for item in inventory if int(item["detected_esc_id"]) not in expected_ids]
        passed = not missing and not unhealthy and not mismatches and not matrix_mismatch_joints and not unexpected and not duplicate_esc_ids
        summary = {
            "total_expected": len(profile["joints"]),
            "total_present": total_present,
            "total_missing": len(missing),
            "total_comm_ok": total_comm_ok,
            "total_unexpected": len(unexpected),
            "total_duplicate_ids": len(duplicate_esc_ids),
            "total_mismatches": len(mismatches),
            "total_faults": len(unhealthy),
            "total_status_read_anomalies": len(status_read_anomalies),
            "missing": missing,
            "unhealthy": unhealthy,
            "status_read_anomalies": status_read_anomalies,
            "mismatches": mismatches,
            "bitrate_mismatches": bitrate_mismatches,
            "ctrl_mode_mismatches": ctrl_mode_mismatches,
            "bus_mismatches": bus_mismatches,
            "matrix_mismatch_joints": matrix_mismatch_joints,
            "unexpected_ids": [int(item["detected_esc_id"]) for item in unexpected],
            "duplicate_esc_ids": duplicate_esc_ids,
            "passed": passed,
        }
        return {
            "results": results,
            "inventory": inventory,
            "missing": missing,
            "unhealthy": unhealthy,
            "mismatches": mismatches,
            "unexpected": unexpected,
            "duplicate_esc_ids": duplicate_esc_ids,
            "passed": passed,
            "summary": summary,
        }

    def _select_single_candidate(self, session: DeviceSession) -> Dict[str, Any]:
        scan = session.last_scan or {}
        candidates = scan.get("candidates", [])
        if not candidates:
            raise ValueError("请先扫描并识别电机")
        if len(candidates) > 1 and scan.get("scan_mode") != "expert":
            raise ValueError("检测到多个候选电机，请进入专家模式")
        return candidates[0]

    def _motor_from_candidate(self, candidate: Dict[str, Any]) -> Motor:
        params = candidate.get("params", {})
        esc_value = next(
            value
            for value in (params.get("ESC_ID"), candidate.get("detected_esc_id"), candidate.get("current_id"))
            if value is not None
        )
        esc_id = int(esc_value)
        mst_value = next(
            (
                value
                for value in (params.get("MST_ID"), candidate.get("detected_mst_id"))
                if value is not None
            ),
            esc_id + 0x10,
        )
        mst_id = int(mst_value)
        motor_type = candidate.get("motor_type", "DM4310")
        return Motor(_motor_type_from_name(motor_type), esc_id, mst_id)

    def _resolve_joint_for_runtime(
        self,
        session: DeviceSession,
        joint_name: str,
        profile_id: str,
        force_inventory: bool = False,
    ) -> Dict[str, Any]:
        profile_joint = dict(self.profile_manager.get_joint(profile_id, joint_name))
        expected_esc_id = int(profile_joint["target_esc_id"])
        expected_mst_id = int(profile_joint["target_mst_id"])

        inventory_payload = session.last_inventory.get("payload", {})
        cached_profile_id = session.last_inventory.get("profile_id")
        inventory_items = inventory_payload.get("inventory", [])
        if force_inventory or not inventory_items or cached_profile_id not in {None, profile_id}:
            inventory_payload = self.line_inventory(session.session_id, profile_id)
            inventory_items = inventory_payload.get("inventory", [])

        discovered = next(
            (item for item in inventory_items if int(item.get("detected_esc_id", -1)) == expected_esc_id),
            None,
        )
        motor = Motor(
            _motor_type_from_name(profile_joint["motor_type"]),
            expected_esc_id,
            int(discovered.get("detected_mst_id") or expected_mst_id) if discovered else expected_mst_id,
        )
        return {
            "expected": profile_joint,
            "present": bool(discovered),
            "candidate": discovered,
            "motor": motor,
        }

    def _build_single_target_config(
        self,
        job_type: str,
        profile_id: Optional[str],
        target_joint: Optional[str],
        candidate: Dict[str, Any],
        current_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        profile_joint = None
        if profile_id and target_joint:
            profile_joint = dict(self.profile_manager.get_joint(profile_id, target_joint))
        elif profile_id:
            try:
                profile = self.profile_manager.get_profile(profile_id)
                detected_esc = int(current_params.get("ESC_ID") or candidate.get("detected_esc_id") or candidate.get("current_id"))
                profile_joint = next((dict(joint) for joint in profile["joints"] if int(joint["target_esc_id"]) == detected_esc), None)
            except Exception:
                profile_joint = None

        base = profile_joint or {
            "joint_name": target_joint or "-",
            "motor_type": _official_motor_type_map().get(target_joint or "", "DM-J4310-2EC"),
            "target_esc_id": int(current_params.get("ESC_ID") or candidate.get("detected_esc_id") or candidate.get("current_id")),
            "target_mst_id": int(current_params.get("MST_ID") or candidate.get("detected_mst_id") or ((candidate.get("current_id") or 1) + 0x10)),
            "target_ctrl_mode": _control_name(current_params.get("CTRL_MODE") or "MIT"),
            "target_timeout": int(current_params.get("TIMEOUT") or 1000),
            "target_can_br": int(current_params.get("can_br") or 1000000),
            "requires_zero": False,
            "test_profile": "safe_mit_ping",
            "expected_bus": "can0",
        }

        base["target_ctrl_mode"] = _control_name(base.get("target_ctrl_mode") or current_params.get("CTRL_MODE") or "MIT")
        base["target_timeout"] = int(base.get("target_timeout") or current_params.get("TIMEOUT") or 1000)
        base["target_can_br"] = int(_normalize_can_br(base.get("target_can_br") or current_params.get("can_br")) or 1000000)
        base["target_esc_id"] = int(base.get("target_esc_id") or current_params.get("ESC_ID") or candidate.get("detected_esc_id") or candidate.get("current_id"))
        base["target_mst_id"] = int(base.get("target_mst_id") or current_params.get("MST_ID") or candidate.get("detected_mst_id") or (base["target_esc_id"] + 0x10))
        base["target_pmax"] = float(current_params.get("PMAX") or 0)
        base["target_vmax"] = float(current_params.get("VMAX") or 0)
        base["target_tmax"] = float(current_params.get("TMAX") or 0)
        base["target_kt_value"] = float(current_params.get("KT_Value") or 0)
        base["target_gr"] = float(current_params.get("Gr") or 0)
        base["task_kind"] = job_type
        if job_type in {"single_id_config", "single_param_config"}:
            current_timeout = current_params.get("TIMEOUT")
            base["target_timeout"] = int(current_timeout) if current_timeout is not None else None
            base["timeout_write_policy"] = "read_only_during_single_motor_commissioning"
        if job_type == "single_id_config":
            base["requires_zero"] = False
            base["test_profile"] = "saved_readback"
        if job_type == "single_param_config":
            base["requires_zero"] = False
            base["test_profile"] = "comm_ping"
        return base

    def _single_param_mismatches(self, target_config: Dict[str, Any], readback: Dict[str, Any]) -> List[Dict[str, Any]]:
        expected: Dict[str, Any] = {"ESC_ID": int(target_config["target_esc_id"])}
        for target_key, rid in PARAM_TARGET_FIELD_MAP.items():
            if target_key not in target_config:
                continue
            raw_value = target_config[target_key]
            if rid == DM_variable.CTRL_MODE:
                expected[rid.name] = int(_control_from_value(raw_value))
            elif rid == DM_variable.can_br:
                expected[rid.name] = int(_normalize_can_br(raw_value) or 0)
            elif rid in {DM_variable.KT_Value, DM_variable.Gr, DM_variable.PMAX, DM_variable.VMAX, DM_variable.TMAX}:
                expected[rid.name] = float(raw_value)
            else:
                expected[rid.name] = int(raw_value)
        mismatches = []
        for key, value in expected.items():
            actual = readback.get(key)
            if actual is None:
                mismatches.append({"field": key, "expected": value, "actual": actual})
                continue
            if key == DM_variable.can_br.name:
                actual = _normalize_can_br(actual)
            if isinstance(value, float):
                if abs(float(actual) - value) > 1e-6:
                    mismatches.append({"field": key, "expected": value, "actual": actual})
            elif int(actual) != int(value):
                mismatches.append({"field": key, "expected": value, "actual": actual})
        return mismatches

    def _single_saved_readback(self, job: JobRecord, session: DeviceSession) -> Dict[str, Any]:
        """No-motion completion check after save_flash: never enables or commands the motor."""
        motor = self._motor_from_candidate(job.candidate)
        readback_rids = [DM_variable.ESC_ID] + list(PARAM_TARGET_FIELD_MAP.values()) + [DM_variable.SN, DM_variable.sw_ver]
        readback = self._read_params(session, motor, readback_rids, ignore_errors=True)
        status = self._refresh_and_snapshot(session, motor, ignore_errors=True)
        mismatches = self._single_param_mismatches(job.target_config, readback)
        issues = []
        if mismatches:
            issues.append("param_mismatch")
        if status.get("has_error"):
            issues.append("motor_error")
        if status.get("is_enabled"):
            issues.append("motor_enabled")
        if float(status.get("t_mos", 0.0)) >= TEMP_LIMITS["mos"]:
            issues.append("mos_overtemp")
        if float(status.get("t_rotor", 0.0)) >= TEMP_LIMITS["rotor"]:
            issues.append("rotor_overtemp")
        if mismatches:
            job.motors["commissioned_motor"]["mismatches"] = mismatches
        return {
            "mode": "saved_readback",
            "motion": False,
            "readback": readback,
            "final_status": status,
            "mismatches": mismatches,
            "issues": issues,
            "passed": not issues,
        }

    def _read_params(
        self,
        session: DeviceSession,
        motor: Motor,
        rids: Iterable[DM_variable],
        ignore_errors: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        params = {}
        for rid in rids:
            try:
                params[rid.name] = session.driver.read_motor_param(motor, rid, timeout=timeout)
            except Exception:
                if not ignore_errors:
                    raise
                params[rid.name] = None
        return params

    def _refresh_and_snapshot(self, session: DeviceSession, motor: Motor, ignore_errors: bool = False) -> Dict[str, Any]:
        try:
            session.driver.refresh_motor_status(motor)
        except Exception:
            if not ignore_errors:
                raise
        return motor.snapshot()

    def _write_single_target(
        self,
        session: DeviceSession,
        motor: Motor,
        target: Dict[str, Any],
        *,
        allow_service_params: bool = False,
    ):
        snapshot = self._refresh_and_snapshot(session, motor)
        if snapshot.get("is_enabled"):
            raise RuntimeError("motor must be disabled before parameter write")
        motor.MotorType = _motor_type_from_name(target["motor_type"])
        writes = [
            (DM_variable.CTRL_MODE, int(_control_from_value(target["target_ctrl_mode"]))),
            (DM_variable.can_br, _encode_can_br_for_motor(target["target_can_br"])),
            (DM_variable.MST_ID, int(target["target_mst_id"])),
        ]
        if allow_service_params and target.get("target_timeout") is not None:
            writes.insert(1, (DM_variable.TIMEOUT, int(target["target_timeout"])))
        optional_writes = [
            ("target_kt_value", DM_variable.KT_Value, float),
            ("target_gr", DM_variable.Gr, float),
            ("target_pmax", DM_variable.PMAX, float),
            ("target_vmax", DM_variable.VMAX, float),
            ("target_tmax", DM_variable.TMAX, float),
        ]
        if allow_service_params:
            for key, rid, caster in optional_writes:
                if key in target and target[key] is not None:
                    writes.append((rid, caster(target[key])))
        for rid, value in writes:
            if not session.driver.change_motor_param(motor, rid, value):
                raise RuntimeError(f"failed to write {rid.name}")
            if rid == DM_variable.MST_ID:
                session.driver.removeMotor(motor)
                motor.MasterID = int(value)
                session.driver.addMotor(motor)
                scan = self._session(session.session_id).last_scan
                if scan.get("candidates"):
                    scan["candidates"][0]["detected_mst_id"] = int(value)
                    scan["candidates"][0].setdefault("params", {})["MST_ID"] = int(value)

        new_esc_id = int(target["target_esc_id"])
        if motor.SlaveID != new_esc_id:
            if not session.driver.change_motor_param(motor, DM_variable.ESC_ID, new_esc_id):
                raise RuntimeError("failed to write ESC_ID")
            session.driver.removeMotor(motor)
            motor.SlaveID = new_esc_id
            motor.MasterID = int(target["target_mst_id"])
            session.driver.addMotor(motor)
            scan = self._session(session.session_id).last_scan
            if scan.get("candidates"):
                scan["candidates"][0]["current_id"] = new_esc_id
                scan["candidates"][0]["detected_esc_id"] = new_esc_id
                scan["candidates"][0].setdefault("params", {})["ESC_ID"] = new_esc_id

    def _disable_for_parameter_write(self, session: DeviceSession, motor: Motor) -> bool:
        if not session.driver.disable(motor):
            return False
        snapshot = self._refresh_and_snapshot(session, motor)
        return not bool(snapshot.get("is_enabled"))

    def _zero_precheck(self, session: DeviceSession, motor: Motor) -> bool:
        stable = True
        last = None
        for _ in range(3):
            last = self._refresh_and_snapshot(session, motor)
            if last["has_error"] or last["t_mos"] >= TEMP_LIMITS["mos"] or last["t_rotor"] >= TEMP_LIMITS["rotor"]:
                return False
            time.sleep(0.05)
        return stable and bool(last)

    def _zero_passed(self, snapshot: Dict[str, Any]) -> bool:
        return (
            abs(float(snapshot["position"])) <= 0.05
            and not snapshot["has_error"]
            and float(snapshot["t_mos"]) < TEMP_LIMITS["mos"]
            and float(snapshot["t_rotor"]) < TEMP_LIMITS["rotor"]
        )

    def _safe_mit_ping(self, session: DeviceSession, motor: Motor) -> Dict[str, Any]:
        positions = []
        session.driver.enable(motor)
        session.driver.controlMIT(motor, kp=10.0, kd=0.2, q=0.05, dq=0.0, tau=0.0)
        time.sleep(0.25)
        snap_a = self._refresh_and_snapshot(session, motor)
        positions.append(float(snap_a["position"]))

        session.driver.controlMIT(motor, kp=10.0, kd=0.2, q=0.0, dq=0.0, tau=0.0)
        time.sleep(0.25)
        snap_b = self._refresh_and_snapshot(session, motor)
        positions.append(float(snap_b["position"]))
        session.driver.disable(motor)
        final = self._refresh_and_snapshot(session, motor, ignore_errors=True)

        peak = max(abs(position) for position in positions) if positions else 0.0
        passed = (
            0.01 <= peak <= 0.20
            and abs(float(final["position"])) <= 0.08
            and not final["has_error"]
            and float(final["t_mos"]) < TEMP_LIMITS["mos"]
            and float(final["t_rotor"]) < TEMP_LIMITS["rotor"]
        )
        return {"positions": positions, "peak_position": peak, "final_status": final, "passed": passed}

    def _issue_meta(
        self,
        issue_code: str,
        node: str,
        detected_value: Any = None,
        expected_value: Any = None,
    ) -> Dict[str, Any]:
        templates = {
            "missing": ("critical", "关节掉线", "未收到该关节响应", "检查供电、CAN 接线和 ESC_ID"),
            "missing_esc_id": ("critical", "ESC_ID 读取失败", "无法读取电机 ESC_ID", "检查供电、总线和当前电机 ID"),
            "missing_mst_id": ("warning", "MST_ID 读取失败", "无法读取 Master ID", "重新读取参数，必要时重新写入 MST_ID"),
            "mst_id_mismatch": ("critical", "Master ID 不匹配", "电机 Master ID 与模板不一致", "按模板重写 MST_ID 并保存 Flash"),
            "can_br_mismatch": ("critical", "波特率不匹配", "电机 can_br 与当前工位模板不一致", "统一电机 can_br 与 SocketCAN bitrate"),
            "ctrl_mode_mismatch": ("warning", "控制模式不匹配", "电机 CTRL_MODE 与目标模式不一致", "重新写入 CTRL_MODE 并回读确认"),
            "bus_mismatch": ("warning", "总线分配不匹配", "检测通道与模板 expected_bus 不一致", "确认当前调试器接入的 CAN 通道"),
            "duplicate_esc_id": ("critical", "重复 ESC_ID", "总线上存在重复 ESC_ID", "逐个断开节点排查并重新分配 ID"),
            "unexpected_node": ("warning", "意外节点", "发现不在 OpenARM profile 内的节点", "核对现场接线和 profile 配置"),
            "motor_error": ("critical", "电机故障", "电机状态中存在 fault", "查看驱动状态、温度和负载后再继续"),
            "status_read_anomaly": ("warning", "状态读取异常", "电机返回了未映射的状态码，无法按标准状态解析", "记录原始 CAN 帧并使用官方工具复核状态码；复核前不放行"),
            "mos_overtemp": ("critical", "MOS 过温", "MOS 温度超过阈值", "停机散热并检查负载与散热条件"),
            "rotor_overtemp": ("critical", "绕组过温", "转子/线圈温度超过阈值", "停机散热并检查持续电流与堵转风险"),
            "param_read_failed": ("warning", "参数读取失败", "部分参数无法回读", "重新读取参数并检查通讯稳定性"),
            "param_mismatch": ("critical", "参数回读不一致", "写入后的参数与目标值不一致", "重新写入并再次回读校验"),
            "save_flash_failed": ("critical", "保存失败", "保存 Flash 未成功", "重新保存并确认失能成功"),
            "disable_failed": ("critical", "失能失败", "保存前失能失败", "检查控制状态后再执行保存"),
            "zero_failed": ("warning", "零位失败", "零位流程未通过校验", "重新对准机械基准并再次零位"),
            "test_failed": ("warning", "测试失败", "测试结果未达到通过条件", "检查电机参数、负载和控制模式"),
            "position_response_non_monotonic": ("critical", "位置响应非单调", "位置给定与反馈关系异常，可能出现摆动或无法定位", "执行低速单调扫角测试，若换线后问题仍跟随电机，建议更换电机"),
            "oscillation_without_fault": ("warning", "无故障码摆动", "电机无显式 fault 但存在来回摆动或定位不稳", "记录 MIT 指令前后位置曲线，检查位置环反馈与传感器"),
            "sensor_v_broken": ("critical", "Sensor V broken", "位置传感器 V 通道异常或损坏", "重复读参和校准验证；若问题反复出现，建议更换电机或传感器组件"),
            "calibration_failed": ("critical", "校准失败", "电机运动后校准未通过", "检查传感器反馈稳定性并复现错误日志"),
            "intermittent_sensor_fault": ("warning", "间歇性传感器异常", "故障曾短暂恢复但再次出现", "执行连续读参/校准循环并记录复现条件"),
            "command_check_failed": ("critical", "关节命令连通测试失败", "关节无法稳定执行 enable/disable 命令链路", "检查供电、总线和驱动状态，再复测该关节"),
        }
        severity, title, message, action = templates.get(
            issue_code,
            ("info", issue_code, "检测到未分类问题", "查看详细上下文并人工确认"),
        )
        return {
            "code": issue_code,
            "severity": severity,
            "blocking": severity == "critical",
            "scope": node,
            "title": title,
            "message": message,
            "detected_value": detected_value,
            "expected_value": expected_value,
            "recommended_action": action,
        }

    def _issue_summary(self, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        severity_counts = {"critical": 0, "warning": 0, "info": 0}
        for item in issues:
            severity_counts[item["severity"]] = severity_counts.get(item["severity"], 0) + 1
        return {
            "total": len(issues),
            "critical": severity_counts["critical"],
            "warning": severity_counts["warning"],
            "info": severity_counts["info"],
            "has_blocking": severity_counts["critical"] > 0,
        }

    def _collect_job_issues(self, job: JobRecord) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        if job.job_type in {"single_id_config", "single_param_config"}:
            motor_payload = job.motors.get("commissioned_motor", {})
            current = motor_payload.get("current", {})
            current_status = current.get("status", {})
            current_params = current.get("params", {})
            if current_status.get("has_error"):
                issues.append(self._issue_meta("motor_error", "commissioned_motor"))
            if float(current_status.get("t_mos", 0.0)) >= TEMP_LIMITS["mos"]:
                issues.append(self._issue_meta("mos_overtemp", "commissioned_motor", current_status.get("t_mos"), TEMP_LIMITS["mos"]))
            if float(current_status.get("t_rotor", 0.0)) >= TEMP_LIMITS["rotor"]:
                issues.append(self._issue_meta("rotor_overtemp", "commissioned_motor", current_status.get("t_rotor"), TEMP_LIMITS["rotor"]))
            if current_params and current_params.get("ESC_ID") is None:
                issues.append(self._issue_meta("missing_esc_id", "commissioned_motor"))
            if current_params and current_params.get("MST_ID") is None:
                issues.append(self._issue_meta("missing_mst_id", "commissioned_motor"))
            for mismatch in motor_payload.get("mismatches", []):
                issues.append(
                    self._issue_meta(
                        "param_mismatch",
                        "commissioned_motor",
                        mismatch.get("actual"),
                        mismatch.get("expected"),
                    )
                    | {"field": mismatch.get("field")}
                )
            if job.failure_reason:
                if "save flash" in job.failure_reason.lower():
                    issues.append(self._issue_meta("save_flash_failed", "commissioned_motor"))
                elif "disable" in job.failure_reason.lower():
                    issues.append(self._issue_meta("disable_failed", "commissioned_motor"))
                elif "零位" in job.failure_reason:
                    issues.append(self._issue_meta("zero_failed", "commissioned_motor"))
                elif "测试" in job.failure_reason:
                    issues.append(self._issue_meta("test_failed", "commissioned_motor"))
        elif job.job_type == "single_comm_check":
            checked = job.motors.get("checked_motor", {})
            for issue_code in checked.get("issues", []):
                issues.append(self._issue_meta(issue_code, "checked_motor"))
        elif job.job_type in {"arm_comm_scan", "arm_acceptance"}:
            for name, payload in job.motors.items():
                for issue_code in payload.get("issues", []):
                    issues.append(
                        self._issue_meta(
                            issue_code,
                            name,
                            payload.get("params", {}).get(issue_code.replace("_mismatch", "").upper()),
                            payload.get("expected", {}).get(f"target_{issue_code.split('_')[0]}"),
                        )
                    )
            summary = job.target_config.get("scan_summary") or job.target_config.get("acceptance_summary") or {}
            for joint in summary.get("missing", []):
                issues.append(self._issue_meta("missing", joint))
            for esc_id in summary.get("duplicate_esc_ids", []):
                issues.append(self._issue_meta("duplicate_esc_id", f"ESC_ID {esc_id}", esc_id, None))
            for esc_id in summary.get("unexpected_ids", []):
                issues.append(self._issue_meta("unexpected_node", f"ESC_ID {esc_id}", esc_id, "profile member"))

        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in issues:
            signature = (
                item["code"],
                item["scope"],
                item.get("detected_value"),
                item.get("expected_value"),
                item.get("field"),
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
        return deduped

    def _diagnostic_playbooks(self, job: JobRecord, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        issue_codes = {item["code"] for item in issues}
        playbooks: List[Dict[str, Any]] = []

        if job.job_type in {"arm_comm_scan", "arm_acceptance", "single_comm_check", "single_id_config", "single_param_config"}:
            playbooks.append(
                {
                    "id": "gripper_non_monotonic_response",
                    "title": "夹爪位置响应异常 / 无故障码摆动",
                    "applies_to": ["J7", "J8", "Gripper"],
                    "when_to_use": [
                        "位置值可下发，但反馈角度随夹爪开合不单调",
                        "无显式 fault code，状态位仍为 0/1",
                        "空载和带夹爪负载都能复现",
                        "更换线束或对调接线后，问题仍跟随同一颗电机",
                    ],
                    "recommended_tests": [
                        "执行低速单调扫角测试，记录给定位置与反馈位置曲线，确认是否存在两处以上反向跳变",
                        "对同型号正常电机做同样扫角，比较反馈曲线是否单调",
                        "记录 enable -> MIT -> disable 期间的 candump，确认控制帧正常且无 fault 上报",
                        "在空载与负载两种条件下重复测试；若问题均复现，优先怀疑电机内部位置反馈链路",
                    ],
                    "service_recommendation": "若换线、换夹爪、空载测试后异常仍跟随电机，建议更换该电机。",
                    "linked_issue_codes": ["position_response_non_monotonic", "oscillation_without_fault"],
                }
            )

        if "param_read_failed" in issue_codes or "motor_error" in issue_codes or job.job_type in {"single_comm_check", "single_param_config"}:
            playbooks.append(
                {
                    "id": "sensor_v_broken_case",
                    "title": "Sensor V broken / 读参与校准失败",
                    "applies_to": ["single motor", "arm scan"],
                    "when_to_use": [
                        "调试软件报错“Sensor V broken!”",
                        "无法稳定读取参数或无法重新校准",
                        "电机会运动，但校准最终失败",
                        "故障可能间歇性恢复后再次出现",
                    ],
                    "recommended_tests": [
                        "执行连续 10 次读参循环，观察是否出现间歇性 param read failed",
                        "执行重复校准/零位流程并记录每次是否失败，标记是否存在短暂恢复",
                        "在静置、轻微扰动线束和温升后重复读参，判断是否为间歇性传感器问题",
                        "若现场可控，优先对比同型号正常电机的读参稳定性与校准通过率",
                    ],
                    "service_recommendation": "若“Sensor V broken”反复出现，且接线已排除，建议判定为位置传感器或电机内部硬件异常。",
                    "linked_issue_codes": ["sensor_v_broken", "param_read_failed", "calibration_failed", "intermittent_sensor_fault"],
                }
            )

        return playbooks

    def _run_single_comm_check(self, job: JobRecord, session: DeviceSession) -> Dict[str, Any]:
        candidate = job.candidate or self._select_single_candidate(session)
        motor = self._motor_from_candidate(candidate)
        params = self._read_params(session, motor, SINGLE_SCAN_RIDS, ignore_errors=True)
        status = self._refresh_and_snapshot(session, motor, ignore_errors=True)
        issues = []
        if any(params.get(rid.name) is None for rid in SINGLE_SCAN_RIDS):
            issues.append("param_read_failed")
        if params.get("ESC_ID") is None:
            issues.append("missing_esc_id")
        if params.get("MST_ID") is None:
            issues.append("missing_mst_id")
        if status.get("has_error"):
            issues.append("motor_error")
        if float(status.get("t_mos", 0.0)) >= TEMP_LIMITS["mos"]:
            issues.append("mos_overtemp")
        if float(status.get("t_rotor", 0.0)) >= TEMP_LIMITS["rotor"]:
            issues.append("rotor_overtemp")
        passed = not issues
        job.candidate = candidate
        job.current_step = "checked"
        job.motors = {
            "checked_motor": {
                "candidate": candidate,
                "params": params,
                "status": status,
                "issues": issues,
                "passed": passed,
            }
        }
        return {"motor": job.motors["checked_motor"], "issues": issues, "passed": passed}

    def _arm_joint_command_check(self, session: DeviceSession, item: Dict[str, Any]) -> Dict[str, Any]:
        if not item.get("present"):
            return {"attempted": False, "passed": False, "reason": "joint_missing"}
        esc_id = int(item.get("params", {}).get("ESC_ID") or item["expected"]["target_esc_id"])
        mst_id = int(item.get("params", {}).get("MST_ID") or item["expected"]["target_mst_id"])
        motor = Motor(_motor_type_from_name(item["expected"]["motor_type"]), esc_id, mst_id)
        try:
            enable_ok = bool(session.driver.enable(motor))
            after_enable = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            disable_ok = bool(session.driver.disable(motor))
            after_disable = self._refresh_and_snapshot(session, motor, ignore_errors=True)
            passed = enable_ok and disable_ok and not after_enable.get("has_error") and not after_disable.get("has_error")
            return {
                "attempted": True,
                "passed": passed,
                "after_enable_status": after_enable.get("status"),
                "after_disable_status": after_disable.get("status"),
                "has_error_after_enable": after_enable.get("has_error"),
                "has_error_after_disable": after_disable.get("has_error"),
            }
        except Exception as error:
            return {"attempted": True, "passed": False, "reason": str(error)}

    def _attach_arm_command_checks(self, session: DeviceSession, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        attempted = 0
        passed = 0
        failed_joints = []
        for item in results:
            command_check = self._arm_joint_command_check(session, item)
            item["command_check"] = command_check
            if not command_check.get("attempted"):
                continue
            attempted += 1
            if command_check.get("passed"):
                passed += 1
            else:
                failed_joints.append(item["joint_name"])
                if "command_check_failed" not in item["issues"]:
                    item["issues"].append("command_check_failed")
                item["comm_ok"] = False
                item["result_label"] = "FAIL"
        return {
            "command_test_total": attempted,
            "command_test_passed": passed,
            "command_test_failed": attempted - passed,
            "command_test_failed_joints": failed_joints,
        }

    def _run_arm_comm_scan(
        self,
        job: JobRecord,
        session: DeviceSession,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
        allow_motion: bool = False,
    ) -> Dict[str, Any]:
        if not job.profile_id:
            raise ValueError("arm scan requires profile_id")
        job.current_step = "bus_scanning"
        self._log_event(job, "info", "bus_scanning", "开始整臂 CAN2.0 通信扫描")
        arm_scan = self._scan_arm_with_stability(
            session,
            job.profile_id,
            repeat_count=max(1, min(int(repeat_count), 5)),
            repeat_delay_ms=max(0, min(int(repeat_delay_ms), 2000)),
        )
        results = arm_scan["results"]
        if allow_motion:
            command_summary = self._attach_arm_command_checks(session, results)
            arm_scan["summary"].update(command_summary)
            arm_scan["summary"]["passed"] = arm_scan["summary"]["passed"] and command_summary["command_test_failed"] == 0
            arm_scan["summary"]["command_check_mode"] = "enabled"
        else:
            arm_scan["summary"].update(
                {
                    "command_test_total": 0,
                    "command_test_passed": 0,
                    "command_test_failed": 0,
                    "command_test_failed_joints": [],
                    "command_check_mode": "safe_readonly",
                }
            )
        arm_scan["summary"]["shipment_checklist"] = self._shipment_checklist(arm_scan["summary"])
        job.motors = {item["joint_name"]: item for item in results}
        job.target_config["scan_summary"] = arm_scan["summary"]
        job.current_step = "consistency_checked"
        self._log_event(job, "info", "consistency_checked", "完成总线盘点与一致性检查")
        return {
            "joints": results,
            "missing": arm_scan["missing"],
            "unhealthy": arm_scan["unhealthy"],
            "mismatches": arm_scan["mismatches"],
            "unexpected": arm_scan["unexpected"],
            "duplicate_esc_ids": arm_scan["duplicate_esc_ids"],
            "summary": arm_scan["summary"],
            "passed": arm_scan["passed"],
        }

    def _acceptance_summary(self, arm_scan: Dict[str, Any]) -> Dict[str, Any]:
        summary = dict(arm_scan["summary"])
        blocking_reasons = []
        if summary["missing"]:
            blocking_reasons.append(f"missing:{','.join(summary['missing'])}")
        if summary["duplicate_esc_ids"]:
            blocking_reasons.append(f"duplicate_esc_ids:{','.join(str(item) for item in summary['duplicate_esc_ids'])}")
        if summary["unexpected_ids"]:
            blocking_reasons.append(f"unexpected_ids:{','.join(str(item) for item in summary['unexpected_ids'])}")
        if summary["bitrate_mismatches"]:
            blocking_reasons.append(f"can_br_mismatch:{','.join(summary['bitrate_mismatches'])}")
        if summary["ctrl_mode_mismatches"]:
            blocking_reasons.append(f"ctrl_mode_mismatch:{','.join(summary['ctrl_mode_mismatches'])}")
        if summary["bus_mismatches"]:
            blocking_reasons.append(f"bus_mismatch:{','.join(summary['bus_mismatches'])}")
        if summary["unhealthy"]:
            blocking_reasons.append(f"fault_or_unhealthy:{','.join(summary['unhealthy'])}")
        if summary.get("status_read_anomalies"):
            blocking_reasons.append(f"status_read_anomaly:{','.join(summary['status_read_anomalies'])}")
        if summary.get("command_test_failed_joints"):
            blocking_reasons.append(f"command_check_failed:{','.join(summary['command_test_failed_joints'])}")
        summary["release_ready"] = summary["passed"]
        summary["release_decision"] = "PASS" if summary["passed"] else "HOLD"
        summary["blocking_reasons"] = blocking_reasons
        summary["shipment_checklist"] = self._shipment_checklist(summary)
        return summary

    def _shipment_checklist(self, summary: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        stability = summary.get("stability") or {}
        automated = [
            {
                "id": "id_mapping",
                "label": "CAN ID / Receiver ID 映射正确",
                "status": "pass" if not summary.get("missing") and not summary.get("duplicate_esc_ids") and not summary.get("unexpected_ids") and not summary.get("mismatches") else "fail",
                "detail": "检查缺失节点、重复 ID、意外节点以及 Receiver ID 不一致。",
            },
            {
                "id": "baudrate",
                "label": "波特率一致且为目标配置",
                "status": "pass" if not summary.get("bitrate_mismatches") else "fail",
                "detail": "对应 OpenArm Step 4 的 Set Motor Baudrate / Verify Motor Communication。",
            },
            {
                "id": "command_chain",
                "label": "逐关节 enable/disable 命令链路正常",
                "status": "manual_required" if summary.get("command_check_mode") == "safe_readonly" else ("pass" if summary.get("command_test_failed", 0) == 0 else "fail"),
                "detail": "验证每个在线关节都能响应基本 CAN 命令链路。未做零位校准时建议保持只读安全模式。",
            },
            {
                "id": "communication_stability",
                "label": "连续复扫通信稳定",
                "status": "pass" if stability.get("flaky_joint_count", 0) == 0 else "fail",
                "detail": "复扫中无偶发掉线、无参数漂移。",
            },
            {
                "id": "fault_free",
                "label": "无电机 fault / 过温 / 状态读取异常",
                "status": "pass" if summary.get("total_faults", 0) == 0 and summary.get("total_status_read_anomalies", 0) == 0 else "fail",
                "detail": "现场应确认所有关节状态正常、可读参，且状态码可按标准枚举解析。",
            },
        ]
        manual = [
            {
                "id": "power_cycle_persistence",
                "label": "断电重上电后 ID / 波特率持久化复核",
                "status": "manual_required",
                "detail": "OpenArm 官方建议在写 Flash 后重新上电并再次执行 motor check 确认永久生效。",
            },
            {
                "id": "zero_calibration_scope",
                "label": "零位校准与最终姿态校准",
                "status": "customer_scope",
                "detail": "官方 Step 4 包含 zero position calibration；若按交付文件约定留给客户，应在报告中明确为客户侧必做项。",
            },
            {
                "id": "demo_and_follower_validation",
                "label": "官方示例 / Follower 功能联调",
                "status": "customer_scope",
                "detail": "在最终部署环境完成上位机、主控与 follower 功能验证。",
            },
        ]
        return {"automated": automated, "manual": manual}

    def _run_arm_acceptance(
        self,
        job: JobRecord,
        session: DeviceSession,
        repeat_count: int = 1,
        repeat_delay_ms: int = 120,
        allow_motion: bool = False,
    ) -> Dict[str, Any]:
        if not job.profile_id:
            raise ValueError("arm acceptance requires profile_id")
        job.current_step = "bus_scanning"
        self._log_event(job, "info", "bus_scanning", "开始整臂 CAN2.0 验收扫描")
        arm_scan = self._scan_arm_with_stability(
            session,
            job.profile_id,
            repeat_count=max(1, min(int(repeat_count), 5)),
            repeat_delay_ms=max(0, min(int(repeat_delay_ms), 2000)),
        )
        results = arm_scan["results"]
        if allow_motion:
            command_summary = self._attach_arm_command_checks(session, results)
            arm_scan["summary"].update(command_summary)
            arm_scan["summary"]["passed"] = arm_scan["summary"]["passed"] and command_summary["command_test_failed"] == 0
            arm_scan["summary"]["command_check_mode"] = "enabled"
        else:
            arm_scan["summary"].update(
                {
                    "command_test_total": 0,
                    "command_test_passed": 0,
                    "command_test_failed": 0,
                    "command_test_failed_joints": [],
                    "command_check_mode": "safe_readonly",
                }
            )
        acceptance_summary = self._acceptance_summary(arm_scan)
        job.motors = {item["joint_name"]: item for item in results}
        job.current_step = "acceptance_checked"
        job.target_config = {"acceptance_summary": acceptance_summary, "scan_summary": arm_scan["summary"]}
        self._log_event(
            job,
            "info",
            "acceptance_checked",
            f"整臂验收完成，结论 {acceptance_summary['release_decision']}",
        )
        return {
            "joints": results,
            "missing": arm_scan["missing"],
            "unhealthy": arm_scan["unhealthy"],
            "mismatches": arm_scan["mismatches"],
            "unexpected": arm_scan["unexpected"],
            "duplicate_esc_ids": arm_scan["duplicate_esc_ids"],
            "summary": acceptance_summary,
            "passed": acceptance_summary["release_ready"],
        }

    def _require_capability(self, session: DeviceSession, capability: str):
        if not getattr(session.capabilities, capability):
            raise RuntimeError(f"transport does not support {capability}")

    def _fail_job(self, job: JobRecord, reason: str):
        job.status = "failed"
        job.current_step = "failed"
        job.failure_reason = reason
        job.finished_at = _now_iso()
        self._log_event(job, "error", "job_failed", reason)
        self._persist_job(job)
        self._emit("job_state", self._job_state_payload(job, reason))

    def _log_event(self, job: JobRecord, severity: str, step: str, message: str):
        event = {"timestamp": _now_iso(), "severity": severity, "step": step, "message": message}
        job.events.append(event)
        events_path = Path(job.artifact_dir) / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._emit("job_state", self._job_state_payload(job, message))

    def _job_state_payload(self, job: JobRecord, message: str) -> Dict[str, Any]:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "step": job.current_step,
            "message": message,
            "progress": self._progress(job),
        }

    def _progress(self, job: JobRecord) -> int:
        steps = {
            "draft": 0,
            "device_connected": 10,
            "identified": 20,
            "target_loaded": 25,
            "profile_loaded": 25,
            "profile_selected": 30,
            "bus_scanning": 45,
            "inventory_built": 55,
            "consistency_checked": 70,
            "acceptance_checked": 85,
            "checked": 85,
            "reported": 95,
            "params_written": 45,
            "params_verified": 55,
            "params_saved": 65,
            "zeroed": 80,
            "tested": 95,
            "passed": 100,
            "failed": 100,
            "cancelled": 100,
        }
        return steps.get(job.status, 0)

    def _persist_job(self, job: JobRecord):
        payload = self._job_payload(job)
        _atomic_json(Path(job.artifact_dir) / "job.json", payload)
        _atomic_json(Path(job.artifact_dir) / "issues.json", self.issues(job.job_id))
        motors_dir = Path(job.artifact_dir) / "motors"
        motors_dir.mkdir(parents=True, exist_ok=True)
        for name, motor_payload in job.motors.items():
            _atomic_json(motors_dir / f"{_safe_name(name)}.json", motor_payload)
        self._emit("job_state", self._job_state_payload(job, job.events[-1]["message"] if job.events else job.status))
        for motor_name, motor_payload in job.motors.items():
            status = motor_payload.get("status") or motor_payload.get("current", {}).get("status") or motor_payload.get("final_status")
            if status:
                self._emit(
                    "motor_status",
                    {
                        "job_id": job.job_id,
                        "joint_or_slot": motor_name,
                        "position": status.get("position", 0.0),
                        "velocity": status.get("velocity", 0.0),
                        "torque": status.get("torque", 0.0),
                        "t_mos": status.get("t_mos", 0.0),
                        "t_rotor": status.get("t_rotor", 0.0),
                        "motor_status": status.get("status", "UNKNOWN"),
                        "transport_online": True,
                    },
                )

    def _job_payload(self, job: JobRecord) -> Dict[str, Any]:
        return {
            "job": {
                "job_id": job.job_id,
                "job_type": _public_job_type(job.job_type),
                "profile_id": job.profile_id,
                "target_joint": job.target_joint,
                "expert_mode": job.expert_mode,
                "product_line": job.product_line,
                "status": job.status,
                "current_step": job.current_step,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "failure_reason": job.failure_reason,
                "artifact_dir": job.artifact_dir,
            },
            "motors": job.motors,
            "current_step": job.current_step,
            "allowed_actions": self._allowed_actions(job),
            "events": job.events[-20:],
            "summary": job.target_config.get("acceptance_summary"),
            "issues_summary": self._issue_summary(self._collect_job_issues(job)),
        }

    def _write_report(self, job: JobRecord):
        issues_payload = self.issues(job.job_id)
        rows = []
        for name, payload in job.motors.items():
            current = payload.get("current", {}).get("status") or payload.get("status") or {}
            status_text = payload.get("test", {}).get("passed")
            if status_text is None:
                status_text = payload.get("passed")
            if status_text is None:
                status_text = payload.get("comm_ok")
            if status_text is None:
                status_text = payload.get("present", True) and not current.get("has_error", False)
            issues = payload.get("issues", [])
            result_label = payload.get("result_label") or ("PASS" if status_text else "FAIL")
            rows.append(
                f"<tr><td>{escape(name)}</td><td>{escape(str(payload.get('expected', {}).get('motor_type', payload.get('target', {}).get('motor_type', ''))))}</td>"
                f"<td>{escape(str(current.get('status', 'UNKNOWN')))}</td><td>{escape(', '.join(issues) if issues else '-')}</td><td>{escape(str(result_label))}</td></tr>"
            )
        acceptance_summary = job.target_config.get("acceptance_summary")
        acceptance_block = ""
        if acceptance_summary:
            acceptance_block = (
                f"<p>Release Decision: {escape(str(acceptance_summary.get('release_decision', '-')))}</p>"
                f"<p>Blocking Reasons: {escape(', '.join(acceptance_summary.get('blocking_reasons', [])) or '-')}</p>"
            )
        issue_rows = "".join(
            f"<tr><td>{escape(item['scope'])}</td><td>{escape(item['title'])}</td><td>{escape(item['severity'])}</td>"
            f"<td>{escape(str(item.get('detected_value', '-')))}</td><td>{escape(str(item.get('expected_value', '-')))}</td>"
            f"<td>{escape(item['recommended_action'])}</td></tr>"
            for item in issues_payload["issues"]
        )
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>Job Report {escape(job.job_id)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; padding: 24px; color: #1f2937; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .pass {{ color: #166534; }}
    .fail {{ color: #b91c1c; }}
  </style>
</head>
<body>
  <h1>OpenARM Motor Commissioning Report</h1>
  <p>Job ID: {escape(job.job_id)}</p>
  <p>Job Type: {escape(_public_job_type(job.job_type))}</p>
  <p>Status: {escape(job.status)}</p>
  <p>Profile: {escape(str(job.profile_id or '-'))}</p>
  <p>Target Joint: {escape(str(job.target_joint or '-'))}</p>
  <p>Issues: total={issues_payload['summary']['total']} critical={issues_payload['summary']['critical']} warning={issues_payload['summary']['warning']} info={issues_payload['summary']['info']}</p>
  {acceptance_block}
  <table>
    <thead><tr><th>Motor / Joint</th><th>OpenARM 官方型号</th><th>Status</th><th>Issues</th><th>Result</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <h2>问题监测</h2>
  <table>
    <thead><tr><th>Scope</th><th>Title</th><th>Severity</th><th>Detected</th><th>Expected</th><th>Recommended Action</th></tr></thead>
    <tbody>{issue_rows or '<tr><td colspan="6">未发现问题</td></tr>'}</tbody>
  </table>
</body>
</html>"""
        _atomic_text(Path(job.artifact_dir) / "report.html", html)
