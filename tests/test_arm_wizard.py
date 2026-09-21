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
    shown = service_with_records.arm_wizard_status("OAF26092045")["motor_records"]
    assert shown == [
        {
            "record_id": attached[0]["record_id"],
            "joint_name": attached[0]["joint_name"],
            "motor_type": attached[0]["motor_type"],
            "result": "PASS",
            "created_at": attached[0]["commissioned_at"],
            "attached_at": attached[0]["attached_at"],
        }
    ]
    # The page shows when the motor was commissioned, not when it was linked here:
    # that date is the evidence, and it comes from the single-motor station.
    assert shown[0]["created_at"].startswith("2026-09-17")


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


# ---- building a new arm is the wizard's starting point ---------------------------


def test_a_shipped_arm_is_kept_on_record_but_out_of_the_working_list(service):
    """The wizard is for the arm being built now, not for the ones already sold.

    A released arm with its report filed has shipped. It stays on file - the report has
    to remain reachable - but it does not belong in the list of arms under test.
    """
    service.bind_arm_identity("OAF26092070")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092070.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["linked_jobs"] = [{"job_id": "x", "job_type": "arm_acceptance", "status": "passed"}]
    record["zero_calibration_records"] = [{"status": "passed"}]
    record["demo_validation_records"] = [{"status": "passed"}]
    record["evidence_records"] = [{"evidence_type": "can_health_snapshot", "status": "passed"}]
    record["factory_reports"] = [{"report_id": "r1"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    service.bind_arm_identity("OAF26092071")  # still being tested

    payload = service.arm_wizard_arms()
    assert [item["arm_cn"] for item in payload["arms"]] == ["OAF26092071"]
    assert [item["arm_cn"] for item in payload["completed_arms"]] == ["OAF26092070"]
    assert payload["completed_arms"][0]["report_count"] == 1


def test_a_released_arm_without_a_report_is_still_being_worked_on(service):
    # Released but unsigned is not shipped; it still needs its report.
    service.bind_arm_identity("OAF26092072")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092072.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["linked_jobs"] = [{"job_id": "x", "job_type": "arm_acceptance", "status": "passed"}]
    record["zero_calibration_records"] = [{"status": "passed"}]
    record["demo_validation_records"] = [{"status": "passed"}]
    record["evidence_records"] = [{"evidence_type": "can_health_snapshot", "status": "passed"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    payload = service.arm_wizard_arms()
    assert [item["arm_cn"] for item in payload["arms"]] == ["OAF26092072"]
    assert payload["completed_arms"] == []


def test_the_suggested_serial_skips_numbers_already_used(service):
    first = service.arm_wizard_arms()["next_arm_cn"]
    assert first.startswith("OAF") and first.endswith("01")
    service.arm_wizard_create(first, product_version="openarm_2_0")
    assert service.arm_wizard_arms()["next_arm_cn"] == first[:-2] + "02"


def test_creating_an_arm_opens_its_file_with_the_product_locked_in(service):
    suggested = service.arm_wizard_arms()["next_arm_cn"]
    payload = service.arm_wizard_create(suggested, product_version="openarm_2_0", arm_type="OpenARM Follower")
    assert payload["ok"] is True
    assert payload["product_version"] == "openarm_2_0"

    status = service.arm_wizard_status(suggested)
    by_id = {step["id"]: step for step in status["steps"]}
    assert by_id["identity"]["state"] == "done"
    assert status["next_step"] == "link"


def test_a_serial_that_breaks_the_naming_rule_is_refused(service):
    payload = service.arm_wizard_create("NOT-A-SERIAL", product_version="openarm_1_0")
    assert payload["problem"]["code"] == "arm_cn_invalid"
    assert payload["problem"]["solutions"]


def test_reusing_an_existing_serial_is_refused_with_advice(service):
    suggested = service.arm_wizard_arms()["next_arm_cn"]
    service.arm_wizard_create(suggested, product_version="openarm_1_0")
    payload = service.arm_wizard_create(suggested, product_version="openarm_1_0")
    assert payload["problem"]["code"] == "arm_cn_taken"
    # The operator most likely meant to continue that arm, so say so.
    assert any("继续测" in item for item in payload["problem"]["solutions"])


def test_an_unknown_product_version_cannot_be_recorded(service):
    payload = service.arm_wizard_create("OAF26092073", product_version="openarm_9_9")
    assert payload["problem"]["code"] == "arm_cn_invalid"
    assert not (workstation.FACTORY_ARMS_DIR / "OAF26092073.json").exists()


# ---- grouping and deleting -------------------------------------------------------


def test_the_steps_are_grouped_into_three_phases(service):
    options = service.arm_wizard_options()
    assert [group["id"] for group in options["groups"]] == ["static", "dynamic", "release"]
    assert all(group["label"] and group["purpose"] for group in options["groups"])

    by_group = {}
    for step in options["steps"]:
        by_group.setdefault(step["group"], []).append(step["id"])
    assert by_group["static"] == ["identity", "link", "static", "timeout", "fd_switch"]
    assert by_group["dynamic"] == ["enable", "zero", "gripper", "camera", "demo"]
    assert by_group["release"] == ["gate", "report"]


def test_nothing_that_moves_the_arm_sits_in_the_static_group(service):
    # The group names are a promise to the operator: 静态测试 means the arm stays still.
    for step in service.arm_wizard_options()["steps"]:
        if step["group"] == "static":
            assert step["motion"] is False, step["id"]
        if step["group"] == "release":
            assert step["motion"] is False and step["writes"] is False, step["id"]


def test_the_steps_keep_the_official_order_within_their_groups(service):
    ids = [step["id"] for step in service.arm_wizard_options()["steps"]]
    assert ids.index("identity") < ids.index("link") < ids.index("static") < ids.index("timeout")
    assert ids.index("timeout") < ids.index("enable") < ids.index("zero") < ids.index("demo")
    assert ids.index("demo") < ids.index("gate") < ids.index("report")


def test_a_brand_new_arm_can_be_deleted(service):
    # The case this exists for: wrong product version or a mistyped serial, caught
    # straight away.
    service.arm_wizard_create("OAF26092080", product_version="openarm_2_0")
    assert service.arm_wizard_status("OAF26092080")["deletable"] is True

    payload = service.arm_wizard_delete("OAF26092080")
    assert payload["ok"] is True
    assert not (workstation.FACTORY_ARMS_DIR / "OAF26092080.json").exists()
    # Moved, not destroyed.
    assert (workstation.FACTORY_DIR / "deleted_arms" / "OAF26092080.json").exists()
    assert "OAF26092080" not in [item["arm_cn"] for item in service.arm_wizard_arms()["arms"]]


def test_an_arm_with_any_evidence_cannot_be_deleted(service):
    service.arm_wizard_create("OAF26092081", product_version="openarm_1_0")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092081.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["linked_jobs"] = [{"job_id": "x", "job_type": "arm_acceptance", "status": "failed"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    assert service.arm_wizard_status("OAF26092081")["deletable"] is False
    payload = service.arm_wizard_delete("OAF26092081")
    assert payload["problem"]["code"] == "arm_has_evidence"
    assert path.exists(), "the record must survive a refused delete"


def test_even_one_attached_motor_record_blocks_deletion(service_with_records):
    # A record attached to a joint is evidence about a motor, not just about the arm.
    service_with_records.arm_wizard_create("OAF26092082", product_version="openarm_2_0")
    record_id = service_with_records.arm_wizard_available_motor_records("OAF26092082")["records"][0]["record_id"]
    service_with_records.arm_wizard_attach_motor_record("OAF26092082", record_id)

    assert service_with_records.arm_wizard_status("OAF26092082")["deletable"] is False
    assert service_with_records.arm_wizard_delete("OAF26092082")["problem"]["code"] == "arm_has_evidence"


def test_deleting_an_unknown_arm_says_so(service):
    assert service.arm_wizard_delete("OAF00000000")["problem"]["code"] == "arm_not_found"


def test_the_shipped_arms_are_all_undeletable(service):
    """The arms that have shipped carry evidence, so none of them can be deleted.

    Checked through the read-only path on copies of the records. Calling the delete
    method against the production directory would be one changed condition away from
    destroying a factory record, which is not a risk a test should take.

    Only the shipped arms are checked. An arm being built right now legitimately has no
    evidence yet - that is the whole point of being able to discard it.
    """
    from tests.test_golden_real_arms import BASELINE

    real = Path(__file__).resolve().parent.parent / "artifacts" / "factory" / "arms"
    if not real.exists():
        pytest.skip("production records are not on this machine")
    checked = 0
    for arm_cn in BASELINE:
        path = real / f"{arm_cn}.json"
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        assert service._arm_evidence_count(record) > 0, arm_cn
        checked += 1
    if not checked:
        pytest.skip("none of the baseline arms are on this machine")


def test_deleting_can_keep_the_record_or_erase_it(service):
    # Two different decisions: a serial that might come back, versus one typed wrong
    # thirty seconds ago that should leave no trace.
    service.arm_wizard_create("OAF26092090", product_version="openarm_1_0")
    kept = service.arm_wizard_delete("OAF26092090", mode="archive")
    assert kept["mode"] == "archive" and kept["kept_at"]
    archived = workstation.FACTORY_DIR / "deleted_arms" / "OAF26092090.json"
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8"))["deleted_mode"] == "archive"

    service.arm_wizard_create("OAF26092091", product_version="openarm_1_0")
    purged = service.arm_wizard_delete("OAF26092091", mode="purge")
    assert purged["mode"] == "purge" and purged["kept_at"] is None
    assert not (workstation.FACTORY_DIR / "deleted_arms" / "OAF26092091.json").exists()
    assert not (workstation.FACTORY_ARMS_DIR / "OAF26092091.json").exists()


def test_both_delete_modes_respect_the_evidence_guard(service):
    for index, mode in enumerate(("archive", "purge")):
        arm_cn = f"OAF2609209{index + 2}"
        service.arm_wizard_create(arm_cn, product_version="openarm_1_0")
        path = workstation.FACTORY_ARMS_DIR / f"{arm_cn}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["factory_reports"] = [{"report_id": "r"}]
        path.write_text(json.dumps(record), encoding="utf-8")

        assert service.arm_wizard_delete(arm_cn, mode=mode)["problem"]["code"] == "arm_has_evidence"
        assert path.exists(), f"{mode} must not touch an arm with evidence"


def test_an_unknown_delete_mode_is_refused(service):
    service.arm_wizard_create("OAF26092094", product_version="openarm_1_0")
    with pytest.raises(ValueError, match="mode must be one of"):
        service.arm_wizard_delete("OAF26092094", mode="shred")
    assert (workstation.FACTORY_ARMS_DIR / "OAF26092094.json").exists()


# ---- undoing mistakes ------------------------------------------------------------


def test_attaching_the_wrong_record_is_not_a_one_way_door(service_with_records):
    """Attaching counted as evidence, and evidence blocked deleting the arm.

    One wrong click therefore locked the archive: it could be neither corrected nor
    discarded, and it stayed on disk forever. This is the deadlock that existed before
    detach, and it must not come back.
    """
    service_with_records.arm_wizard_create("OAF26092150", product_version="openarm_2_0")
    record_id = service_with_records.arm_wizard_available_motor_records("OAF26092150")["records"][0]["record_id"]
    service_with_records.arm_wizard_attach_motor_record("OAF26092150", record_id)
    assert service_with_records.arm_wizard_status("OAF26092150")["deletable"] is False

    payload = service_with_records.arm_wizard_detach_motor_record("OAF26092150", record_id)
    assert payload["ok"] is True and payload["attached"] == []
    # Back to an empty archive, so the ordinary delete works again.
    assert service_with_records.arm_wizard_status("OAF26092150")["deletable"] is True
    assert service_with_records.arm_wizard_delete("OAF26092150")["ok"] is True


def test_detaching_leaves_the_motor_record_itself_alone(service_with_records):
    # The record belongs to the motor, not to this arm.
    service_with_records.arm_wizard_create("OAF26092151", product_version="openarm_2_0")
    before = len(service_with_records._load_single_motor_records())
    record_id = service_with_records.arm_wizard_available_motor_records("OAF26092151")["records"][0]["record_id"]
    service_with_records.arm_wizard_attach_motor_record("OAF26092151", record_id)
    service_with_records.arm_wizard_detach_motor_record("OAF26092151", record_id)
    assert len(service_with_records._load_single_motor_records()) == before


def test_detaching_something_that_is_not_attached_says_so(service):
    service.arm_wizard_create("OAF26092152", product_version="openarm_1_0")
    payload = service.arm_wizard_detach_motor_record("OAF26092152", "smr_nope")
    assert payload["problem"]["code"] == "arm_motor_record_mismatch"


def test_an_archive_built_by_mistake_can_be_force_deleted(service):
    # Built with the wrong product version and already scanned: without force it would
    # sit on disk forever, and the serial would stay taken.
    service.arm_wizard_create("OAF26092153", product_version="openarm_1_0")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092153.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["linked_jobs"] = [{"job_id": "x", "job_type": "arm_acceptance", "status": "failed"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    assert service.arm_wizard_delete("OAF26092153")["problem"]["code"] == "arm_has_evidence"

    forced = service.arm_wizard_delete("OAF26092153", force=True)
    assert forced["ok"] is True
    assert not path.exists()
    kept = workstation.FACTORY_DIR / "deleted_arms" / "OAF26092153.json"
    assert kept.exists()
    saved = json.loads(kept.read_text(encoding="utf-8"))
    assert saved["deleted_forced"] is True and saved["deleted_evidence_count"] == 1


def test_force_delete_will_not_purge_a_record_that_exists(service):
    """Force is for an archive that should not exist, not for erasing results.

    Withdrawing a record and destroying one are different acts, and only one of them
    should be reachable from a wizard.
    """
    service.arm_wizard_create("OAF26092154", product_version="openarm_1_0")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092154.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["factory_reports"] = [{"report_id": "r"}]
    path.write_text(json.dumps(record), encoding="utf-8")

    payload = service.arm_wizard_delete("OAF26092154", mode="purge", force=True)
    assert payload["problem"]["code"] == "arm_force_delete_keeps_record"
    assert path.exists()
    # The keeping variant is allowed.
    assert service.arm_wizard_delete("OAF26092154", mode="archive", force=True)["ok"] is True


def test_a_report_can_be_withdrawn_without_being_destroyed(service, tmp_path):
    """A report issued against wrong evidence is worse than none - it is signed.

    There was no way to take one back, and reports are by far the largest thing on
    disk. Withdrawing moves the files aside: one that may have left the building has
    to stay reconstructable.
    """
    service.arm_wizard_create("OAF26092155", product_version="openarm_1_0")
    path = workstation.FACTORY_ARMS_DIR / "OAF26092155.json"
    report_dir = tmp_path / "issued"
    report_dir.mkdir()
    html = report_dir / "report.html"
    html.write_text("<html>report</html>", encoding="utf-8")

    record = json.loads(path.read_text(encoding="utf-8"))
    record["factory_reports"] = [{"report_id": "OA-TEST-001", "title": "t", "html_path": str(html)}]
    path.write_text(json.dumps(record), encoding="utf-8")

    payload = service.delete_factory_report("OAF26092155", "OA-TEST-001")
    assert payload["ok"] is True
    assert not html.exists(), "the file should have moved"
    moved = workstation.FACTORY_DIR / "withdrawn_reports" / "OAF26092155" / "report.html"
    assert moved.exists() and moved.read_text(encoding="utf-8") == "<html>report</html>"

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["factory_reports"] == []
    assert after["withdrawn_reports"][0]["report_id"] == "OA-TEST-001"
    assert after["withdrawn_reports"][0]["withdrawn_at"]


def test_withdrawing_an_unknown_report_says_so(service):
    service.arm_wizard_create("OAF26092156", product_version="openarm_1_0")
    assert service.delete_factory_report("OAF26092156", "nope")["problem"]["code"] == "report_not_found"


def test_everything_the_wizard_creates_can_be_undone(service_with_records):
    """The rule behind the three tests above, stated once.

    A wizard that can create a thing and not remove it accumulates mistakes on disk and
    blocks the operator from fixing them.
    """
    for pair in (
        ("arm_wizard_create", "arm_wizard_delete"),
        ("arm_wizard_attach_motor_record", "arm_wizard_detach_motor_record"),
        ("generate_formal_factory_acceptance_report", "delete_factory_report"),
    ):
        for name in pair:
            assert hasattr(service_with_records, name), name
