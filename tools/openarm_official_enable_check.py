#!/usr/bin/env python3
"""Official OpenArm enable/disable check with raw Damiao status confirmation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import can
import openarm_can as oa

from src.damiao_motor_driver import DM_Motor_Type, DamiaoSocketCANDriver, Motor


MOTOR_TYPES = [
    oa.MotorType.DM8009,
    oa.MotorType.DM8009,
    oa.MotorType.DM4340,
    oa.MotorType.DM4340,
    oa.MotorType.DM4310,
    oa.MotorType.DM4310,
    oa.MotorType.DM4310,
]

DRIVER_MOTOR_TYPES = [
    DM_Motor_Type.DM8009,
    DM_Motor_Type.DM8009,
    DM_Motor_Type.DM4340,
    DM_Motor_Type.DM4340,
    DM_Motor_Type.DM4310,
    DM_Motor_Type.DM4310,
    DM_Motor_Type.DM4310,
]


def id_map(arm_side: str) -> tuple[List[int], List[int], int, int]:
    if arm_side == "left_arm":
        return list(range(0x09, 0x10)), list(range(0x19, 0x20)), 0x10, 0x20
    return list(range(0x01, 0x08)), list(range(0x11, 0x18)), 0x08, 0x18


def status_name(code: int) -> str:
    return {
        0x0: "DISABLED",
        0x1: "ENABLED",
        0x8: "OVERVOLTAGE",
        0x9: "UNDERVOLTAGE",
        0xA: "OVERCURRENT",
        0xB: "MOS_OVERTEMP",
        0xC: "COIL_OVERTEMP",
        0xD: "COMM_LOST",
        0xE: "OVERLOAD",
    }.get(code, f"UNKNOWN_0x{code:X}")


def decode_status(recv_id: int, data: List[int]) -> tuple[int | None, str]:
    send_id = recv_id - 0x10
    if send_id > 0x0F and data[0] == send_id:
        return None, "STATE_FRAME_ID16_UNTAGGED"
    code = int(data[0]) >> 4
    return code, status_name(code)


def collect_status(bus: can.BusABC, recv_ids: List[int], duration_s: float) -> Dict[int, dict]:
    deadline = time.time() + duration_s
    latest: Dict[int, dict] = {}
    recv_set = set(recv_ids)
    while time.time() < deadline:
        msg = bus.recv(timeout=0.005)
        if msg is None or msg.arbitration_id not in recv_set or len(msg.data) < 8:
            continue
        data = list(msg.data)
        code, name = decode_status(int(msg.arbitration_id), data)
        latest[int(msg.arbitration_id)] = {
            "can_id": int(msg.arbitration_id),
            "data_hex": bytes(data).hex().upper(),
            "status_code": code,
            "status": name,
            "timestamp": float(msg.timestamp),
        }
    return latest


def read_positions_with_workbench_driver(canport: str, arm_side: str, samples: int = 5) -> tuple[List[float], List[float]]:
    send_ids, recv_ids, gripper_send, gripper_recv = id_map(arm_side)
    driver = DamiaoSocketCANDriver(channel=canport, bitrate=1000000)
    if not driver.connect():
        raise RuntimeError("workbench driver failed to connect for position pre-read")
    try:
        motors = [
            Motor(motor_type, send_id, recv_id)
            for motor_type, send_id, recv_id in zip(DRIVER_MOTOR_TYPES, send_ids, recv_ids)
        ]
        gripper = Motor(DM_Motor_Type.DM4310, gripper_send, gripper_recv)
        arm_samples: List[List[float]] = []
        grip_samples: List[float] = []
        for _ in range(samples):
            arm_q: List[float] = []
            for motor in motors:
                driver.refresh_motor_status(motor)
                snap = motor.snapshot()
                if snap.get("has_error") or snap.get("is_enabled"):
                    raise RuntimeError(f"unsafe pre-read status on motor {motor.SlaveID}: {snap.get('status')}")
                arm_q.append(float(snap["position"]))
            driver.refresh_motor_status(gripper)
            grip_snap = gripper.snapshot()
            if grip_snap.get("has_error") or grip_snap.get("is_enabled"):
                raise RuntimeError(f"unsafe pre-read status on gripper {gripper.SlaveID}: {grip_snap.get('status')}")
            arm_samples.append(arm_q)
            grip_samples.append(float(grip_snap["position"]))
            time.sleep(0.02)
        arm_q = [sum(sample[i] for sample in arm_samples) / len(arm_samples) for i in range(len(motors))]
        grip_q = [sum(grip_samples) / len(grip_samples)]
    finally:
        driver.disconnect()
    if all(abs(item) < 1e-9 for item in arm_q + grip_q):
        raise RuntimeError("position feedback was not populated; refusing to enable")
    return arm_q, grip_q


def keepalive_and_collect_status(
    openarm: oa.OpenArm,
    bus: can.BusABC,
    recv_ids: List[int],
    arm_count: int,
    duration_s: float,
    arm_q: List[float],
    grip_q: List[float],
) -> tuple[int, Dict[int, dict]]:
    arm = openarm.get_arm()
    grip = openarm.get_gripper()
    arm_params = [oa.MITParam(2.0, 0.15, q, 0.0, 0.0) for q in arm_q[:arm_count]]
    grip_params = [oa.MITParam(1.0, 0.1, grip_q[0], 0.0, 0.0)]
    print(f"hold_positions_arm={[round(item, 6) for item in arm_q[:arm_count]]}", flush=True)
    print(f"hold_positions_gripper={[round(item, 6) for item in grip_q]}", flush=True)
    recv_set = set(recv_ids)
    latest: Dict[int, dict] = {}
    sent = 0
    deadline = time.time() + duration_s
    while time.time() < deadline:
        arm.mit_control_all(arm_params)
        grip.mit_control_all(grip_params)
        sent += arm_count + 1
        frame_deadline = time.time() + 0.004
        while time.time() < frame_deadline:
            msg = bus.recv(timeout=0.001)
            if msg is None or msg.arbitration_id not in recv_set or len(msg.data) < 8:
                continue
            data = list(msg.data)
            code, name = decode_status(int(msg.arbitration_id), data)
            latest[int(msg.arbitration_id)] = {
                "can_id": int(msg.arbitration_id),
                "data_hex": bytes(data).hex().upper(),
                "status_code": code,
                "status": name,
                "timestamp": float(msg.timestamp),
            }
        time.sleep(0.001)
    return sent, latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Official OpenArm enable check without motion.")
    parser.add_argument("--canport", default="can0")
    parser.add_argument("--arm-side", "--arm_side", dest="arm_side", choices=["right_arm", "left_arm"], default="right_arm")
    parser.add_argument("--hold-ms", type=int, default=300)
    parser.add_argument("--fd", action="store_true", help="Use CAN-FD. Default is classic CAN 2.0.")
    args = parser.parse_args()

    send_ids, recv_ids, gripper_send, gripper_recv = id_map(args.arm_side)
    all_recv_ids = recv_ids + [gripper_recv]
    hold_s = max(0.05, min(args.hold_ms / 1000.0, 10.0))

    print("=== Official OpenArm Enable Check ===", flush=True)
    print(f"canport={args.canport} arm_side={args.arm_side} fd={args.fd}", flush=True)
    print(f"send_ids={[hex(item) for item in send_ids + [gripper_send]]}", flush=True)
    print(f"recv_ids={[hex(item) for item in all_recv_ids]}", flush=True)

    bus = can.interface.Bus(channel=args.canport, interface="socketcan")
    openarm = oa.OpenArm(args.canport, args.fd)
    openarm.init_arm_motors(MOTOR_TYPES, send_ids, recv_ids)
    openarm.init_gripper_motor(oa.MotorType.DM4310, gripper_send, gripper_recv)
    openarm.set_callback_mode_all(oa.CallbackMode.STATE)

    try:
        collect_status(bus, all_recv_ids, 0.05)
        arm_q, grip_q = read_positions_with_workbench_driver(args.canport, args.arm_side)
        print(f"pre_enable_positions_arm={[round(item, 6) for item in arm_q]}", flush=True)
        print(f"pre_enable_positions_gripper={[round(item, 6) for item in grip_q]}", flush=True)
        print("Enabling with official openarm.enable_all()...", flush=True)
        openarm.enable_all()
        sent, enabled_status = keepalive_and_collect_status(
            openarm,
            bus,
            all_recv_ids,
            len(send_ids),
            hold_s,
            arm_q,
            grip_q,
        )
        print(f"keepalive_frames_sent={sent}", flush=True)

        enabled_ok = True
        for recv_id in all_recv_ids:
            status = enabled_status.get(recv_id)
            print(f"ENABLE recv_id=0x{recv_id:X} status={status}", flush=True)
            if not status or (status.get("status_code") not in (0x1, None)):
                enabled_ok = False

        print("Disabling with official openarm.disable_all()...", flush=True)
        openarm.disable_all()
        disabled_status = collect_status(bus, all_recv_ids, 0.4)

        disabled_ok = True
        for recv_id in all_recv_ids:
            status = disabled_status.get(recv_id)
            print(f"DISABLE recv_id=0x{recv_id:X} status={status}", flush=True)
            if not status or (status.get("status_code") not in (0x0, None)):
                disabled_ok = False

        if enabled_ok and disabled_ok:
            print("RESULT: PASS", flush=True)
            return 0
        print("RESULT: FAIL", flush=True)
        return 2
    finally:
        try:
            openarm.disable_all()
        except Exception:
            pass
        bus.shutdown()


if __name__ == "__main__":
    sys.exit(main())
