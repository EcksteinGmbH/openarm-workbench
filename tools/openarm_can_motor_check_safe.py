#!/usr/bin/env python3
"""OpenARM-compatible motor check with Damiao TIMEOUT-safe keepalive."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.damiao_motor_driver import (  # noqa: E402
    Control_Type,
    DM_Motor_Type,
    DM_variable,
    DamiaoSocketCANDriver,
    Motor,
)


def motor_type_for_can_id(send_can_id: int) -> DM_Motor_Type:
    joint_index = ((int(send_can_id) - 1) % 8) + 1
    if joint_index <= 2:
        return DM_Motor_Type.DM8009
    if joint_index <= 4:
        return DM_Motor_Type.DM4340
    return DM_Motor_Type.DM4310


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenArm motor-check compatible command with fast MIT keepalive"
    )
    parser.add_argument("send_can_id", type=int)
    parser.add_argument("recv_can_id", type=int)
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("-fd", action="store_true", dest="fd")
    return parser.parse_args()


def print_status(index: int, snapshot: dict):
    print(f"\n--- Refresh {index}/10 ---")
    print(f"Motor ID: {snapshot.get('slave_id')}")
    print(f"  Position: {snapshot.get('position')} rad")
    print(f"  Velocity: {snapshot.get('velocity')} rad/s")
    print(f"  Torque: {snapshot.get('torque')} Nm")
    print(f"  Temperature (MOS): {snapshot.get('t_mos')} °C")
    print(f"  Temperature (Rotor): {snapshot.get('t_rotor')} °C")
    print(f"  Status: {snapshot.get('status')} ({snapshot.get('status_code')})")


def main() -> int:
    args = parse_args()
    if args.fd:
        print("Error: CAN-FD is not supported by this workstation-safe motor check.", file=sys.stderr)
        return 1

    print("=== OpenArm Motor Control Script ===")
    print("Mode: Workstation TIMEOUT-safe wrapper")
    print(f"Send CAN ID: {args.send_can_id}")
    print(f"Receive CAN ID: {args.recv_can_id}")
    print(f"CAN Interface: {args.can_interface}")
    print("CAN-FD Enabled: No")
    print()

    driver = DamiaoSocketCANDriver(channel=args.can_interface, bitrate=1000000)
    motor_type = motor_type_for_can_id(args.send_can_id)
    print(f"Motor Type: {motor_type.name}")
    motor = Motor(motor_type, args.send_can_id, args.recv_can_id)
    if not driver.connect():
        print("Error: failed to open SocketCAN interface", file=sys.stderr)
        return 1

    try:
        driver.ensure_motor(motor)
        print("Initializing OpenArm CAN...")
        print("Initializing motor...")
        print("Reading motor parameters...")
        mst_id = driver.read_motor_param(motor, DM_variable.MST_ID, timeout=1.0)
        baudrate = driver.read_motor_param(motor, DM_variable.can_br, timeout=1.0)
        control_mode = driver.read_motor_param(motor, DM_variable.CTRL_MODE, timeout=1.0)

        print("\n=== Motor Parameters ===")
        print(f"Send CAN ID: {args.send_can_id}")
        print(f"Queried Master ID: {mst_id}")
        print(f"Queried Baudrate (1-9): {baudrate}")
        print(f"Queried Control Mode (1: MIT, 2: POS_VEL, 3: VEL, 4: TORQUE_POS): {control_mode}")
        if int(mst_id or -1) != int(args.recv_can_id):
            print(
                f"Error: Queried Master ID ({mst_id}) does not match provided recv_can_id ({args.recv_can_id})",
                file=sys.stderr,
            )
            return 1
        if int(control_mode or -1) != int(Control_Type.MIT):
            print(f"Warning: Queried Control Mode ({control_mode}) is not MIT. Currently not supported.")
        print("✓ Master ID verification passed")

        pre = {}
        try:
            driver.refresh_motor_status(motor)
            pre = motor.snapshot()
        except Exception:
            pre = {}
        hold_q = float(pre.get("position", 0.0) or 0.0)

        print("\n=== Enabling Motor ===")
        driver.enable_fast(motor)

        print("\n=== Refreshing Motor Status (10Hz for 1 second, 5ms zero-torque keepalive) ===")
        for index in range(1, 11):
            deadline = time.time() + 0.1
            while time.time() < deadline:
                driver.controlMIT_fast(motor, kp=0.0, kd=0.0, q=hold_q, dq=0.0, tau=0.0)
                driver._drain(0.001)
                time.sleep(0.005)
            snapshot = motor.snapshot()
            print_status(index, snapshot)
            if snapshot.get("has_error"):
                print(f"Error: motor entered {snapshot.get('status')} during check", file=sys.stderr)
                return 1

        print("\n=== Disabling Motor ===")
        driver.disable(motor)
        time.sleep(0.05)
        driver.refresh_motor_status(motor)
        final = motor.snapshot()
        if final.get("status") != "DISABLED" or final.get("has_error"):
            print(f"Error: final state is {final.get('status')} ({final.get('status_code')})", file=sys.stderr)
            return 1

        print("\n=== Script Completed Successfully ===")
        return 0
    finally:
        try:
            driver.disable(motor)
        except Exception:
            pass
        driver.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
