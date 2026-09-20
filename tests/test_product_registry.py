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


def test_2_0_gripper_keys_on_arm_side_while_1_0_keys_on_the_cn_prefix():
    registry = workstation.ProductRegistry()
    # Not a different number - a different scheme. 1.0 直接按 Follower/Leader 分方向，
    # 2.0 按左右臂分，混用会把夹爪往反方向开。
    assert set(registry.get("openarm_1_0")["gripper"]["open_target_rad_by_arm_cn_prefix"]) == {"OAF", "OAL"}
    assert set(registry.get("openarm_2_0")["gripper"]["open_target_rad_by_arm_side"]) == {"right_arm", "left_arm"}
    assert "open_target_rad_by_arm_side" not in registry.get("openarm_1_0")["gripper"]
    assert "open_target_rad_by_arm_cn_prefix" not in registry.get("openarm_2_0")["gripper"]


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
