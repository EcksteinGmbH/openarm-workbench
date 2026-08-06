#!/usr/bin/env python3
"""Short enable/disable safety check for a workstation arm profile."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.damiao_motor_driver import DamiaoSocketCANDriver, Motor
from src.workstation import ProfileManager, _motor_type_from_name


def _snapshot(motor: Motor) -> dict[str, Any]:
    status = motor.getMotorStatus()
    status_code = int(status)
    return {
        "position": float(motor.getPosition()),
        "velocity": float(motor.getVelocity()),
        "torque": float(motor.getTorque()),
        "t_mos": float(motor.getT_MOS()),
        "t_rotor": float(motor.getT_Rotor()),
        "status": getattr(status, "name", f"UNKNOWN_0x{status_code:X}"),
        "status_code": status_code,
        "is_enabled": bool(motor.isEnable),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--bitrate", type=int, default=1000000)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--hold-seconds", type=float, default=0.5)
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    profile = ProfileManager().get_profile(args.profile_id)
    driver = DamiaoSocketCANDriver(channel=args.channel, bitrate=args.bitrate)
    if not driver.connect():
        raise RuntimeError(f"failed to connect SocketCAN channel {args.channel}")

    motors: list[tuple[dict[str, Any], Motor]] = []
    results: list[dict[str, Any]] = []
    try:
        for joint in profile["joints"]:
            motor = Motor(
                _motor_type_from_name(joint["motor_type"]),
                int(joint["target_esc_id"]),
                int(joint["target_mst_id"]),
            )
            driver.ensure_motor(motor)
            motors.append((joint, motor))

        for joint, motor in motors:
            item = {
                "joint_name": joint["joint_name"],
                "esc_id": motor.SlaveID,
                "mst_id": motor.MasterID,
                "enable_ok": False,
                "enabled_snapshot": None,
                "disable_ok": None,
                "disabled_snapshot": None,
                "ok": False,
                "error": None,
            }
            try:
                if args.status_only:
                    item["enable_ok"] = None
                else:
                    item["enable_ok"] = bool(driver.enable(motor))
                    time.sleep(max(0.05, min(args.hold_seconds, 2.0)))
                driver.refresh_motor_status(motor)
                item["enabled_snapshot"] = _snapshot(motor)
                if args.status_only:
                    item["ok"] = item["enabled_snapshot"]["status"] in {"DISABLED", "ENABLED"}
            except Exception as exc:  # pragma: no cover - live hardware helper
                item["error"] = str(exc)
            results.append(item)
    finally:
        for index, (joint, motor) in enumerate(motors):
            if args.status_only:
                continue
            try:
                disabled = bool(driver.disable(motor))
                driver.refresh_motor_status(motor)
                for item in results:
                    if item["joint_name"] == joint["joint_name"]:
                        item["disable_ok"] = disabled
                        item["disabled_snapshot"] = _snapshot(motor)
                        item["ok"] = (
                            bool(item["enable_ok"])
                            and item["enabled_snapshot"] is not None
                            and item["enabled_snapshot"].get("status") == "ENABLED"
                            and disabled
                            and item["disabled_snapshot"].get("status") == "DISABLED"
                        )
                        break
            except Exception as exc:  # pragma: no cover - live hardware helper
                for item in results:
                    if item["joint_name"] == joint["joint_name"]:
                        item["disable_ok"] = False
                        item["error"] = item["error"] or str(exc)
                        break
        driver.disconnect()

    payload = {
        "profile_id": args.profile_id,
        "channel": args.channel,
        "hold_seconds": args.hold_seconds,
        "status_only": args.status_only,
        "motion_command_sent": False,
        "all_disabled_after_check": None
        if args.status_only
        else all(item.get("disabled_snapshot", {}).get("status") == "DISABLED" for item in results),
        "ok": all(item["ok"] for item in results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
