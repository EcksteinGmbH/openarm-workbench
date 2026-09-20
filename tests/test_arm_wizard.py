"""The whole-arm wizard: the official acceptance order, one step at a time.

This layer sequences and guards; every step delegates to the method the engineer tools
have always called, so a 1.0 arm is judged by exactly the code that judged the three
arms already shipped. 2.0 keeps its place in the flow with its steps visible but
locked, each naming what has to be settled first.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.workstation as workstation
from tests.test_workstation import shared_socketcan_factory


FIXTURE_RECORDS = Path(__file__).parent / "golden" / "fixture" / "single_motor_records"


@pytest.fixture()
def service(monkeypatch, tmp_path):
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", shared_socketcan_factory())
    return workstation.WorkstationService()


@pytest.fixture()
def service_with_records(service):
    """A service whose single-motor records are the 16 real commissioned motors."""
    target = workstation.FACTORY_DIR / "single_motor_records"
    target.mkdir(parents=True, exist_ok=True)
    for path in FIXTURE_RECORDS.glob("*.json"):
        (target / path.name).write_bytes(path.read_bytes())
    return service


def test_the_step_order_is_the_official_acceptance_order(service):
    ids = [step["id"] for step in service.arm_wizard_options()["steps"]]
    assert ids == [
        "identity", "link", "static", "timeout", "fd_switch",
        "enable", "zero", "gripper", "camera", "demo", "gate", "report",
    ]


def test_every_step_says_what_it_does_and_whether_it_moves_the_arm(service):
    for step in service.arm_wizard_options()["steps"]:
        assert step["label"] and step["purpose"], step["id"]
        assert isinstance(step["motion"], bool)
    by_id = {step["id"]: step for step in service.arm_wizard_options()["steps"]}
    # An operator has to know before pressing whether the arm is about to move.
    assert {sid for sid, step in by_id.items() if step["motion"]} == {"enable", "zero", "gripper", "demo"}
    # And which ones write to the motors without moving them.
    assert {sid for sid, step in by_id.items() if step["writes"]} == {"timeout", "fd_switch"}


def test_1_0_skips_the_steps_that_do_not_apply_to_it(service):
    steps = {step["id"]: step for step in service.arm_wizard_options("openarm_1_0")["steps"]}
    # 1.0 stays on classic CAN and has no cameras.
    assert steps["fd_switch"]["applies"] is False
    assert steps["camera"]["applies"] is False
    # Everything else is available: this is the flow the three shipped arms went through.
    assert all(step["locked"] is False for step in steps.values())


def test_2_0_keeps_its_place_in_the_flow_but_is_locked(service):
    steps = {step["id"]: step for step in service.arm_wizard_options("openarm_2_0")["steps"]}
    assert steps["fd_switch"]["applies"] is True
    assert steps["camera"]["applies"] is True
    # Locked, and each one says why, so the reason reaches the operator.
    for step_id in ("fd_switch", "zero", "gripper", "camera", "demo"):
        assert steps[step_id]["locked"] is True, step_id
        assert steps[step_id]["locked_reason"], step_id
    # The read-only and parameter steps are not blocked by the unverified sections.
    for step_id in ("identity", "link", "static", "timeout", "enable", "gate", "report"):
        assert steps[step_id]["locked"] is False, step_id


def test_an_unknown_product_version_is_refused(service):
    with pytest.raises(ValueError, match="unknown product_version"):
        service.arm_wizard_options("openarm_3_0")


def test_status_of_a_new_arm_points_at_the_first_real_step(service):
    service.bind_arm_identity("OAF26092040")
    status = service.arm_wizard_status("OAF26092040")
    assert status["ok"] is True
    assert status["product_version"] == "openarm_1_0"
    # Building the archive is what just happened, so the next thing to do is connect.
    assert status["next_step"] == "link"
    by_id = {step["id"]: step for step in status["steps"]}
    assert by_id["identity"]["state"] == "done"
    assert by_id["link"]["state"] == "current"
    assert by_id["static"]["state"] == "pending"
    assert by_id["fd_switch"]["state"] == "skipped"


def test_a_2_0_arm_stops_at_the_first_locked_step(service):
    service.bind_arm_identity("OAF26092041", product_version="openarm_2_0")
    status = service.arm_wizard_status("OAF26092041")
    by_id = {step["id"]: step for step in status["steps"]}
    assert by_id["fd_switch"]["state"] == "locked"
    assert by_id["gripper"]["state"] == "locked"
    # Read-only steps stay reachable, so an operator can still scan and check a 2.0 arm.
    assert status["next_step"] == "link"
    assert status["release_decision"] == "HOLD"


def test_an_unknown_arm_gets_a_problem_not_a_crash(service):
    payload = service.arm_wizard_status("OAF00000000")
    assert payload["ok"] is False
    assert payload["problem"]["code"] == "arm_not_found"
    assert payload["problem"]["solutions"]


def test_a_locked_step_raises_a_dialog_rather_than_a_side_note():
    # The operator cannot clear this from the page, so it must not be a quiet note.
    assert "arm_step_locked" in workstation.BLOCKING_PROBLEM_CODES


def test_progress_is_read_from_evidence_already_on_record(service):
    # An arm tested through the engineer tools before this wizard existed must show its
    # real progress, not start from zero.
    service.bind_arm_identity("OAF26092042")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092042.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["zero_calibration_records"] = [{"status": "passed"}]
    record["demo_validation_records"] = [{"status": "passed"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    by_id = {step["id"]: step for step in service.arm_wizard_status("OAF26092042")["steps"]}
    assert by_id["zero"]["state"] == "done"
    assert by_id["demo"]["state"] == "done"
    assert by_id["gripper"]["state"] == "done"


# ---- attaching the commissioned motors -------------------------------------------


def test_the_sixteen_commissioned_motors_are_offered_to_a_2_0_arm(service_with_records):
    service_with_records.bind_arm_identity("OAF26092043", product_version="openarm_2_0")
    payload = service_with_records.arm_wizard_available_motor_records("OAF26092043")
    assert payload["ok"] is True
    assert len(payload["records"]) == 16
    assert {item["joint_name"] for item in payload["records"]} == {
        f"{side}-J{index}" for side in ("R", "L") for index in range(1, 9)
    }
    assert all(item["attached"] is False for item in payload["records"])


def test_a_1_0_arm_is_not_offered_the_2_0_motors(service_with_records):
    # Mixing evidence across product versions is exactly what the gate exists to stop.
    service_with_records.bind_arm_identity("OAF26092044", product_version="openarm_1_0")
    assert service_with_records.arm_wizard_available_motor_records("OAF26092044")["records"] == []


def test_attaching_a_record_records_the_joint_it_belongs_to(service_with_records):
    service_with_records.bind_arm_identity("OAF26092045", product_version="openarm_2_0")
    record_id = service_with_records.arm_wizard_available_motor_records("OAF26092045")["records"][0]["record_id"]
    payload = service_with_records.arm_wizard_attach_motor_record("OAF26092045", record_id)

    assert payload["ok"] is True
    attached = payload["attached"]
    assert len(attached) == 1
    assert attached[0]["record_id"] == record_id
    assert attached[0]["joint_name"] and attached[0]["attached_at"]
    assert service_with_records.arm_wizard_status("OAF26092045")["motor_records"] == [
        {
            "record_id": attached[0]["record_id"],
            "joint_name": attached[0]["joint_name"],
            "motor_type": attached[0]["motor_type"],
            "result": "PASS",
            "attached_at": attached[0]["attached_at"],
        }
    ]


def test_attaching_a_record_from_the_other_product_is_refused(service_with_records):
    service_with_records.bind_arm_identity("OAF26092046", product_version="openarm_1_0")
    # The records are all 2.0; this arm is 1.0.
    any_record = next(iter(service_with_records._load_single_motor_records()))
    payload = service_with_records.arm_wizard_attach_motor_record("OAF26092046", any_record["record_id"])
    assert payload["problem"]["code"] == "arm_motor_record_mismatch"
    assert "openarm_2_0" in payload["problem"]["detail"]


def test_re_attaching_a_joint_replaces_rather_than_duplicates(service_with_records):
    service_with_records.bind_arm_identity("OAF26092047", product_version="openarm_2_0")
    records = service_with_records.arm_wizard_available_motor_records("OAF26092047")["records"]
    first = records[0]["record_id"]
    service_with_records.arm_wizard_attach_motor_record("OAF26092047", first)
    payload = service_with_records.arm_wizard_attach_motor_record("OAF26092047", first)
    assert len(payload["attached"]) == 1, "a joint must carry exactly one record"


def test_an_unknown_record_is_refused(service_with_records):
    service_with_records.bind_arm_identity("OAF26092048", product_version="openarm_2_0")
    payload = service_with_records.arm_wizard_attach_motor_record("OAF26092048", "smr_does_not_exist")
    assert payload["problem"]["code"] == "arm_motor_record_mismatch"


def test_a_passed_arm_is_not_told_to_redo_steps_that_left_no_record(service):
    # TIMEOUT standardization and the low-gain enable check wrote nothing to the arm
    # record before 0.16.0, so the three arms already shipped have no trace of them.
    # Calling those steps "current" would send an operator to repeat a Flash write on
    # a finished arm.
    service.bind_arm_identity("OAF26092060")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092060.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["zero_calibration_records"] = [{"status": "passed"}]
    record["demo_validation_records"] = [{"status": "passed"}]
    record["evidence_records"] = [{"evidence_type": "can_health_snapshot", "status": "passed"}]
    record["linked_jobs"] = [{"job_id": "x", "job_type": "arm_acceptance", "status": "passed"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    status = service.arm_wizard_status("OAF26092060")
    assert status["release_decision"] == "PASS"
    assert status["next_step"] is None
    by_id = {step["id"]: step for step in status["steps"]}
    assert by_id["timeout"]["state"] == "no_record"
    assert by_id["enable"]["state"] == "no_record"
    assert "current" not in {step["state"] for step in status["steps"]}


def test_a_step_that_runs_now_leaves_a_record_on_the_arm(service, monkeypatch):
    # The fix for the above: give the step an arm_cn and it records itself, so the
    # next arm through the wizard shows real progress.
    from tests.test_workstation import _openarm_arm_registry

    service.bind_arm_identity("OAF26092061")
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry()
    driver.ensure_motor = driver.addMotor

    service.arm_timeout_standardization(
        session["device_session_id"],
        profile_id="openarm_right_arm_v1",
        confirmed=True,
        arm_cn="OAF26092061",
    )

    record = json.loads((workstation.FACTORY_ARMS_DIR / "OAF26092061.json").read_text(encoding="utf-8"))
    kinds = {run["kind"]: run for run in record["command_run_history"]}
    assert kinds["arm_timeout_standardization"]["status"] == "passed"
    assert kinds["arm_timeout_standardization"]["motion_command_sent"] is False

    by_id = {step["id"]: step for step in service.arm_wizard_status("OAF26092061")["steps"]}
    assert by_id["timeout"]["state"] == "done"


def test_recording_is_skipped_when_no_arm_is_named(service):
    # Every existing caller passes no arm_cn and must behave exactly as before.
    from tests.test_workstation import _openarm_arm_registry

    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry()
    driver.ensure_motor = driver.addMotor

    result = service.arm_timeout_standardization(
        session["device_session_id"], profile_id="openarm_right_arm_v1", confirmed=True
    )
    assert result["ok"] is True
    assert list(workstation.FACTORY_ARMS_DIR.glob("*.json")) == []
