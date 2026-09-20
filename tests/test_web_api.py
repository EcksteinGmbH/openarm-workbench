from __future__ import annotations

import shutil

import pytest

import src.workstation as workstation
from tests.test_workstation import FakeSerialDriver, shared_socketcan_factory
import web.app as web_app


@pytest.fixture(autouse=True)
def isolated_web_service(monkeypatch, tmp_path):
    monkeypatch.setattr(workstation, "DamiaoMotorDriver", FakeSerialDriver)
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", shared_socketcan_factory())
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


def test_single_commissioning_api_completes_with_saved_readback_without_zero(client):
    session_id = _json(
        client.post(
            "/api/device/connect",
            json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}},
        )
    )["device_session_id"]
    client.post("/api/device/scan", json={"device_session_id": session_id, "job_type": "single_commissioning"})
    job_id = _json(
        client.post(
            "/api/jobs",
            json={
                "device_session_id": session_id,
                "job_type": "single_commissioning",
                "profile_id": "openarm_v1",
                "target_joint": "J2",
            },
        )
    )["job_id"]
    target = _json(
        client.post(f"/api/jobs/{job_id}/apply-profile", json={"target_joint": "J2", "profile_id": "openarm_v1"})
    )["target_config"]
    assert target["requires_zero"] is False
    assert target["test_profile"] == "saved_readback"

    assert client.post(f"/api/jobs/{job_id}/write-params", json={"target_config": target}).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/verify-params").status_code == 200
    assert client.post(f"/api/jobs/{job_id}/save-flash").status_code == 200
    allowed = _json(client.get(f"/api/jobs/{job_id}"))["allowed_actions"]
    assert "test" in allowed
    assert "zero" not in allowed

    zero = client.post(f"/api/jobs/{job_id}/zero", json={"confirmed": True})
    assert zero.status_code == 400
    assert _json(zero)["success"] is False

    tested = _json(client.post(f"/api/jobs/{job_id}/test", json={"confirmed": True}))
    assert tested["tested"] is True
    assert tested["metrics"]["motion"] is False
    assert _json(client.get(f"/api/jobs/{job_id}"))["job"]["status"] == "passed"

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


def test_single_motor_wizard_api_flow_and_problem_envelope(client, monkeypatch):
    monkeypatch.setattr(web_app.service, "_wizard_can_precheck", lambda channel, bitrate: None)
    options = _json(client.get("/api/single-motor/wizard/options"))
    assert options["defaults"]["product_line"] == "openarm_2_0"
    assert [arm["arm_side"] for arm in options["arms"]] == ["right_arm", "left_arm"]

    identified = _json(client.post("/api/single-motor/wizard/identify", json={"arm_side": "right_arm", "joint": "J1"}))
    assert identified["ok"] is True
    job_id = identified["job_id"]
    assert _json(client.post(f"/api/single-motor/wizard/{job_id}/write"))["ok"] is True
    assert _json(client.post(f"/api/single-motor/wizard/{job_id}/save"))["ok"] is True
    finished = _json(client.post(f"/api/single-motor/wizard/{job_id}/finish"))
    assert finished["ok"] is True
    assert finished["record"]["result"] == "PASS"
    assert _json(client.get("/api/single-motor/records"))["total_records"] == 1

    def explode(*args, **kwargs):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(web_app.service, "_inventory_scan", explode)
    response = client.post("/api/single-motor/wizard/identify", json={})
    payload = _json(response)
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["problem"]["code"] == "unknown_error"
    assert "socket closed" in payload["problem"]["detail"]


def test_single_motor_inspect_api_returns_rows_and_problem_envelope(client, monkeypatch):
    monkeypatch.setattr(web_app.service, "_wizard_can_precheck", lambda channel, bitrate: None)

    payload = _json(client.post("/api/single-motor/inspect", json={"channel": "can0", "bitrate": 1000000}))
    assert payload["ok"] is True and payload["read_only"] is True
    assert payload["scanned_range"] == "0x01-0x20"
    motor = payload["motors"][0]
    assert {"esc_id", "mst_id", "matched_joints", "rows", "status"} <= set(motor)
    assert any(row["field"] == "SN" for row in motor["rows"])

    def explode(*args, **kwargs):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(web_app.service, "_inventory_scan", explode)
    response = client.post("/api/single-motor/inspect", json={})
    assert response.status_code == 200
    assert _json(response)["problem"]["code"] == "unknown_error"


def test_wizard_tabs_hide_task_rail_from_first_paint(client):
    page = client.get("/").data.decode()
    # The rails are hidden by CSS keyed on body[data-primary-flow]; nothing sets that
    # attribute until a tab is clicked, so the markup must already carry the default tab.
    assert '<body data-primary-flow="connectTab">' in page

    css = client.get("/static/css/style.css").data.decode()
    for selector in (
        'body[data-primary-flow="connectTab"]:not(.link-advanced) .left-rail',
        'body[data-primary-flow="motorWorkbenchTab"]:not(.motor-advanced) .left-rail',
    ):
        assert selector in css

    app_js = client.get("/static/js/app.js").data.decode()
    assert "switchPrimaryTab(currentPrimaryTab());" in app_js


