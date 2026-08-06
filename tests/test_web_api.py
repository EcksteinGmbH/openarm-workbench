from __future__ import annotations

import shutil

import pytest

import src.workstation as workstation
from tests.test_workstation import FakeSerialDriver, FakeSocketCANDriver
import web.app as web_app


@pytest.fixture(autouse=True)
def isolated_web_service(monkeypatch, tmp_path):
    monkeypatch.setattr(workstation, "DamiaoMotorDriver", FakeSerialDriver)
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", FakeSocketCANDriver)
    artifacts_dir = tmp_path / "artifacts" / "jobs"
    factory_dir = tmp_path / "artifacts" / "factory"
    monkeypatch.setattr(workstation, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(workstation, "FACTORY_DIR", factory_dir)
    monkeypatch.setattr(workstation, "FACTORY_MOTORS_DIR", factory_dir / "motors")
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", factory_dir / "arms")
    monkeypatch.setattr(workstation, "FACTORY_BUNDLES_DIR", factory_dir / "bundles")
    monkeypatch.setattr(workstation, "FACTORY_ARM_RECORDS_DIR", factory_dir / "arm_records")
    monkeypatch.setattr(workstation, "FACTORY_REPORTS_DIR", factory_dir / "reports")
    monkeypatch.setattr(workstation, "FACTORY_EVIDENCE_DIR", factory_dir / "evidence")
    monkeypatch.setattr(workstation, "VENDOR_MAINTENANCE_DIR", factory_dir / "vendor_maintenance")
    monkeypatch.setattr(workstation, "VENDOR_MAINTENANCE_RECORDS_DIR", factory_dir / "vendor_maintenance" / "records")
    monkeypatch.setattr(workstation, "VENDOR_MAINTENANCE_LOGS_DIR", factory_dir / "vendor_maintenance" / "logs")
    shutil.rmtree(tmp_path / "artifacts", ignore_errors=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    web_app.app.config["TESTING"] = True
    web_app.service = workstation.WorkstationService()
    yield


@pytest.fixture()
def client():
    return web_app.app.test_client()


def _json(response):
    payload = response.get_json()
    assert payload is not None
    return payload


def test_device_connect_job_and_single_scan_api(client):
    response = client.post(
        "/api/device/connect",
        json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}},
    )
    assert response.status_code == 200
    connected = _json(response)
    assert connected["success"] is True
    session_id = connected["device_session_id"]

    response = client.post(
        "/api/device/scan",
        json={"device_session_id": session_id, "job_type": "single_param_config"},
    )
    assert response.status_code == 200
    scan = _json(response)
    assert scan["summary"]["detected"] == 1

    response = client.post(
        "/api/jobs",
        json={
            "device_session_id": session_id,
            "job_type": "single_param_config",
            "profile_id": "openarm_v1",
            "target_joint": "J5",
        },
    )
    assert response.status_code == 200
    job = _json(response)
    assert job["success"] is True
    assert job["status"] == "device_connected"


def test_api_errors_use_json_envelope(client):
    response = client.post(
        "/api/device/scan",
        json={"device_session_id": "missing", "job_type": "single_param_config"},
    )
    payload = _json(response)
    assert response.status_code == 404
    assert payload["success"] is False
    assert "session not found" in payload["message"]


def test_config_exposes_current_per_joint_timeout_policy(client):
    response = client.get("/api/config")
    payload = _json(response)

    assert response.status_code == 200
    assert payload["commissioning_policy"]["arm_timeout_standardization_mode"] == "profile_per_joint"
    assert payload["commissioning_policy"]["whole_arm_timeout_policy"] == {
        "right_arm": {"J1-J8": 5000},
        "left_arm": {"J1-J8": 5000},
    }
    assert payload["commissioning_policy"]["motor_traceability_identity"] == "arm_cn_plus_joint_label"
    assert payload["commissioning_policy"]["zero_controller_sn_hw_behavior"] == "accepted_unassigned_optional_metadata"


def test_arm_timeout_api_rejects_obsolete_uniform_override(client):
    response = client.post(
        "/api/device/arm-timeout-standardization",
        json={
            "device_session_id": "unused",
            "profile_id": "openarm_right_arm_v1",
            "timeout": 1000,
            "confirmed": True,
        },
    )
    payload = _json(response)

    assert response.status_code == 400
    assert payload["success"] is False
    assert "不接受统一 timeout" in payload["message"]


def test_factory_identity_and_release_gate_api(client):
    response = client.post(
        "/api/factory/serials/arm-cn",
        json={"role": "F", "date_code": "260428", "sequence": 1},
    )
    assert response.status_code == 200
    arm_serial = _json(response)
    assert arm_serial["success"] is True
    assert arm_serial["arm_cn"] == "OAF26042801"

    response = client.post(
        "/api/factory/serials/validate",
        json={"type": "arm_cn", "value": arm_serial["arm_cn"]},
    )
    validation = _json(response)
    assert response.status_code == 200
    assert validation["valid"] is True

    response = client.post(
        "/api/factory/arms",
        json={
            "arm_cn": arm_serial["arm_cn"],
            "arm_type": "OpenARM Follower",
            "bom_profile": "openarm_v1",
            "left_arm_installed": False,
            "right_arm_installed": True,
        },
    )
    arm = _json(response)
    assert response.status_code == 200
    assert arm["success"] is True
    assert arm["arm_cn"] == arm_serial["arm_cn"]

    response = client.get(f"/api/factory/release-gate/{arm_serial['arm_cn']}")
    gate = _json(response)
    assert response.status_code == 200
    assert gate["success"] is True
    assert gate["release_decision"] == "HOLD"
    assert "缺少整臂扫描/验收任务挂载" in gate["blocking_items"]


def test_factory_invalid_serial_errors_use_json_envelope(client):
    response = client.post(
        "/api/factory/arms",
        json={"arm_cn": "bad-cn", "arm_type": "OpenARM Follower", "bom_profile": "openarm_v1"},
    )
    payload = _json(response)
    assert response.status_code == 400
    assert payload["success"] is False
    assert "CN 格式" in payload["message"]


def test_vendor_maintenance_record_api(client, tmp_path, monkeypatch):
    dmtool = tmp_path / "DMTool.AppImage"
    dmtool.write_text("#!/bin/sh\n", encoding="utf-8")
    dmtool.chmod(0o755)
    monkeypatch.setattr(workstation, "DMTOOL_APPIMAGE_PATH", dmtool)

    response = client.get("/api/vendor/dmtool/status")
    status = _json(response)
    assert response.status_code == 200
    assert status["dmtool"]["exists"] is True
    assert status["dmtool"]["executable"] is True
    assert status["dmtool"]["automatic_calibration_supported"] is False

    response = client.post(
        "/api/vendor/maintenance-records",
        json={
            "target_label": "R-J4",
            "maintenance_stage": "service_repair",
            "motor_encoder_calibration": "not_required",
            "output_encoder_calibration": "performed",
            "zero_save": "not_performed",
            "operator": "tester",
            "notes": "manual DMTool record",
        },
    )
    record = _json(response)
    assert response.status_code == 200
    assert record["entry"]["target_label"] == "R-J4"
    assert record["entry"]["output_encoder_calibration"] == "performed"
    assert record["entry"]["vendor_tool"]["integration_mode"] == "manual_record_only"

    response = client.get("/api/vendor/maintenance-records")
    records = _json(response)
    assert len(records["records"]) == 1
