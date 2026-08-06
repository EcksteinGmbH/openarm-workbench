"""
CLI for OpenARM CAN2.0 arm communication scanning.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, Optional

from src.workstation import WorkstationService


def _now_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_joint_csv(path: Path, joints: Iterable[Dict[str, Any]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "joint_name",
                "expected_motor_type",
                "expected_esc_id",
                "expected_mst_id",
                "present",
                "comm_ok",
                "actual_esc_id",
                "actual_mst_id",
                "status",
                "issues",
            ],
        )
        writer.writeheader()
        for joint in joints:
            expected = joint.get("expected", {})
            params = joint.get("params", {})
            writer.writerow(
                {
                    "joint_name": joint.get("joint_name"),
                    "expected_motor_type": expected.get("motor_type"),
                    "expected_esc_id": expected.get("target_esc_id"),
                    "expected_mst_id": expected.get("target_mst_id"),
                    "present": joint.get("present"),
                    "comm_ok": joint.get("comm_ok"),
                    "actual_esc_id": params.get("ESC_ID"),
                    "actual_mst_id": params.get("MST_ID"),
                    "status": joint.get("status", {}).get("status"),
                    "issues": ",".join(joint.get("issues", [])),
                }
            )


def _write_unexpected_csv(path: Path, nodes: Iterable[Dict[str, Any]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["current_id", "detected_esc_id", "detected_mst_id", "status", "ctrl_mode"],
        )
        writer.writeheader()
        for node in nodes:
            writer.writerow(
                {
                    "current_id": node.get("current_id"),
                    "detected_esc_id": node.get("detected_esc_id"),
                    "detected_mst_id": node.get("detected_mst_id"),
                    "status": node.get("status", {}).get("status"),
                    "ctrl_mode": node.get("params", {}).get("CTRL_MODE"),
                }
            )


def _copy_artifacts(source_dir: Path, target_dir: Path):
    if source_dir.resolve() == target_dir.resolve():
        return
    for name in ["job.json", "events.jsonl", "report.html"]:
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, target_dir / name)


def run_scan(
    *,
    channel: str,
    bitrate: int,
    profile_id: str,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    service = WorkstationService()
    session = None
    try:
        session = service.connect_device("socketcan", {"channel": channel, "bitrate": bitrate})
        session_id = session["device_session_id"]

        scan = service.scan_device(session_id, "arm_verification", profile_id=profile_id)
        job = service.create_job("arm_verification", session_id, profile_id=profile_id)
        result = service.test(job["job_id"], confirmed=True)
        report = service.report(job["job_id"])
        artifact_dir = Path(report["artifact_dir"])

        target_dir = output_dir or artifact_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        _copy_artifacts(artifact_dir, target_dir)

        metrics = result["metrics"]
        summary_payload = {
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "channel": channel,
            "bitrate": bitrate,
            "profile_id": profile_id,
            "job_id": job["job_id"],
            "passed": bool(result["tested"]),
            "scan_summary": scan.get("summary", {}),
            "metrics": metrics,
            "artifact_dir": str(artifact_dir),
            "report_files": report["files"],
        }

        _write_json(target_dir / "scan_summary.json", summary_payload)
        _write_joint_csv(target_dir / "joint_results.csv", metrics.get("joints", []))
        unexpected = metrics.get("unexpected", [])
        if unexpected:
            _write_unexpected_csv(target_dir / "unexpected_nodes.csv", unexpected)

        return {
            "passed": bool(result["tested"]),
            "output_dir": str(target_dir),
            "artifact_dir": str(artifact_dir),
            "missing": metrics.get("missing", []),
            "unhealthy": metrics.get("unhealthy", []),
            "mismatches": metrics.get("mismatches", []),
            "unexpected": unexpected,
            "duplicate_esc_ids": metrics.get("duplicate_esc_ids", []),
        }
    finally:
        if session is not None:
            service.disconnect_device(session["device_session_id"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenARM CAN2.0 arm communication scanner")
    parser.add_argument("--channel", default="can0", help="SocketCAN channel, default: can0")
    parser.add_argument("--bitrate", type=int, default=1000000, help="CAN2.0 bitrate, default: 1000000")
    parser.add_argument("--profile", default="openarm_v1", help="OpenARM profile id, default: openarm_v1")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for JSON/CSV/report outputs; defaults to the generated artifact directory",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir
    if output_dir is not None:
        output_dir = output_dir / f"scan_{args.profile}_{_now_stamp()}"

    result = run_scan(
        channel=args.channel,
        bitrate=args.bitrate,
        profile_id=args.profile,
        output_dir=output_dir,
    )

    print(f"channel={args.channel} bitrate={args.bitrate} profile={args.profile}")
    print(f"output_dir={result['output_dir']}")
    print(f"artifact_dir={result['artifact_dir']}")
    print(f"missing={len(result['missing'])} unhealthy={len(result['unhealthy'])} mismatches={len(result['mismatches'])}")
    print(f"unexpected={len(result['unexpected'])} duplicate_esc_ids={len(result['duplicate_esc_ids'])}")
    print("result=PASS" if result["passed"] else "result=FAIL")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
