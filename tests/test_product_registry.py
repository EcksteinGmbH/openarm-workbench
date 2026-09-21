"""The product registry: what a 1.0 arm is, what a 2.0 arm is, and what is not yet known.

The registry describes the system; it never redefines it. Everything 2.0 that drives a
motor is locked until it has been confirmed on hardware, because no hardware can be
attached to this machine at present.
"""
from __future__ import annotations

import pytest
import yaml

import src.workstation as workstation
from tests.test_workstation import shared_socketcan_factory


@pytest.fixture()
def service(monkeypatch):
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", shared_socketcan_factory())
    return workstation.WorkstationService()


def test_both_product_versions_load():
    registry = workstation.ProductRegistry()
    assert registry.known_versions() == ["openarm_1_0", "openarm_2_0"]


def test_registry_never_contradicts_the_profiles(service):
    # The profiles are what production actually ran on. A disagreement means the
    # registry is wrong, and the service refuses to start rather than run on both.
    assert service.product_registry.cross_check(service.profile_manager) == []


def test_a_contradicting_registry_stops_the_service(monkeypatch, tmp_path):
    source = workstation.PRODUCT_REGISTRY_DIR / "openarm_1_0.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    # Same eight IDs, wrong order: structurally valid, but J1 would be 0x08 rather
    # than the 0x01 the profile and every commissioned motor use.
    data["arms"]["right_arm"]["esc_ids"].reverse()
    (tmp_path / "openarm_1_0.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(workstation, "PRODUCT_REGISTRY_DIR", tmp_path)

    with pytest.raises(ValueError, match="disagrees with profiles"):
        workstation.WorkstationService()


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.pop("parameters"), "missing 'parameters'"),
        (lambda d: d["motors"].pop("J8"), "exactly J1-J8"),
        (lambda d: d["arms"]["right_arm"]["esc_ids"].pop(), "8 entries"),
        (lambda d: d["arms"]["right_arm"]["esc_ids"].__setitem__(1, 0x01), "duplicates"),
        (lambda d: d["arms"]["right_arm"]["esc_ids"].__setitem__(1, 0x99), "outside 0x01-0x20"),
        (lambda d: d["arms"]["left_arm"]["esc_ids"].__setitem__(0, 0x01), "share ESC IDs"),
        (lambda d: d["can"]["operation"].__setitem__("mode", "bogus"), "can20 or canfd"),
        (lambda d: d["can"]["operation"].update({"mode": "canfd", "dbitrate": None}), "no dbitrate"),
        (lambda d: d["gripper"].update({"hardware_verified": False, "locked_reason": None}), "no locked_reason"),
    ],
)
def test_a_malformed_registry_is_rejected_at_load(monkeypatch, tmp_path, mutate, message):
    # These all describe an arm that cannot exist. Failing at startup beats discovering
    # it against real hardware.
    data = yaml.safe_load((workstation.PRODUCT_REGISTRY_DIR / "openarm_1_0.yaml").read_text(encoding="utf-8"))
    mutate(data)
    (tmp_path / "openarm_1_0.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(workstation, "PRODUCT_REGISTRY_DIR", tmp_path)

    with pytest.raises(ValueError, match=message):
        workstation.ProductRegistry()


def test_1_0_is_hardware_verified_and_2_0_is_not():
    registry = workstation.ProductRegistry()
    assert registry.lock_reasons("openarm_1_0") == {}

    locks = registry.lock_reasons("openarm_2_0")
    # Every 2.0 section that moves a motor or needs an undecided threshold is locked.
    assert set(locks) == {"can.operation", "gripper", "zero", "camera.gripper", "camera.top"}
    assert all(reason for reason in locks.values()), "a lock without a reason is not actionable"
    # Plan A: 2.0 IDs are configured over classic CAN, and that half IS verified -
    # all 16 motors were commissioned this way on 2026-09-17.
    assert registry.is_locked("openarm_2_0", "commissioning") is False
    assert registry.is_locked("openarm_2_0", "operation") is True


def test_1_0_states_one_gripper_target_for_follower_and_leader_alike():
    # The old code returned -1.0472 for OAF and +1.0472 for OAL, a rule that came from
    # what those historical runs happened to pass rather than from any spec. The
    # official limit table is [-60 deg, 0 deg], so one value applies to both.
    gripper = workstation.ProductRegistry().get("openarm_1_0")["gripper"]
    assert gripper["open_target_rad"] == -1.0472
    assert "open_target_rad_by_arm_side" not in gripper
    assert "open_target_rad_by_arm_cn_prefix" not in gripper


def test_the_leader_anomaly_is_recorded_but_not_applied():
    # Kept as evidence to be settled by the next Leader measured on hardware, not as a
    # code path that keeps re-asserting Leader is mirrored.
    anomaly = workstation.ProductRegistry().get("openarm_1_0")["gripper"]["historical_anomaly"]
    assert anomaly["observed_open_target_rad"] == 1.0472
    assert anomaly["status"] == "recorded_only_not_applied"
    assert anomaly["cause"] and anomaly["resolution"]


def test_2_0_keys_the_gripper_target_on_the_arm_side():
    # A different scheme from 1.0, not a different number: 2.0 mirrors right and left.
    by_side = workstation.ProductRegistry().get("openarm_2_0")["gripper"]["open_target_rad_by_arm_side"]
    assert set(by_side) == {"right_arm", "left_arm"}
    assert by_side["right_arm"] == -by_side["left_arm"]


@pytest.mark.parametrize(
    "product_version, arm_side, expected",
    [
        ("openarm_1_0", "right_arm", -1.0472),
        ("openarm_1_0", "left_arm", -1.0472),
        ("openarm_1_0", None, -1.0472),
        ("openarm_2_0", "right_arm", -1.5708),
        ("openarm_2_0", "left_arm", 1.5708),
    ],
)
def test_gripper_targets_come_from_the_product(product_version, arm_side, expected):
    gripper = workstation.ProductRegistry().get(product_version)["gripper"]
    open_target, close_target = workstation._official_demo_gripper_targets(gripper, arm_side)
    assert open_target == expected
    assert close_target == 0.0


def test_a_product_keyed_on_arm_side_refuses_a_command_that_omits_it():
    # Guessing here would open a 2.0 gripper the wrong way into its mechanical limit.
    gripper = workstation.ProductRegistry().get("openarm_2_0")["gripper"]
    with pytest.raises(ValueError, match="must state --arm_side"):
        workstation._official_demo_gripper_targets(gripper, None)


def test_the_demo_command_takes_its_gripper_target_from_the_product():
    command = ["/x/openarm-can-demo", "--canport", "can0", "--arm_side", "left_arm"]
    gripper = workstation.ProductRegistry().get("openarm_1_0")["gripper"]
    built = workstation._normalize_official_demo_command(command, arm_cn="OAF26080401", gripper=gripper)
    assert "--gripper-open-target" in built
    assert built[built.index("--gripper-open-target") + 1] == "-1.0472"
    # Same value for a Leader CN: the OAF/OAL split is gone.
    built_leader = workstation._normalize_official_demo_command(command, arm_cn="OAL26060201", gripper=gripper)
    assert built_leader[built_leader.index("--gripper-open-target") + 1] == "-1.0472"


def test_the_demo_refuses_to_execute_while_the_gripper_is_unverified(service):
    # The lock has to hold where the motor is driven, not only at the release gate.
    service.bind_arm_identity("OAF26092030", product_version="openarm_2_0")
    with pytest.raises(ValueError, match="拒绝执行 Demo"):
        service.run_official_demo_validation(
            "OAF26092030",
            "/x/openarm-can-demo --canport can0 --arm_side right_arm",
            execute=True,
            confirmations={key: True for key in workstation.DEMO_COMMAND_CONFIRMATIONS},
        )


def test_2_0_gripper_threshold_is_left_unset_rather_than_invented():
    # An invented threshold becomes a PASS/FAIL verdict nobody decided (V5 §9-7).
    assert workstation.ProductRegistry().get("openarm_2_0")["gripper"]["min_travel_rad"] is None


def test_binding_an_arm_defaults_to_1_0_and_records_the_source(service):
    record = service.bind_arm_identity("OAF26092001")
    assert record["product_version"] == "openarm_1_0"
    assert record["product_version_source"] == "default_legacy"


def test_binding_an_arm_as_2_0_is_recorded(service):
    record = service.bind_arm_identity("OAF26092002", product_version="openarm_2_0")
    assert record["product_version"] == "openarm_2_0"
    assert record["product_version_source"] == "declared"


def test_an_unknown_product_version_is_refused(service):
    with pytest.raises(ValueError, match="unknown product_version"):
        service.bind_arm_identity("OAF26092003", product_version="openarm_3_0")


def test_the_product_version_cannot_be_changed_once_recorded(service):
    service.bind_arm_identity("OAF26092004", product_version="openarm_2_0")
    # Re-binding with the same version is fine (the identity form is re-submitted often).
    assert service.bind_arm_identity("OAF26092004", product_version="openarm_2_0")["product_version"] == "openarm_2_0"
    # Switching it would reinterpret every piece of evidence already collected.
    with pytest.raises(ValueError, match="cannot be changed"):
        service.bind_arm_identity("OAF26092004", product_version="openarm_1_0")


def test_the_gate_blocks_a_product_whose_motion_behaviour_is_unverified(service):
    service.bind_arm_identity("OAF26092005", product_version="openarm_2_0")
    gate = service.factory_release_gate("OAF26092005")
    assert gate["release_decision"] == "HOLD"
    assert gate["product_version"] == "openarm_2_0"
    assert any("未经真机验证的锁定项" in item for item in gate["blocking_items"])


def test_the_gate_blocks_evidence_from_the_other_product_version(service):
    arm_cn = "OAF26092006"
    service.bind_arm_identity(arm_cn, product_version="openarm_1_0")
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    job = service.create_job("arm_acceptance", session["device_session_id"], "openarm_v1")
    service.jobs[job["job_id"]].product_line = "openarm_2_0"
    service.attach_job_to_arm(arm_cn, job["job_id"])

    gate = service.factory_release_gate(arm_cn)
    assert gate["release_decision"] == "HOLD"
    assert any("与整机 openarm_1_0 不一致" in item for item in gate["blocking_items"])


def test_evidence_that_states_no_version_is_not_a_conflict(service):
    # Everything recorded before the registry existed states nothing. Holding those
    # arms would be rewriting history, not catching a mistake.
    arm_cn = "OAF26092007"
    service.bind_arm_identity(arm_cn)
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    job = service.create_job("arm_acceptance", session["device_session_id"], "openarm_v1")
    service.attach_job_to_arm(arm_cn, job["job_id"])

    gate = service.factory_release_gate(arm_cn)
    assert not any("不一致" in item for item in gate["blocking_items"])


def test_config_exposes_the_product_versions(service):
    config = service.config()
    assert config["default_product_version"] == "openarm_1_0"
    by_version = {item["product_version"]: item for item in config["product_versions"]}
    assert by_version["openarm_1_0"]["hardware_verified"] is True
    assert by_version["openarm_1_0"]["operation_can_mode"] == "can20"
    assert by_version["openarm_2_0"]["hardware_verified"] is False
    assert by_version["openarm_2_0"]["operation_can_mode"] == "canfd"
    assert by_version["openarm_2_0"]["locked_sections"]


def test_the_2_0_zero_method_matches_the_official_procedure():
    """Official 2.0 zeroing is the jig plus set_zero, and it does not move the arm.

    From docs/official/setup-tutorial.md, quoting the official tutorial:
    `openarm-can-cli -i can0 set_zero --arm`, run with the arm clamped in the
    calibration jig. The implementation in openarm_can 1.4.0
    (setup/cli/commands/zero_position_commands.cpp) sends only a disable frame and a
    set-zero frame per motor - no motion command at all.
    """
    zero = workstation.ProductRegistry().get("openarm_2_0")["zero"]
    assert zero["method"] == "cell_jig_set_zero"
    assert zero["subcommand"] == "set_zero"
    assert zero["motion"] is False
    assert zero["requires_jig"] is True


def test_the_zero_target_ids_follow_plan_a_not_the_official_default():
    # Official runs `--arm` (IDs 1-8) with the left arm on can1. Plan A puts our left
    # arm at 0x09-0x10 on the same can0, and `--id` overrides `--arm`, so each side has
    # to name its own IDs. Using `--arm` for our left arm would zero the right one.
    by_side = workstation.ProductRegistry().get("openarm_2_0")["zero"]["target_ids_by_arm_side"]
    assert by_side["right_arm"] == list(range(0x01, 0x09))
    assert by_side["left_arm"] == list(range(0x09, 0x11))


def test_zeroing_moves_a_1_0_arm_but_not_a_2_0_one(service):
    # 1.0 searches the mechanical limits, which drives the joints. 2.0 is held by the
    # jig. Telling an operator "the arm will move" when it will not is how a warning
    # stops being read.
    def zero_step(product_version):
        steps = service.arm_wizard_options(product_version)["steps"]
        return next(step for step in steps if step["id"] == "zero")

    assert zero_step("openarm_1_0")["motion"] is True
    assert zero_step("openarm_2_0")["motion"] is False
    # Everything else keeps the flag its step declares.
    assert zero_step("openarm_1_0")["group"] == zero_step("openarm_2_0")["group"] == "dynamic"


def test_the_official_reference_is_kept_in_the_repo():
    """The camera answer lives only in the docs, not in openarm_can.

    Grepping the code package alone produced the wrong conclusion once already, so the
    pages the workstation's behaviour depends on are stored under docs/official/ with
    their URL and fetch date.
    """
    from pathlib import Path

    official = Path(__file__).resolve().parent.parent / "docs" / "official"
    pages = {path.name for path in official.glob("*.md")} - {"README.md"}
    assert pages, "no official reference stored"
    for page in pages:
        text = (official / page).read_text(encoding="utf-8")
        assert "https://docs.openarm.dev/" in text, f"{page} has no source URL"
        assert "抓取日期" in text, f"{page} has no fetch date"


def test_the_2_0_gripper_angles_are_marked_unsourced():
    """Official publishes no 2.0 gripper angle, so ours must not look authoritative.

    Re-checked 2026-09-21: the 2.0 gripper and general hardware pages state no angle,
    direction, motor or camera model, and openarm_can 1.4.0 has no gripper angle
    constant. The values here came from the V5 plan and could not be traced further.
    Recording a guess without saying it is one is how a guess becomes a spec.
    """
    gripper = workstation.ProductRegistry().get("openarm_2_0")["gripper"]
    assert gripper["open_target_rad_source"] == "unverified_from_v5_plan"
    assert gripper["hardware_verified"] is False
    assert "没有官方出处" in gripper["locked_reason"]


def test_the_1_0_gripper_target_is_backed_by_real_runs():
    # By contrast 1.0's -1.0472 is carried by 12 arm-sides that ran it and passed.
    gripper = workstation.ProductRegistry().get("openarm_1_0")["gripper"]
    assert gripper["open_target_rad"] == -1.0472
    assert gripper["hardware_verified"] is True
    assert "open_target_rad_source" not in gripper


def test_the_official_diagnose_rules_are_in_the_problem_catalogue():
    """`diagnose --explain` separates faults that look identical from outside.

    From openarm_can 1.4.0 setup/cli/commands/diagnose_commands.cpp. An operator cannot
    tell a missing terminator from a wrong bitrate unaided - both produce no ACK and
    bus-off - so the catalogue has to carry the official way of separating them.
    """
    for code in (
        "bus_reply_on_unlistened_id",
        "bus_daisy_chain_break",
        "bus_silent_scattered",
        "bus_nothing_acknowledges",
    ):
        entry = workstation.SINGLE_MOTOR_PROBLEMS[code]
        assert entry["title"] and entry["message"] and entry["solutions"], code

    # The measurement that actually separates termination from bitrate.
    text = " ".join(workstation.SINGLE_MOTOR_PROBLEMS["bus_nothing_acknowledges"]["solutions"])
    assert "60Ω" in text and "120Ω" in text and "40Ω" in text
    assert "dbitrate" in text
