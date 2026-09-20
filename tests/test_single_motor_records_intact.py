"""The 16 commissioned motors for the next 2.0 arm must not be lost or altered.

These records are the only evidence that each of those motors was configured and
verified on hardware on 2026-09-17, and they have to end up in that arm's factory
report. They live under `artifacts/`, which is gitignored, so a copy is committed
under `tests/golden/fixture/single_motor_records/`.

The guard checks the invariant, not byte equality: a record legitimately gains fields
later (an arm_cn when it is attached to an arm). What must never change is which motor
it is, what it was configured to, and that it passed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = Path(__file__).parent / "golden" / "fixture" / "single_motor_records"
LIVE_DIR = REPO_ROOT / "artifacts" / "factory" / "single_motor_records"

# The identity of a commissioned motor. Everything here was measured on hardware.
IDENTITY_FIELDS = ("joint_name", "arm_side", "product_line", "motor_type", "result", "record_id")

EXPECTED_JOINTS = {f"{side}-J{index}" for side in ("R", "L") for index in range(1, 9)}


def _load(directory: Path) -> dict:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    }


def _identity(record: dict) -> dict:
    return {
        **{field: record.get(field) for field in IDENTITY_FIELDS},
        "target": record.get("target"),
        "verified": record.get("verified"),
    }


def test_the_backup_holds_all_sixteen_joints_and_they_all_passed():
    records = _load(BACKUP_DIR)
    assert len(records) == 16, f"expected 16 records, found {len(records)}"
    joints = {record["joint_name"] for record in records.values()}
    assert joints == EXPECTED_JOINTS, f"missing: {sorted(EXPECTED_JOINTS - joints)}"
    assert all(record["result"] == "PASS" for record in records.values())
    assert all(record["product_line"] == "openarm_2_0" for record in records.values())


def test_every_joint_has_the_id_pair_its_profile_calls_for():
    # Plan A: right arm ESC 0x01-0x08 / MST 0x11-0x18, left arm 0x09-0x10 / 0x19-0x20.
    records = {record["joint_name"]: record for record in _load(BACKUP_DIR).values()}
    for index in range(1, 9):
        right, left = records[f"R-J{index}"], records[f"L-J{index}"]
        assert right["target"]["ESC_ID"] == index
        assert right["target"]["MST_ID"] == 0x10 + index
        assert left["target"]["ESC_ID"] == 0x08 + index
        assert left["target"]["MST_ID"] == 0x18 + index


def test_the_recorded_values_are_readback_not_target():
    # A report may only state what was read back from the motor after the Flash save.
    # `after` is the raw readback and is present in every record; `verified` is its
    # decoded form, added in 0.9.0 - R-J1 was commissioned on 0.8.0 and predates it.
    for record in _load(BACKUP_DIR).values():
        after, target = record["after"], record["target"]
        assert after["ESC_ID"] == target["ESC_ID"], record["joint_name"]
        assert after["MST_ID"] == target["MST_ID"], record["joint_name"]
        assert after["CTRL_MODE"] == 1, record["joint_name"]          # MIT
        assert after["can_br"] == 4, record["joint_name"]             # 1 Mbps register code
        assert record["motion_performed"] is False
        assert record["zero_saved"] is False

        verified = record.get("verified")
        if verified is not None:
            assert verified["ESC_ID"] == target["ESC_ID"]
            assert verified["MST_ID"] == target["MST_ID"]
            assert verified["CTRL_MODE"] == "MIT"
            assert verified["can_br"] == 1000000


def test_the_one_record_without_a_decoded_readback_is_the_known_one():
    # Guards the exemption above: exactly R-J1, and only because it predates 0.9.0.
    without = {r["joint_name"] for r in _load(BACKUP_DIR).values() if "verified" not in r}
    assert without == {"R-J1"}


@pytest.mark.skipif(not LIVE_DIR.exists(), reason="production records are not on this machine")
def test_the_live_records_still_match_the_backup():
    """Detects loss or silent edits. New fields are allowed; identity is not."""
    backup, live = _load(BACKUP_DIR), _load(LIVE_DIR)
    missing = set(backup) - set(live)
    assert not missing, f"records gone from {LIVE_DIR}: {sorted(missing)}"
    for record_id, expected in backup.items():
        assert _identity(live[record_id]) == _identity(expected), f"{record_id} was altered"