def test_blocking_problems_are_flagged_for_the_dialog(client, monkeypatch):
    # No adapter on the machine: nothing in the wizard can get past this, so the
    # envelope must mark it blocking and the page must be able to raise a dialog.
    monkeypatch.setattr(web_app.service, "_list_socketcan_interfaces", lambda: [])
    payload = _json(client.post("/api/link/wizard/detect", json={}))
    assert payload["problem"]["code"] == "adapter_missing"
    assert payload["problem"]["blocking"] is True
    assert payload["problem"]["solutions"]


def test_recoverable_problems_are_not_flagged_as_blocking(client, monkeypatch):
    # A bus with no motor on it is the operator's to fix in place; the in-page panel
    # already says so, and a dialog on every power-up step would only be noise.
    monkeypatch.setattr(web_app.service, "_wizard_can_precheck", lambda channel, bitrate: None)
    monkeypatch.setattr(web_app.service, "_inventory_scan", lambda session, scan_ids: ([], []))
    payload = _json(client.post("/api/link/wizard/bus-check", json={"channel": "can0"}))
    assert payload["problem"]["code"] == "bus_no_motor"
    assert payload["problem"]["blocking"] is False


def test_problem_dialog_is_wired_into_both_wizards(client):
    page = client.get("/").data.decode()
    for element_id in ("problemModal", "problemModalTitle", "problemModalBody", "problemModalRetryBtn", "problemModalCloseBtn"):
        assert f'id="{element_id}"' in page

    css = client.get("/static/css/style.css").data.decode()
    assert ".problem-modal-body" in css

    app_js = client.get("/static/js/app.js").data.decode()
    assert "bindProblemModal();" in app_js

    for module in ("single-motor-wizard", "link-wizard"):
        source = client.get(f"/static/js/{module}.js").data.decode()
        assert "showProblemModal" in source
        assert "raiseIfBlocking(" in source


def test_config_exposes_product_versions_with_their_locks(client):
    config = _json(client.get("/api/config"))
    by_version = {item["product_version"]: item for item in config["product_versions"]}
    assert set(by_version) == {"openarm_1_0", "openarm_2_0"}
    assert by_version["openarm_1_0"]["hardware_verified"] is True
    # The page must be able to tell the operator which 2.0 steps are not usable yet.
    assert by_version["openarm_2_0"]["hardware_verified"] is False
    assert "can.operation" in by_version["openarm_2_0"]["locked_sections"]


def test_binding_an_arm_accepts_and_returns_the_product_version(client):
    payload = _json(client.post("/api/factory/arms", json={"arm_cn": "OAF26092010", "product_version": "openarm_2_0"}))
    assert payload["product_version"] == "openarm_2_0"

    gate = _json(client.get("/api/factory/release-gate/OAF26092010"))
    assert gate["release_decision"] == "HOLD"
    assert gate["product_version"] == "openarm_2_0"


def test_arm_wizard_options_expose_the_official_order_and_2_0_locks(client):
    payload = _json(client.get("/api/arm/wizard/options?product_version=openarm_2_0"))
    ids = [step["id"] for step in payload["steps"]]
    assert ids[0] == "identity" and ids[-1] == "report"
    locked = {step["id"] for step in payload["steps"] if step["locked"]}
    # 2.0 keeps its place in the flow; the page can show why each one waits.
    assert {"fd_switch", "gripper", "camera"} <= locked
    assert all(step["locked_reason"] for step in payload["steps"] if step["locked"])
    assert payload["operation_bus"]["mode"] == "canfd"


def test_arm_wizard_status_and_motor_record_attachment(client):
    _json(client.post("/api/factory/arms", json={"arm_cn": "OAF26092050", "product_version": "openarm_2_0"}))
    status = _json(client.get("/api/arm/wizard/OAF26092050/status"))
    assert status["ok"] is True and status["next_step"] == "link"

    # No commissioned records in this isolated tmp dir, so the list is simply empty.
    records = _json(client.get("/api/arm/wizard/OAF26092050/motor-records"))
    assert records["ok"] is True and records["records"] == []

    refused = _json(client.post("/api/arm/wizard/OAF26092050/motor-records", json={"record_id": "nope"}))
    assert refused["problem"]["code"] == "arm_motor_record_mismatch"


def test_arm_wizard_status_of_an_unknown_arm_is_a_problem_envelope(client):
    payload = _json(client.get("/api/arm/wizard/OAF00000000/status"))
    assert payload["ok"] is False
    assert payload["problem"]["code"] == "arm_not_found"
