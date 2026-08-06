#!/usr/bin/env python3
"""No-motion readiness gate before OpenARM dynamic zero/demo tests."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.damiao_motor_driver import DM_Motor_Type, DM_variable, DamiaoSocketCANDriver, Motor
from src.workstation import ProfileManager


MOTOR_TYPES = [
    DM_Motor_Type.DM8009,
    DM_Motor_Type.DM8009,
    DM_Motor_Type.DM4340,
    DM_Motor_Type.DM4340,
    DM_Motor_Type.DM4310,
    DM_Motor_Type.DM4310,
    DM_Motor_Type.DM4310,
    DM_Motor_Type.DM4310,
]


def ids_for_side(arm_side: str) -> tuple[list[int], list[int], list[str]]:
    if arm_side == "left_arm":
        esc_ids = list(range(0x09, 0x11))
        mst_ids = list(range(0x19, 0x21))
        names = [f"L-J{i}" for i in range(1, 9)]
        return esc_ids, mst_ids, names
    esc_ids = list(range(0x01, 0x09))
    mst_ids = list(range(0x11, 0x19))
    names = [f"R-J{i}" for i in range(1, 9)]
    return esc_ids, mst_ids, names


def can_snapshot(channel: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["ip", "-statistics", "-details", "link", "show", channel],
        check=False,
        text=True,
        capture_output=True,
    )
    text = proc.stdout + proc.stderr
    return {
        "returncode": proc.returncode,
        "raw": text,
        "up": "state UP" in text,
        "error_active": "can state ERROR-ACTIVE" in text,
        "bitrate_1000000": "bitrate 1000000" in text,
        "has_errors": " bus-off" in text and not "\n\t  0          0          0          0          0          0" in text,
    }


def read_joint(driver: DamiaoSocketCANDriver, motor: Motor, samples: int, delay_s: float) -> dict[str, Any]:
    positions: list[float] = []
    velocities: list[float] = []
    torques: list[float] = []
    frames: list[dict[str, Any] | None] = []
    status_samples: list[dict[str, Any]] = []
    for _ in range(samples):
        driver.refresh_motor_status(motor)
        snap = motor.snapshot()
        status_samples.append(snap)
        positions.append(float(snap["position"]))
        velocities.append(float(snap["velocity"]))
        torques.append(float(snap["torque"]))
        frames.append(snap.get("last_status_frame"))
        time.sleep(delay_s)

    params = {
        "ESC_ID": driver.read_motor_param(motor, DM_variable.ESC_ID),
        "MST_ID": driver.read_motor_param(motor, DM_variable.MST_ID),
        "CTRL_MODE": driver.read_motor_param(motor, DM_variable.CTRL_MODE),
        "TIMEOUT": driver.read_motor_param(motor, DM_variable.TIMEOUT),
        "can_br": driver.read_motor_param(motor, DM_variable.can_br),
    }
    final = status_samples[-1]
    finite_positions = all(math.isfinite(item) for item in positions)
    position_span = max(positions) - min(positions) if positions else float("inf")
    return {
        "params": params,
        "status": final,
        "samples": {
            "count": samples,
            "positions": positions,
            "velocities": velocities,
            "torques": torques,
            "position_span_rad": position_span,
            "finite_positions": finite_positions,
            "frames": frames,
        },
    }


def script_guard_snapshot() -> dict[str, Any]:
    zero_script = ROOT / "external/openarm_can_1.2.2/setup/openarm-can-zero-position-calibration"
    enable_script = ROOT / "tools/openarm_official_enable_check.py"
    zero_text = zero_script.read_text(encoding="utf-8")
    enable_text = enable_script.read_text(encoding="utf-8")
    return {
        "zero_script_feedback_guard": "not enough valid position feedback before enable" in zero_text
        and "position feedback is unstable before enable" in zero_text,
        "zero_script_gain_scale": "WORKSTATION_GAIN_SCALE" in zero_text,
        "zero_script_bump_guard": "WORKSTATION_MAX_BUMP_DEG" in zero_text,
        "enable_script_refuses_empty_position": "refusing to enable" in enable_text,
        "enable_script_state_callback": "CallbackMode.STATE" in enable_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="No-motion dynamic-test readiness check.")
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--arm-side", "--arm_side", dest="arm_side", choices=["right_arm", "left_arm"], default="left_arm")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--delay-ms", type=int, default=80)
    args = parser.parse_args()

    esc_ids, mst_ids, names = ids_for_side(args.arm_side)
    profile_id = "openarm_right_arm_v1" if args.arm_side == "right_arm" else "openarm_left_arm_v1"
    profile = ProfileManager().get_profile(profile_id)
    expected_timeouts = {
        str(joint["joint_name"]): int(joint["target_timeout"])
        for joint in profile["joints"]
    }
    result: dict[str, Any] = {
        "channel": args.channel,
        "arm_side": args.arm_side,
        "profile_id": profile_id,
        "motion_command_sent": False,
        "checks": {},
        "joints": [],
        "ready_for_low_gain_enable": False,
        "ready_for_official_dynamic_zero": False,
        "ready_for_demo": False,
        "blocking_reasons": [],
    }

    can_state = can_snapshot(args.channel)
    result["checks"]["can"] = can_state
    if not (can_state["up"] and can_state["error_active"] and can_state["bitrate_1000000"]):
        result["blocking_reasons"].append("can_not_ready")

    guards = script_guard_snapshot()
    result["checks"]["script_guards"] = guards
    for key, value in guards.items():
        if not value:
            result["blocking_reasons"].append(f"missing_{key}")

    driver = DamiaoSocketCANDriver(channel=args.channel, bitrate=1000000)
    try:
        if not driver.connect():
            result["blocking_reasons"].append("driver_connect_failed")
        for name, esc_id, mst_id, motor_type in zip(names, esc_ids, mst_ids, MOTOR_TYPES):
            expected_timeout = expected_timeouts[name]
            motor = Motor(motor_type, esc_id, mst_id)
            joint = {
                "joint_name": name,
                "esc_id": esc_id,
                "mst_id": mst_id,
                "expected_timeout": expected_timeout,
                "passed": False,
                "issues": [],
            }
            try:
                data = read_joint(driver, motor, max(3, args.samples), max(0.02, args.delay_ms / 1000.0))
                joint.update(data)
                params = data["params"]
                status = data["status"]
                samples = data["samples"]
                if params.get("ESC_ID") != esc_id:
                    joint["issues"].append("esc_id_mismatch")
                if params.get("MST_ID") != mst_id:
                    joint["issues"].append("mst_id_mismatch")
                if params.get("CTRL_MODE") != 1:
                    joint["issues"].append("ctrl_mode_not_mit")
                if params.get("TIMEOUT") != expected_timeout:
                    joint["issues"].append("timeout_mismatch")
                if params.get("can_br") not in (4, 1000000):
                    joint["issues"].append("can_br_not_1mbps")
                if status.get("has_error"):
                    joint["issues"].append(f"motor_status_{status.get('status')}")
                if status.get("is_enabled"):
                    joint["issues"].append("motor_unexpectedly_enabled")
                if not samples.get("finite_positions"):
                    joint["issues"].append("position_not_finite")
                if samples.get("position_span_rad", 999.0) > 0.05:
                    joint["issues"].append("position_feedback_unstable")
                if not status.get("last_status_frame"):
                    joint["issues"].append("missing_status_frame")
                joint["passed"] = not joint["issues"]
            except Exception as exc:
                joint["issues"].append(f"read_failed:{exc}")
            result["joints"].append(joint)
    finally:
        driver.disconnect()

    failed = [item for item in result["joints"] if not item["passed"]]
    if failed:
        result["blocking_reasons"].append("joint_readiness_failed")

    result["ready_for_low_gain_enable"] = not result["blocking_reasons"]
    result["ready_for_official_dynamic_zero"] = False
    result["ready_for_demo"] = False
    if result["ready_for_low_gain_enable"]:
        result["next_step"] = "Run low-gain enable hold with real-position confirmation before any official dynamic zero/demo."
    else:
        result["next_step"] = "Do not enable. Resolve blocking_reasons first."

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready_for_low_gain_enable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
