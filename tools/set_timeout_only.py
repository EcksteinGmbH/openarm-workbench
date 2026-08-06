#!/usr/bin/env python3
"""Set or verify only Damiao CAN TIMEOUT (register 9) for a workstation arm profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.damiao_motor_driver import DM_variable, DamiaoSocketCANDriver, Motor
from src.workstation import ProfileManager, _motor_type_from_name


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--bitrate", type=int, default=1000000)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--timeout", type=int, default=1000)
    parser.add_argument(
        "--joint-name",
        action="append",
        dest="joint_names",
        help="Limit the operation to an exact profile joint name; repeat for multiple joints.",
    )
    parser.add_argument("--no-save-flash", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()

    profile = ProfileManager().get_profile(args.profile_id)
    selected_names = set(args.joint_names or [])
    profile_names = {joint["joint_name"] for joint in profile["joints"]}
    unknown_names = selected_names - profile_names
    if unknown_names:
        parser.error(f"unknown joint name(s): {', '.join(sorted(unknown_names))}")
    driver = DamiaoSocketCANDriver(channel=args.channel, bitrate=args.bitrate)
    if not driver.connect():
        raise RuntimeError(f"failed to connect SocketCAN channel {args.channel}")

    results = []
    try:
        for joint in profile["joints"]:
            if selected_names and joint["joint_name"] not in selected_names:
                continue
            motor = Motor(
                _motor_type_from_name(joint["motor_type"]),
                int(joint["target_esc_id"]),
                int(joint["target_mst_id"]),
            )
            result = {
                "joint_name": joint["joint_name"],
                "esc_id": motor.SlaveID,
                "mst_id": motor.MasterID,
                "target_timeout": args.timeout,
                "before": None,
                "after_write": None,
                "after_save": None,
                "write_ok": False,
                "save_ok": None,
                "ok": False,
                "error": None,
            }
            try:
                driver.ensure_motor(motor)
                driver.refresh_motor_status(motor)
                if motor.isEnable:
                    driver.disable(motor)

                result["before"] = _as_int(driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.8))
                if args.read_only:
                    result["write_ok"] = None
                    result["save_ok"] = None
                    result["after_write"] = result["before"]
                    result["after_save"] = result["before"]
                else:
                    result["write_ok"] = bool(driver.change_motor_param(motor, DM_variable.TIMEOUT, args.timeout))
                    result["after_write"] = _as_int(driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.8))

                    if not args.no_save_flash and result["after_write"] == args.timeout:
                        result["save_ok"] = bool(driver.save_motor_param(motor))
                        result["after_save"] = _as_int(driver.read_motor_param(motor, DM_variable.TIMEOUT, timeout=0.8))
                    else:
                        result["save_ok"] = False if not args.no_save_flash else None
                        result["after_save"] = result["after_write"]

                result["ok"] = (
                    result["before"] == args.timeout
                    if args.read_only
                    else (
                        result["write_ok"]
                        and result["after_write"] == args.timeout
                        and (args.no_save_flash or (result["save_ok"] and result["after_save"] == args.timeout))
                    )
                )
            except Exception as exc:  # pragma: no cover - live hardware helper
                result["error"] = str(exc)
            results.append(result)
    finally:
        driver.disconnect()

    payload = {
        "profile_id": args.profile_id,
        "channel": args.channel,
        "timeout": args.timeout,
        "read_only": args.read_only,
        "save_flash": False if args.read_only else not args.no_save_flash,
        "joint_names": [item["joint_name"] for item in results],
        "ok": all(item["ok"] for item in results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
