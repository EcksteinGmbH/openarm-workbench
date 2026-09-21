from __future__ import annotations

from pathlib import Path
import copy
import shutil
import uuid

import pytest

from src.formal_factory_report import (
    _passed_command,
    _parse_zero_stdout,
    _latest_low_gain_record,
    _report_person,
    _status_from_demo_stdout,
    _timeout_adjustments,
    render_formal_factory_report,
)
import src.workstation as workstation
from src.damiao_motor_driver import (
    DM_Motor_Type,
    DM_variable,
    DamiaoMotorDriver,
    DamiaoSocketCANDriver,
    Motor,
    Motor_Status,
)


class _FakeBaseDriver:
    def __init__(self, *args, **kwargs):
        self.connected = False
        self.registry = {
            1: {
                "params": {
                    int(DM_variable.KT_Value): 0.55,
                    int(DM_variable.ESC_ID): 1,
                    int(DM_variable.MST_ID): 17,
                    int(DM_variable.CTRL_MODE): 1,
                    int(DM_variable.TIMEOUT): 500,
                    int(DM_variable.can_br): 1000000,
                    int(DM_variable.sw_ver): 100,
                    int(DM_variable.sub_ver): 1,
                    int(DM_variable.SN): 123456,
                    int(DM_variable.Gr): 6,
                    int(DM_variable.PMAX): 12,
                    int(DM_variable.VMAX): 30,
                    int(DM_variable.TMAX): 10,
                },
                "position": 0.02,
                "velocity": 0.0,
                "torque": 0.0,
                "mos": 30.0,
                "rotor": 35.0,
                "status": Motor_Status.DISABLED,
            }
        }
        self.motors = {}
        self.calls = []

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def addMotor(self, motor):
        self.motors[motor.SlaveID] = motor
        if motor.MasterID:
            self.motors[motor.MasterID] = motor
        return True

    def removeMotor(self, motor):
        for key in [motor.SlaveID, motor.MasterID]:
            self.motors.pop(key, None)

    def _entry(self, motor):
        return self.registry.get(motor.SlaveID)

    def read_motor_param(self, motor, rid, timeout=None):
        self.addMotor(motor)
        entry = self._entry(motor)
        if not entry:
            return None
        value = entry["params"].get(int(rid))
        if value is not None:
            motor.temp_param_dict[int(rid)] = value
        return value

    def change_motor_param(self, motor, rid, value):
        self.calls.append(("change_motor_param", motor.SlaveID, int(rid), value))
        self.addMotor(motor)
        entry = self._entry(motor)
        if not entry:
            return False
        rid = int(rid)
        if rid == int(DM_variable.ESC_ID):
            self.registry[int(value)] = entry
            del self.registry[motor.SlaveID]
        stored_value = float(value) if rid in {
            int(DM_variable.KT_Value),
            int(DM_variable.Gr),
            int(DM_variable.PMAX),
            int(DM_variable.VMAX),
            int(DM_variable.TMAX),
        } else int(value)
        entry["params"][rid] = stored_value
        motor.temp_param_dict[rid] = stored_value
        return True

    def save_motor_param(self, motor):
        self.calls.append(("save_motor_param", motor.SlaveID))
        return True

    def refresh_motor_status(self, motor):
        self.addMotor(motor)
        entry = self._entry(motor)
        if not entry:
            raise RuntimeError("motor not found")
        motor.recv_data(
            entry["position"],
            entry["velocity"],
            entry["torque"],
            entry["mos"],
            entry["rotor"],
            motor.SlaveID,
            int(entry["status"]),
        )
        return True

    def enable(self, motor):
        self.calls.append(("enable", motor.SlaveID))
        entry = self._entry(motor)
        if entry:
            entry["status"] = Motor_Status.ENABLED
        return True

    def disable(self, motor):
        self.calls.append(("disable", motor.SlaveID))
        entry = self._entry(motor)
        if entry:
            entry["status"] = Motor_Status.DISABLED
            entry["velocity"] = 0.0
            entry["torque"] = 0.0
        return True

    def set_zero_position(self, motor):
        self.calls.append(("set_zero_position", motor.SlaveID))
        entry = self._entry(motor)
        if entry:
            entry["position"] = 0.0
        return True

    def controlMIT(self, motor, kp, kd, q, dq, tau):
        self.calls.append(("controlMIT", motor.SlaveID, q))
        entry = self._entry(motor)
        if entry:
            entry["position"] = q
            entry["velocity"] = dq
            entry["torque"] = tau
            entry["status"] = Motor_Status.ENABLED
        return True


class FakeSerialDriver(_FakeBaseDriver):
    pass


class FakeSocketCANDriver(_FakeBaseDriver):
    pass


def shared_socketcan_factory():
    """Build a DamiaoSocketCANDriver stand-in that always hands back one instance.

    One machine has one CAN bus: reopening the socket - which the wizards now do
    when a scan comes back empty on a session they reused - must see the same
    motors, not a freshly populated registry.
    """
    holder = {}

    def factory(*args, **kwargs):
        if "driver" not in holder:
            holder["driver"] = FakeSocketCANDriver(*args, **kwargs)
        return holder["driver"]

    return factory


def _openarm_arm_registry(
    position: float = 0.02,
    start_esc_id: int = 1,
    right_arm_timeout_policy: bool = False,
):
    registry = {}
    for esc_id in range(start_esc_id, start_esc_id + 8):
        joint_index = esc_id - start_esc_id + 1
        registry[esc_id] = {
            "params": {
                int(DM_variable.KT_Value): 0.55,
                int(DM_variable.ESC_ID): esc_id,
                int(DM_variable.MST_ID): 0x10 + esc_id,
                int(DM_variable.CTRL_MODE): 1,
                # Every profile now targets the same operational TIMEOUT, so a fake arm
                # that matches its profile must use it too. `right_arm_timeout_policy`
                # is kept for callers that still pass it; it no longer changes anything.
                int(DM_variable.TIMEOUT): workstation.WHOLE_ARM_TARGET_TIMEOUT,
                int(DM_variable.can_br): 1000000,
                int(DM_variable.sw_ver): 100,
                int(DM_variable.sub_ver): 1,
                int(DM_variable.SN): 100000 + esc_id,
                int(DM_variable.Gr): 6,
                int(DM_variable.PMAX): 12,
                int(DM_variable.VMAX): 30,
                int(DM_variable.TMAX): 10,
            },
            "position": position,
            "velocity": 0.0,
            "torque": 0.0,
            "mos": 30.0,
            "rotor": 35.0,
            "status": Motor_Status.DISABLED,
        }
    return registry


@pytest.fixture(autouse=True)
def fake_drivers(monkeypatch, tmp_path):
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
    shutil.rmtree(workstation.ARTIFACTS_DIR, ignore_errors=True)
    shutil.rmtree(workstation.FACTORY_DIR, ignore_errors=True)
    workstation.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def test_single_commissioning_flow():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    scan = service.scan_device(session["device_session_id"], "single_commissioning")
    assert len(scan["candidates"]) == 1

    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J4")
    applied = service.apply_profile(job_info["job_id"], "J4", "openarm_v1")
    assert applied["target_config"]["motor_type"] == "DM-J4340-2EC"

    driver = service.sessions[session["device_session_id"]].driver
    service.write_params(job_info["job_id"], applied["target_config"])
    first_write_index = next(index for index, call in enumerate(driver.calls) if call[0] == "change_motor_param")
    last_disable_before_write = max(index for index, call in enumerate(driver.calls[:first_write_index]) if call[0] == "disable")
    assert last_disable_before_write < first_write_index
    verify = service.verify_params(job_info["job_id"])
    assert verify["verified"] is True

    service.save_flash(job_info["job_id"])
    saved_actions = service.get_job(job_info["job_id"])["allowed_actions"]
    assert "zero" not in saved_actions
    assert "test" in saved_actions
    with pytest.raises(ValueError):
        service.zero(job_info["job_id"], confirmed=True)

    calls_before_readback = len(driver.calls)
    test_result = service.test(job_info["job_id"], confirmed=True)
    assert test_result["tested"] is True
    assert test_result["metrics"]["mode"] == "saved_readback"
    assert test_result["metrics"]["motion"] is False
    readback_calls = {call[0] for call in driver.calls[calls_before_readback:]}
    assert not readback_calls & {"enable", "controlMIT", "set_zero_position", "change_motor_param", "save_motor_param"}

    report = service.report(job_info["job_id"])
    assert "job.json" in report["files"]
    assert Path(report["artifact_dir"]).exists()
    assert service.get_job(job_info["job_id"])["job"]["status"] == "passed"


def test_single_commissioning_expert_zero_then_motion_ping():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    service.scan_device(session["device_session_id"], "single_commissioning", expert_mode=True)
    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J4", expert_mode=True)
    applied = service.apply_profile(job_info["job_id"], "J4", "openarm_v1")
    service.write_params(job_info["job_id"], applied["target_config"])
    service.verify_params(job_info["job_id"])
    service.save_flash(job_info["job_id"])
    assert {"zero", "test"} <= set(service.get_job(job_info["job_id"])["allowed_actions"])

    zero = service.zero(job_info["job_id"], confirmed=True)
    assert zero["zeroed"] is True
    test_result = service.test(job_info["job_id"], confirmed=True)
    assert test_result["tested"] is True
    assert "peak_position" in test_result["metrics"]
    assert service.get_job(job_info["job_id"])["job"]["status"] == "passed"


def test_single_commissioning_saved_readback_fails_on_param_drift():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    service.scan_device(session["device_session_id"], "single_commissioning")
    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J4")
    applied = service.apply_profile(job_info["job_id"], "J4", "openarm_v1")
    service.write_params(job_info["job_id"], applied["target_config"])
    service.verify_params(job_info["job_id"])
    service.save_flash(job_info["job_id"])

    driver = service.sessions[session["device_session_id"]].driver
    esc_id = int(applied["target_config"]["target_esc_id"])
    driver.registry[esc_id]["params"][int(DM_variable.MST_ID)] = 0x7F

    test_result = service.test(job_info["job_id"], confirmed=True)
    assert test_result["tested"] is False
    assert test_result["metrics"]["issues"] == ["param_mismatch"]
    job = service.get_job(job_info["job_id"])
    assert job["job"]["status"] == "failed"
    assert job["issues_summary"]["has_blocking"] is True


def test_line_inventory_can_seed_single_motor_candidate(monkeypatch):
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    session_id = session["device_session_id"]

    inventory = service.line_inventory(session_id)
    assert inventory["summary"]["total_detected"] == 1

    monkeypatch.setattr(service, "_inventory_scan", lambda _session, _ids: ([], []))
    scan = service.scan_device(session_id, "single_param_config", current_id=1, expert_mode=True)

    assert scan["summary"]["detected"] == 1
    assert scan["candidates"][0]["detected_esc_id"] == 1


def test_motor_from_candidate_keeps_zero_mst_id():
    service = workstation.WorkstationService()
    motor = service._motor_from_candidate(
        {
            "current_id": 1,
            "detected_esc_id": 1,
            "detected_mst_id": 0,
            "params": {"ESC_ID": 1, "MST_ID": 0},
        }
    )

    assert motor.SlaveID == 1
    assert motor.MasterID == 0


def test_write_params_updates_master_id_before_esc_id_change():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    session_id = session["device_session_id"]
    service.scan_device(session_id, "single_param_config")
    job_info = service.create_job("single_param_config", session_id, "openarm_left_arm_v1", "L-J2")
    applied = service.apply_profile(job_info["job_id"], "L-J2", "openarm_left_arm_v1")

    service.write_params(job_info["job_id"], applied["target_config"])

    driver = service.sessions[session_id].driver
    assert driver.registry[0x0A]["params"][int(DM_variable.ESC_ID)] == 0x0A
    assert driver.registry[0x0A]["params"][int(DM_variable.MST_ID)] == 0x1A
    assert service.verify_params(job_info["job_id"])["verified"] is True


def test_official_right_and_left_arm_profile_ids_match_delivery_plan():
    service = workstation.WorkstationService()
    right = service.profile_manager.get_profile("openarm_right_arm_v1")
    left = service.profile_manager.get_profile("openarm_left_arm_v1")

    assert [(joint["joint_name"], joint["target_esc_id"], joint["target_mst_id"]) for joint in right["joints"]] == [
        ("R-J1", 0x01, 0x11),
        ("R-J2", 0x02, 0x12),
        ("R-J3", 0x03, 0x13),
        ("R-J4", 0x04, 0x14),
        ("R-J5", 0x05, 0x15),
        ("R-J6", 0x06, 0x16),
        ("R-J7", 0x07, 0x17),
        ("R-J8", 0x08, 0x18),
    ]
    assert [(joint["joint_name"], joint["target_esc_id"], joint["target_mst_id"]) for joint in left["joints"]] == [
        ("L-J1", 0x09, 0x19),
        ("L-J2", 0x0A, 0x1A),
        ("L-J3", 0x0B, 0x1B),
        ("L-J4", 0x0C, 0x1C),
        ("L-J5", 0x0D, 0x1D),
        ("L-J6", 0x0E, 0x1E),
        ("L-J7", 0x0F, 0x1F),
        ("L-J8", 0x10, 0x20),
    ]
    assert left["supported_scan_ids"] == list(range(0x09, 0x11))
    assert left["expected_bus"] == "can0"
    assert [joint["target_timeout"] for joint in right["joints"]] == [5000] * 8
    assert [joint["target_timeout"] for joint in left["joints"]] == [5000] * 8


def test_arm_timeout_standardization_uses_per_joint_profile_targets():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    session_id = session["device_session_id"]
    driver = service.sessions[session_id].driver
    driver.registry = _openarm_arm_registry(right_arm_timeout_policy=True)
    driver.ensure_motor = driver.addMotor
    for entry in driver.registry.values():
        entry["params"][int(DM_variable.TIMEOUT)] = 250

    result = service.arm_timeout_standardization(
        session_id,
        profile_id="openarm_right_arm_v1",
        save_flash=True,
        confirmed=True,
    )

    assert result["ok"] is True
    assert result["timeout_source"] == "profile_per_joint"
    assert list(result["timeout_targets"].values()) == [5000] * 8
    assert [item["target_timeout"] for item in result["results"]] == [5000] * 8
    assert result["motion_command_sent"] is False
    assert [driver.registry[index]["params"][int(DM_variable.TIMEOUT)] for index in range(1, 9)] == [
        5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000
    ]


def test_arm_status_check_enforces_timeout_and_accepts_unassigned_optional_identity_metadata():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    session_id = session["device_session_id"]
    driver = service.sessions[session_id].driver
    driver.registry = _openarm_arm_registry(right_arm_timeout_policy=True)
    driver.ensure_motor = driver.addMotor
    driver.read_params = lambda motor, rids, timeout=0.5: {
        rid.name: driver.read_motor_param(motor, rid, timeout=timeout)
        for rid in rids
    }
    driver.registry[5]["params"][int(DM_variable.TIMEOUT)] = 1000
    driver.registry[5]["params"][int(DM_variable.SN)] = 0
    driver.registry[5]["params"][int(DM_variable.hw_ver)] = 0

    result = service.arm_status_check(
        session_id,
        profile_id="openarm_right_arm_v1",
        sample_count=1,
    )

    joint_5 = result["results"][4]
    assert result["ok"] is False
    assert joint_5["expected_timeout"] == 5000
    assert joint_5["timeout"] == 1000
    assert joint_5["issues"] == ["timeout_mismatch"]
    assert joint_5["metadata_notes"] == []
    assert joint_5["passed"] is False
    assert result["motion_command_sent"] is False


def test_motor_snapshot_preserves_unknown_status_code():
    motor = Motor(DM_Motor_Type.DM4310, 1, 17)
    motor.recv_data(0.0, 0.0, 0.0, 30.0, 35.0, 1, 0x6)

    snapshot = motor.snapshot()
    assert snapshot["status"] == "UNKNOWN_0x6"
    assert snapshot["status_code"] == 0x6
    assert snapshot["has_error"] is False
    assert snapshot["is_healthy"] is False


def test_status_payload_reads_error_from_first_byte_not_position_byte():
    driver = DamiaoSocketCANDriver("can0")
    motor = Motor(DM_Motor_Type.DM4340, 12, 0x1C)
    driver.addMotor(motor)

    driver._process_status_payload([0x0C, 0x82, 0xC4, 0x7F, 0xF7, 0xFE, 0x1C, 0x1A], 0x1C)

    snapshot = motor.snapshot()
    assert motor.motor_id == 12
    assert snapshot["status"] == "DISABLED"
    assert snapshot["status_code"] == 0
    assert snapshot["has_error"] is False


def test_socketcan_status_payload_with_0x55_position_byte_is_not_param_frame():
    class FakeBus:
        def __init__(self):
            self.messages = [
                type(
                    "Msg",
                    (),
                    {
                        "data": [0x0C, 0x5F, 0x55, 0x7F, 0xF8, 0x00, 0x1F, 0x1C],
                        "arbitration_id": 0x1C,
                    },
                )()
            ]

        def recv(self, timeout=0):
            return self.messages.pop(0) if self.messages else None

    driver = DamiaoSocketCANDriver("can0")
    motor = Motor(DM_Motor_Type.DM4340, 12, 0x1C)
    driver.addMotor(motor)
    driver.bus = FakeBus()

    driver._drain(0.01)

    snapshot = motor.snapshot()
    assert snapshot["last_status_frame"]["data_hex"] == "0C5F557FF8001F1C"
    assert snapshot["position"] != 0.0
    assert snapshot["t_mos"] == 31.0
    assert snapshot["t_rotor"] == 28.0


def test_status_payload_preserves_real_error_from_first_byte():
    driver = DamiaoSocketCANDriver("can0")
    motor = Motor(DM_Motor_Type.DM4340, 12, 0x1C)
    driver.addMotor(motor)

    driver._process_status_payload([0x8C, 0x82, 0xC4, 0x7F, 0xF7, 0xFE, 0x1C, 0x1A], 0x1C)

    snapshot = motor.snapshot()
    assert motor.motor_id == 12
    assert snapshot["status"] == "OVERVOLTAGE"
    assert snapshot["status_code"] == 8
    assert snapshot["has_error"] is True


def test_driver_ensure_motor_replaces_stale_id_mapping():
    driver = DamiaoSocketCANDriver("can0")
    old_motor = Motor(DM_Motor_Type.DM4310, 2, 18)
    new_motor = Motor(DM_Motor_Type.DM4310, 2, 18)
    driver.addMotor(old_motor)

    driver.ensure_motor(new_motor)
    driver._process_param_payload([2, 0, 0x33, int(DM_variable.CTRL_MODE), 1, 0, 0, 0], 0x12)

    assert int(DM_variable.CTRL_MODE) in new_motor.temp_param_dict
    assert new_motor.temp_param_dict[int(DM_variable.CTRL_MODE)] == 1
    assert int(DM_variable.CTRL_MODE) not in old_motor.temp_param_dict


def test_socketcan_esc_id_write_accepts_ack_from_new_id(monkeypatch):
    driver = DamiaoSocketCANDriver("can0")
    motor = Motor(DM_Motor_Type.DM4340, 1, 0x1C)
    driver.addMotor(motor)
    monkeypatch.setattr(driver, "_send_frame", lambda arbitration_id, data: None)
    monkeypatch.setattr(
        driver,
        "_drain",
        lambda timeout: driver._process_param_payload(
            [0x0C, 0x00, 0x55, int(DM_variable.ESC_ID), 0x0C, 0x00, 0x00, 0x00],
            0x1C,
        ),
    )

    assert driver.change_motor_param(motor, DM_variable.ESC_ID, 0x0C) is True
    assert motor.SlaveID == 0x0C
    assert driver.motors_map.get(0x0C) is motor
    assert 0x01 not in driver.motors_map


def test_serial_esc_id_write_accepts_ack_from_new_id(monkeypatch):
    driver = DamiaoMotorDriver("/dev/fake")
    motor = Motor(DM_Motor_Type.DM4340, 1, 0x1C)
    driver.addMotor(motor)
    monkeypatch.setattr(driver, "_write_param_frame", lambda target, rid, data: None)
    monkeypatch.setattr(
        driver,
        "recv",
        lambda: driver._process_param_payload(
            [0x0C, 0x00, 0x55, int(DM_variable.ESC_ID), 0x0C, 0x00, 0x00, 0x00],
            0x1C,
        ),
    )

    assert driver.change_motor_param(motor, DM_variable.ESC_ID, 0x0C) is True
    assert motor.SlaveID == 0x0C
    assert driver.motors_map.get(0x0C) is motor
    assert 0x01 not in driver.motors_map


def test_socketcan_single_commissioning_flow():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    scan = service.scan_device(session["device_session_id"], "single_commissioning")
    assert len(scan["candidates"]) == 1

    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J1")
    applied = service.apply_profile(job_info["job_id"], "J1", "openarm_v1")

    service.write_params(job_info["job_id"], applied["target_config"])
    verify = service.verify_params(job_info["job_id"])
    assert verify["verified"] is True

    service.save_flash(job_info["job_id"])
    test_result = service.test(job_info["job_id"], confirmed=True)
    assert test_result["tested"] is True
    assert test_result["metrics"]["mode"] == "saved_readback"
    assert service.get_job(job_info["job_id"])["job"]["status"] == "passed"


def test_single_param_config_flow_and_issues_artifact():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    scan = service.scan_device(session["device_session_id"], "single_param_config")
    assert scan["summary"]["detected"] == 1

    job_info = service.create_job("single_param_config", session["device_session_id"], "openarm_v1", "J5", expert_mode=True)
    applied = service.apply_profile(job_info["job_id"], "J5", "openarm_v1")
    target = dict(applied["target_config"])
    target["target_ctrl_mode"] = "VEL"
    target["target_timeout"] = 750
    target["target_can_br"] = 500000
    target["target_kt_value"] = 0.72
    target["target_gr"] = 8.5
    target["target_pmax"] = 15.0
    target["target_vmax"] = 42.0
    target["target_tmax"] = 13.5

    service.write_params(job_info["job_id"], target)
    verify = service.verify_params(job_info["job_id"])
    assert verify["verified"] is True
    service.save_flash(job_info["job_id"])
    result = service.test(job_info["job_id"], confirmed=True)
    assert result["tested"] is True

    report = service.report(job_info["job_id"])
    assert "issues.json" in report["files"]
    issues_payload = service.issues(job_info["job_id"])
    assert issues_payload["summary"]["total"] == 0
    assert service.get_job(job_info["job_id"])["job"]["status"] == "passed"


def test_single_param_config_keeps_timeout_and_motor_constants_read_only_by_default():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    session_id = session["device_session_id"]
    service.scan_device(session_id, "single_param_config")
    driver = service.sessions[session_id].driver
    before = dict(driver.registry[1]["params"])

    job_info = service.create_job("single_param_config", session_id, "openarm_right_arm_v1", "R-J1")
    applied = service.apply_profile(job_info["job_id"], "R-J1", "openarm_right_arm_v1")
    target = applied["target_config"]

    assert target["target_timeout"] == before[int(DM_variable.TIMEOUT)]
    assert target["timeout_write_policy"] == "read_only_during_single_motor_commissioning"

    service.write_params(job_info["job_id"], target)
    written_rids = [call[2] for call in driver.calls if call[0] == "change_motor_param"]

    assert int(DM_variable.TIMEOUT) not in written_rids
    assert int(DM_variable.Gr) not in written_rids
    assert int(DM_variable.KT_Value) not in written_rids
    assert int(DM_variable.PMAX) not in written_rids
    assert int(DM_variable.VMAX) not in written_rids
    assert int(DM_variable.TMAX) not in written_rids
    assert driver.registry[1]["params"][int(DM_variable.TIMEOUT)] == before[int(DM_variable.TIMEOUT)]


def test_write_params_requires_successful_disable():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    service.scan_device(session["device_session_id"], "single_param_config")
    job_info = service.create_job("single_param_config", session["device_session_id"], "openarm_v1", "J5")
    applied = service.apply_profile(job_info["job_id"], "J5", "openarm_v1")
    driver = service.sessions[session["device_session_id"]].driver
    driver.disable = lambda motor: False

    with pytest.raises(RuntimeError, match="disable failed"):
        service.write_params(job_info["job_id"], applied["target_config"])

    assert service.get_job(job_info["job_id"])["job"]["status"] == "failed"


def test_write_single_target_refuses_enabled_motor():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    service.scan_device(session["device_session_id"], "single_param_config")
    job_info = service.create_job("single_param_config", session["device_session_id"], "openarm_v1", "J5")
    applied = service.apply_profile(job_info["job_id"], "J5", "openarm_v1")
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry[1]["status"] = Motor_Status.ENABLED
    motor = service._motor_from_candidate(service._job(job_info["job_id"]).candidate)

    with pytest.raises(RuntimeError, match="must be disabled"):
        service._write_single_target(service.sessions[session["device_session_id"]], motor, applied["target_config"])

    assert not any(call[0] == "change_motor_param" for call in driver.calls)


def test_arm_verification_reports_missing_and_unexpected_nodes():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = {}
    for esc_id in (1, 2):
        driver.registry[esc_id] = {
            "params": {
                int(DM_variable.ESC_ID): esc_id,
                int(DM_variable.MST_ID): 0x10 + esc_id,
                int(DM_variable.CTRL_MODE): 1,
                int(DM_variable.TIMEOUT): 1000,
                int(DM_variable.can_br): 1000000,
                int(DM_variable.sw_ver): 100,
                int(DM_variable.sub_ver): 1,
                int(DM_variable.SN): 100000 + esc_id,
                int(DM_variable.Gr): 6,
                int(DM_variable.PMAX): 12,
                int(DM_variable.VMAX): 30,
                int(DM_variable.TMAX): 10,
            },
            "position": 0.0,
            "velocity": 0.0,
            "torque": 0.0,
            "mos": 30.0,
            "rotor": 35.0,
            "status": Motor_Status.DISABLED,
        }
    driver.registry[30] = {
        "params": {
            int(DM_variable.ESC_ID): 30,
            int(DM_variable.MST_ID): 46,
            int(DM_variable.CTRL_MODE): 1,
            int(DM_variable.TIMEOUT): 1000,
            int(DM_variable.can_br): 1000000,
            int(DM_variable.sw_ver): 100,
            int(DM_variable.sub_ver): 1,
            int(DM_variable.SN): 999999,
            int(DM_variable.Gr): 6,
            int(DM_variable.PMAX): 12,
            int(DM_variable.VMAX): 30,
            int(DM_variable.TMAX): 10,
        },
        "position": 0.0,
        "velocity": 0.0,
        "torque": 0.0,
        "mos": 30.0,
        "rotor": 35.0,
        "status": Motor_Status.DISABLED,
    }

    scan = service.scan_device(session["device_session_id"], "arm_verification", profile_id="openarm_v1")
    assert scan["summary"]["passed"] is False
    assert scan["summary"]["missing"]
    assert scan["summary"]["unexpected_ids"] == []

    inventory = service.line_inventory(session["device_session_id"])
    assert 30 in inventory["summary"]["detected_esc_ids"]

    job_info = service.create_job("arm_verification", session["device_session_id"], "openarm_v1")
    result = service.test(job_info["job_id"], confirmed=True)
    assert result["tested"] is False
    assert "J3" in result["metrics"]["missing"]
    assert result["metrics"]["unexpected"] == []


def test_single_comm_check_reads_params_without_motion():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    scan = service.scan_device(session["device_session_id"], "single_comm_check")
    assert scan["summary"]["detected"] == 1

    job_info = service.create_job("single_comm_check", session["device_session_id"], "openarm_v1")
    result = service.run_comm_check(job_info["job_id"], confirmed=True)
    assert result["tested"] is True

    job = service.get_job(job_info["job_id"])
    assert job["job"]["status"] == "passed"
    assert job["motors"]["checked_motor"]["params"]["ESC_ID"] == 1


def test_single_comm_check_surfaces_param_read_failure_playbook():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    del driver.registry[1]["params"][int(DM_variable.MST_ID)]

    service.scan_device(session["device_session_id"], "single_comm_check")
    job_info = service.create_job("single_comm_check", session["device_session_id"], "openarm_v1")
    result = service.run_comm_check(job_info["job_id"], confirmed=True)
    assert result["tested"] is False

    issues_payload = service.issues(job_info["job_id"])
    assert any(item["code"] == "param_read_failed" for item in issues_payload["issues"])
    assert any(item["id"] == "sensor_v_broken_case" for item in issues_payload["playbooks"])


def test_arm_comm_scan_reports_bitrate_mismatch():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    for esc_id in range(1, 9):
        driver.registry[esc_id] = {
            "params": {
                int(DM_variable.ESC_ID): esc_id,
                int(DM_variable.MST_ID): 0x10 + esc_id,
                int(DM_variable.CTRL_MODE): 1,
                int(DM_variable.TIMEOUT): 1000,
                int(DM_variable.can_br): 1000000 if esc_id != 4 else 500000,
                int(DM_variable.sw_ver): 100,
                int(DM_variable.sub_ver): 1,
                int(DM_variable.SN): 100000 + esc_id,
                int(DM_variable.Gr): 6,
                int(DM_variable.PMAX): 12,
                int(DM_variable.VMAX): 30,
                int(DM_variable.TMAX): 10,
            },
            "position": 0.0,
            "velocity": 0.0,
            "torque": 0.0,
            "mos": 30.0,
            "rotor": 35.0,
            "status": Motor_Status.DISABLED,
        }

    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_v1")
    assert scan["summary"]["passed"] is False
    assert "J4" in scan["summary"]["bitrate_mismatches"]
    assert scan["candidates"][0]["consistency_matrix"]
    assert any(row["field"] == "KT_Value" for row in scan["candidates"][0]["consistency_matrix"])

    job_info = service.create_job("arm_comm_scan", session["device_session_id"], "openarm_v1")
    result = service.run_arm_scan(job_info["job_id"], confirmed=True)
    assert result["tested"] is False
    assert "J4" in result["metrics"]["summary"]["bitrate_mismatches"]


def test_arm_comm_scan_uses_bounded_detail_param_timeout():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0, start_esc_id=1)
    driver.arm_scan_param_read_timeout = 0.07
    read_timeouts = []
    original_read = driver.read_motor_param

    def recording_read(motor, rid, timeout=None):
        read_timeouts.append((int(motor.SlaveID), int(rid), timeout))
        return original_read(motor, rid, timeout=timeout)

    driver.read_motor_param = recording_read

    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_v1")

    detail_reads = [item for item in read_timeouts if item[2] == 0.07]
    assert scan["summary"]["total_present"] == 8
    assert len(detail_reads) == 8 * len(workstation.ARM_VERIFY_RIDS)


def test_arm_comm_scan_accepts_damiao_can_br_code_for_1mbps():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0, start_esc_id=1)
    for entry in driver.registry.values():
        entry["params"][int(DM_variable.can_br)] = 4

    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_v1")

    assert scan["summary"]["bitrate_mismatches"] == []
    assert all("can_br_mismatch" not in item["issues"] for item in scan["candidates"])
    assert all(
        row["matches"] is not False
        for item in scan["candidates"]
        for row in item["consistency_matrix"]
        if row["field"] == "can_br"
    )


def test_arm_comm_scan_missing_detail_params_do_not_create_false_mismatches():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0, start_esc_id=1)
    driver.registry[1]["status"] = Motor_Status.UNDERVOLTAGE
    driver.arm_scan_param_read_timeout = 0.07
    original_read = driver.read_motor_param

    def fail_detail_reads(motor, rid, timeout=None):
        if timeout == 0.07:
            return None
        return original_read(motor, rid, timeout=timeout)

    driver.read_motor_param = fail_detail_reads

    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_v1")
    first = scan["candidates"][0]

    assert first["status"]["status"] == "UNDERVOLTAGE"
    assert first["status"]["status_code"] == 9
    assert "param_read_failed" in first["issues"]
    assert "can_br_mismatch" not in first["issues"]
    assert "ctrl_mode_mismatch" not in first["issues"]
    assert scan["summary"]["bitrate_mismatches"] == []
    assert scan["summary"]["ctrl_mode_mismatches"] == []
    assert scan["summary"]["total_faults"] == 1


def test_left_arm_scan_uses_delivery_id_range():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0, start_esc_id=9, right_arm_timeout_policy=True)

    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_left_arm_v1")
    assert scan["summary"]["passed"] is True
    assert scan["summary"]["total_present"] == 8
    assert [item["joint_name"] for item in scan["candidates"]] == [f"L-J{index}" for index in range(1, 9)]
    assert [item["params"]["ESC_ID"] for item in scan["candidates"]] == list(range(0x09, 0x11))


def test_arm_scan_unknown_status_is_warning_not_pass():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0, start_esc_id=1)
    driver.registry[2]["status"] = 0x6

    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_v1")
    joint = scan["candidates"][1]
    assert joint["joint_name"] == "J2"
    assert joint["status"]["status"] == "UNKNOWN_0x6"
    assert joint["issues"] == ["status_read_anomaly"]
    assert joint["result_label"] == "WARNING"
    assert joint["comm_ok"] is False
    assert scan["summary"]["passed"] is False
    assert scan["summary"]["status_read_anomalies"] == ["J2"]
    assert scan["summary"]["total_status_read_anomalies"] == 1
    assert scan["summary"]["total_faults"] == 0


def test_probe_joint_unknown_status_is_not_passed():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0, start_esc_id=1)
    driver.registry[2]["status"] = 0x7

    result = service.probe_joint_params(
        session["device_session_id"],
        "J2",
        profile_id="openarm_v1",
        force_inventory=True,
    )
    assert result["status"]["status"] == "UNKNOWN_0x7"
    assert result["issues"] == ["status_read_anomaly"]
    assert result["result_label"] == "WARNING"
    assert result["passed"] is False


def test_arm_scan_repeat_stability_marks_flaky_joint(monkeypatch):
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    runs = [
        {
            "results": [
                {
                    "joint_name": "J8",
                    "expected": {"joint_name": "J8", "motor_type": "DM-J4310-2EC"},
                    "present": True,
                    "params": {"ESC_ID": 8, "MST_ID": 24, "CTRL_MODE": 1, "TIMEOUT": 1000, "can_br": 1000000, "Gr": 6.0, "KT_Value": 0.55, "PMAX": 12.0, "VMAX": 30.0, "TMAX": 10.0},
                    "consistency_matrix": [],
                    "status": {"status": "DISABLED", "has_error": False},
                    "issues": [],
                    "comm_ok": True,
                    "result_label": "PASS",
                }
            ],
            "inventory": [],
            "missing": [],
            "unhealthy": [],
            "mismatches": [],
            "unexpected": [],
            "duplicate_esc_ids": [],
            "passed": True,
            "summary": {"total_expected": 1, "total_present": 1, "total_missing": 0, "total_comm_ok": 1, "total_unexpected": 0, "total_duplicate_ids": 0, "total_mismatches": 0, "total_faults": 0, "missing": [], "unhealthy": [], "mismatches": [], "bitrate_mismatches": [], "ctrl_mode_mismatches": [], "bus_mismatches": [], "matrix_mismatch_joints": [], "unexpected_ids": [], "duplicate_esc_ids": [], "passed": True},
        },
        {
            "results": [
                {
                    "joint_name": "J8",
                    "expected": {"joint_name": "J8", "motor_type": "DM-J4310-2EC"},
                    "present": True,
                    "params": {"ESC_ID": 8, "MST_ID": 24, "CTRL_MODE": 1, "TIMEOUT": 1000, "can_br": 500000, "Gr": 6.0, "KT_Value": 0.55, "PMAX": 12.0, "VMAX": 30.0, "TMAX": 10.0},
                    "consistency_matrix": [],
                    "status": {"status": "DISABLED", "has_error": False},
                    "issues": ["can_br_mismatch"],
                    "comm_ok": False,
                    "result_label": "FAIL",
                }
            ],
            "inventory": [],
            "missing": [],
            "unhealthy": [],
            "mismatches": [{"joint_name": "J8", "issues": ["can_br_mismatch"]}],
            "unexpected": [],
            "duplicate_esc_ids": [],
            "passed": False,
            "summary": {"total_expected": 1, "total_present": 1, "total_missing": 0, "total_comm_ok": 0, "total_unexpected": 0, "total_duplicate_ids": 0, "total_mismatches": 1, "total_faults": 0, "missing": [], "unhealthy": [], "mismatches": [{"joint_name": "J8", "issues": ["can_br_mismatch"]}], "bitrate_mismatches": ["J8"], "ctrl_mode_mismatches": [], "bus_mismatches": [], "matrix_mismatch_joints": [{"joint_name": "J8", "fields": ["can_br"]}], "unexpected_ids": [], "duplicate_esc_ids": [], "passed": False},
        },
    ]

    monkeypatch.setattr(service, "_scan_arm", lambda _session, _profile_id: runs.pop(0))
    scan = service.scan_device(session["device_session_id"], "arm_comm_scan", profile_id="openarm_v1", repeat_count=2, repeat_delay_ms=0)
    assert scan["summary"]["stability"]["repeat_count"] == 2
    assert scan["summary"]["stability"]["flaky_joints"] == ["J8"]
    assert scan["candidates"][0]["stability"]["parameter_changed_fields"] == ["can_br"]
    assert scan["summary"]["shipment_checklist"]["automated"]


def test_arm_acceptance_passes_with_consistent_bus():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = {}
    for esc_id in range(1, 9):
        driver.registry[esc_id] = {
            "params": {
                int(DM_variable.ESC_ID): esc_id,
                int(DM_variable.MST_ID): 0x10 + esc_id,
                int(DM_variable.CTRL_MODE): 1,
                int(DM_variable.TIMEOUT): workstation.WHOLE_ARM_TARGET_TIMEOUT,
                int(DM_variable.can_br): 1000000,
                int(DM_variable.sw_ver): 100,
                int(DM_variable.sub_ver): 1,
                int(DM_variable.SN): 100000 + esc_id,
                int(DM_variable.Gr): 6,
                int(DM_variable.PMAX): 12,
                int(DM_variable.VMAX): 30,
                int(DM_variable.TMAX): 10,
            },
            "position": 0.0,
            "velocity": 0.0,
            "torque": 0.0,
            "mos": 30.0,
            "rotor": 35.0,
            "status": Motor_Status.DISABLED,
        }

    preview = service.scan_device(session["device_session_id"], "arm_acceptance", profile_id="openarm_v1")
    assert preview["summary"]["release_decision"] == "PASS"
    assert preview["summary"]["release_ready"] is True
    assert preview["summary"]["shipment_checklist"]["automated"]
    assert preview["summary"]["shipment_checklist"]["manual"]
    assert preview["summary"]["command_check_mode"] == "safe_readonly"

    job_info = service.create_job("arm_acceptance", session["device_session_id"], "openarm_v1")
    result = service.run_arm_acceptance(job_info["job_id"], confirmed=True)
    assert result["tested"] is True
    assert result["metrics"]["summary"]["release_decision"] == "PASS"
    assert result["metrics"]["summary"]["command_test_failed"] == 0
    assert result["metrics"]["summary"]["command_check_mode"] == "safe_readonly"
    assert all(item.get("command_check") is None for item in result["metrics"]["joints"])
    assert service.get_job(job_info["job_id"])["summary"]["release_decision"] == "PASS"


def test_api_lifecycle(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "serial_bridge", "connection": {"serial_port": "/dev/fake", "baudrate": 115200}})
    assert connect.status_code == 200
    session_id = connect.get_json()["device_session_id"]

    scan = client.post("/api/device/scan", json={"device_session_id": session_id, "job_type": "single_commissioning", "expert_mode": False})
    assert scan.status_code == 200

    job = client.post("/api/jobs", json={"job_type": "single_commissioning", "device_session_id": session_id, "profile_id": "openarm_v1", "target_joint": "J1", "expert_mode": False})
    job_id = job.get_json()["job_id"]

    apply_profile = client.post(f"/api/jobs/{job_id}/apply-profile", json={"target_joint": "J1", "profile_id": "openarm_v1"})
    assert apply_profile.status_code == 200

    payload = client.get(f"/api/jobs/{job_id}")
    assert payload.status_code == 200
    assert payload.get_json()["job"]["job_id"] == job_id


def test_api_run_arm_scan_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]

    job = client.post("/api/jobs", json={"job_type": "arm_comm_scan", "device_session_id": session_id, "profile_id": "openarm_v1"})
    job_id = job.get_json()["job_id"]

    run = client.post(f"/api/jobs/{job_id}/run-arm-scan", json={"confirmed": True})
    assert run.status_code == 200
    assert "metrics" in run.get_json()


def test_api_run_arm_acceptance_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]

    job = client.post("/api/jobs", json={"job_type": "arm_acceptance", "device_session_id": session_id, "profile_id": "openarm_v1"})
    job_id = job.get_json()["job_id"]

    run = client.post(f"/api/jobs/{job_id}/run-arm-acceptance", json={"confirmed": True})
    assert run.status_code == 200
    assert "metrics" in run.get_json()


def test_issues_endpoint_reports_blocking_items(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]
    fake_driver = fake_service.sessions[session_id].driver
    fake_driver.registry = {}
    fake_driver.registry[1] = {
        "params": {
            int(DM_variable.ESC_ID): 1,
            int(DM_variable.MST_ID): 17,
            int(DM_variable.CTRL_MODE): 1,
            int(DM_variable.TIMEOUT): 1000,
            int(DM_variable.can_br): 500000,
            int(DM_variable.sw_ver): 100,
            int(DM_variable.sub_ver): 1,
            int(DM_variable.SN): 100001,
            int(DM_variable.Gr): 6,
            int(DM_variable.PMAX): 12,
            int(DM_variable.VMAX): 30,
            int(DM_variable.TMAX): 10,
            int(DM_variable.KT_Value): 0.55,
        },
        "position": 0.0,
        "velocity": 0.0,
        "torque": 0.0,
        "mos": 30.0,
        "rotor": 35.0,
        "status": Motor_Status.DISABLED,
    }

    job = client.post("/api/jobs", json={"job_type": "arm_verification", "device_session_id": session_id, "profile_id": "openarm_v1"})
    job_id = job.get_json()["job_id"]
    run = client.post(f"/api/jobs/{job_id}/run-arm-scan", json={"confirmed": True})
    assert run.status_code == 200

    issues = client.get(f"/api/jobs/{job_id}/issues")
    assert issues.status_code == 200
    payload = issues.get_json()
    assert payload["summary"]["total"] > 0
    assert payload["summary"]["has_blocking"] is True
    assert payload["playbooks"]


def test_line_inventory_lists_detected_ids():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry[2] = {
        "params": {
            int(DM_variable.ESC_ID): 2,
            int(DM_variable.MST_ID): 18,
            int(DM_variable.CTRL_MODE): 1,
            int(DM_variable.TIMEOUT): 1000,
            int(DM_variable.can_br): 1000000,
            int(DM_variable.sw_ver): 100,
            int(DM_variable.sub_ver): 1,
            int(DM_variable.SN): 100002,
            int(DM_variable.Gr): 6,
            int(DM_variable.PMAX): 12,
            int(DM_variable.VMAX): 30,
            int(DM_variable.TMAX): 10,
        },
        "position": 0.0,
        "velocity": 0.0,
        "torque": 0.0,
        "mos": 30.0,
        "rotor": 35.0,
        "status": Motor_Status.DISABLED,
    }

    inventory = service.line_inventory(session["device_session_id"], "openarm_v1")
    assert inventory["summary"]["total_detected"] >= 2
    assert 1 in inventory["summary"]["detected_esc_ids"]
    assert 2 in inventory["summary"]["detected_esc_ids"]
    assert any(item["matched_joint"] == "J1" for item in inventory["inventory"])
    assert any(item["matched_motor_type"] == "DM-J8009P-2EC" for item in inventory["inventory"])


def test_probe_joint_params_returns_per_field_results():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})

    probe = service.probe_joint_params(session["device_session_id"], "J1", profile_id="openarm_v1")

    assert probe["present"] is True
    assert probe["params"]["ESC_ID"] == 1
    assert probe["params"]["MST_ID"] == 17
    assert any(item["field"] == "CTRL_MODE" for item in probe["param_results"])
    assert all("elapsed_ms" in item for item in probe["param_results"])


def test_probe_joint_params_reports_missing_joint():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = {}

    probe = service.probe_joint_params(session["device_session_id"], "J1", profile_id="openarm_v1", force_inventory=True)

    assert probe["present"] is False
    assert "missing" in probe["issues"]


def test_joint_link_test_passes_for_present_joint():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})

    result = service.joint_link_test(session["device_session_id"], "J1", profile_id="openarm_v1")

    assert result["present"] is True
    assert result["passed"] is True
    assert result["mode"] == "read_only_status_check"
    assert result["after_enable"] is None
    assert result["after_disable"]["status"] == "DISABLED"


def test_joint_micro_response_test_passes_for_present_joint():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})

    result = service.joint_micro_response_test(session["device_session_id"], "J1", profile_id="openarm_v1")

    assert result["present"] is True
    assert result["passed"] is True
    assert result["measurements"]["peak_delta"] > 0
    assert result["measurements"]["final_delta"] <= 0.05


def test_report_html_uses_official_openarm_model_names():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    service.scan_device(session["device_session_id"], "single_commissioning")
    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J4")
    applied = service.apply_profile(job_info["job_id"], "J4", "openarm_v1")
    service.write_params(job_info["job_id"], applied["target_config"])
    service.verify_params(job_info["job_id"])
    service.save_flash(job_info["job_id"])
    service.test(job_info["job_id"], confirmed=True)

    report = service.report(job_info["job_id"])
    report_html = Path(report["artifact_dir"]) / "report.html"
    content = report_html.read_text(encoding="utf-8")
    assert "OpenARM 官方型号" in content
    assert "DM-J4340-2EC" in content


def test_api_line_inventory_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]

    inventory = client.post("/api/device/line-inventory", json={"device_session_id": session_id, "profile_id": "openarm_v1"})
    assert inventory.status_code == 200
    payload = inventory.get_json()
    assert payload["summary"]["total_detected"] >= 1
    assert "inventory" in payload


def test_api_probe_joint_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]

    probe = client.post(
        "/api/device/probe-joint",
        json={
            "device_session_id": session_id,
            "joint_name": "J1",
            "profile_id": "openarm_v1",
            "timeout_per_param": 0.2,
        },
    )
    assert probe.status_code == 200
    payload = probe.get_json()
    assert payload["present"] is True
    assert payload["params"]["ESC_ID"] == 1


def test_api_joint_link_test_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]

    response = client.post(
        "/api/device/joint-link-test",
        json={"device_session_id": session_id, "joint_name": "J1", "profile_id": "openarm_v1"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["present"] is True
    assert payload["passed"] is True


def test_api_joint_micro_response_test_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    connect = client.post("/api/device/connect", json={"transport": "socketcan", "connection": {"channel": "can0", "bitrate": 1000000}})
    session_id = connect.get_json()["device_session_id"]

    response = client.post(
        "/api/device/joint-micro-response-test",
        json={"device_session_id": session_id, "joint_name": "J1", "profile_id": "openarm_v1"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["present"] is True
    assert payload["passed"] is True


def test_factory_identity_and_bundle_flow():
    service = workstation.WorkstationService()
    arm = service.bind_arm_identity("OAF26042701")
    motor = service.bind_motor_identity(
        motor_sn="DM-J4310-2EC-F0526042701",
        motor_type="DM-J4310-2EC",
        installed_joint="J5",
        arm_cn="OAF26042701",
        esc_id=5,
        mst_id=21,
    )
    assigned = service.assign_joint_motor(
        arm_cn="OAF26042701",
        joint_name="J5",
        motor_sn="DM-J4310-2EC-F0526042701",
        esc_id=5,
        mst_id=21,
        motor_type="DM-J4310-2EC",
    )

    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    job = service.create_job("arm_verification", session["device_session_id"], "openarm_v1")
    service.run_arm_scan(job["job_id"], confirmed=True)
    service.attach_job_to_arm("OAF26042701", job["job_id"])
    service.attach_job_to_motor("DM-J4310-2EC-F0526042701", job["job_id"])
    zero_record = service.record_zero_calibration(
        arm_cn="OAF26042701",
        calibration_scope="right_arm",
        status="passed",
        operator="QC-A01",
        linked_job_id=job["job_id"],
    )
    demo_record = service.record_demo_validation(
        arm_cn="OAF26042701",
        demo_name="official_demo",
        validation_scope="official_demo",
        status="passed",
        operator="QC-A01",
        linked_job_id=job["job_id"],
    )
    bundle = service.build_factory_bundle("OAF26042701")

    overview = service.factory_overview()
    assert arm["arm_cn"] == "OAF26042701"
    assert motor["motor_sn"] == "DM-J4310-2EC-F0526042701"
    assert assigned["arm"]["joint_bindings"]["J5"]["motor_sn"] == "DM-J4310-2EC-F0526042701"
    assert zero_record["entry"]["status"] == "passed"
    assert demo_record["entry"]["status"] == "passed"
    assert overview["summary"]["arm_count"] >= 1
    assert overview["summary"]["motor_count"] >= 1
    assert overview["summary"]["zero_calibration_count"] >= 1
    assert overview["summary"]["demo_validation_count"] >= 1
    assert Path(bundle["bundle_dir"]).exists()
    assert Path(bundle["archive_path"]).exists()
    assert (Path(bundle["bundle_dir"]) / "zero_calibration_records.json").exists()
    assert (Path(bundle["bundle_dir"]) / "demo_validation_records.json").exists()
    assert (Path(bundle["bundle_dir"]) / "factory_records" / "zero_calibration").exists()
    assert (Path(bundle["bundle_dir"]) / "factory_records" / "demo_validation").exists()


def test_factory_workflows_finalize_into_records():
    service = workstation.WorkstationService()
    service.bind_arm_identity("OAF26042703")

    zero_started = service.start_factory_workflow(
        arm_cn="OAF26042703",
        workflow_type="zero_calibration",
        operator="QC-A03",
        calibration_scope="right_arm",
        zero_pose_name="openarm_home",
    )
    assert zero_started["workflow"]["status"] == "active"
    assert [step["id"] for step in zero_started["workflow"]["steps"]] == [
        "official_prereq",
        "pose_align",
        "safety_ready",
        "official_zero_run",
        "power_cycle_verify",
    ]
    for _ in range(len(zero_started["workflow"]["steps"])):
        step_payload = service.advance_factory_workflow(
            arm_cn="OAF26042703",
            workflow_type="zero_calibration",
            action="complete_step",
        )
    assert step_payload["workflow"]["status"] == "awaiting_finalize"
    zero_done = service.advance_factory_workflow(
        arm_cn="OAF26042703",
        workflow_type="zero_calibration",
        action="finalize",
        final_status="passed",
    )
    assert zero_done["record_entry"]["record_type"] == "zero_calibration"

    demo_started = service.start_factory_workflow(
        arm_cn="OAF26042703",
        workflow_type="demo_validation",
        operator="QC-A03",
        demo_name="official_demo",
        validation_scope="official_demo",
    )
    assert demo_started["workflow"]["status"] == "active"
    for _ in range(len(demo_started["workflow"]["steps"])):
        step_payload = service.advance_factory_workflow(
            arm_cn="OAF26042703",
            workflow_type="demo_validation",
            action="complete_step",
        )
    assert step_payload["workflow"]["status"] == "awaiting_finalize"
    demo_done = service.advance_factory_workflow(
        arm_cn="OAF26042703",
        workflow_type="demo_validation",
        action="finalize",
        final_status="passed",
    )
    assert demo_done["record_entry"]["record_type"] == "demo_validation"

    overview = service.factory_overview()
    arm_record = next(item for item in overview["arms"] if item["arm_cn"] == "OAF26042703")
    assert arm_record["active_zero_workflow"] is None
    assert arm_record["active_demo_workflow"] is None
    assert arm_record["zero_calibration_records"]
    assert arm_record["demo_validation_records"]
    assert len(arm_record["workflow_history"]) >= 2


def test_official_factory_command_wrappers(monkeypatch):
    service = workstation.WorkstationService()
    arm_cn = "OAF26042704"
    service.bind_arm_identity(arm_cn)
    service.start_factory_workflow(
        arm_cn=arm_cn,
        workflow_type="zero_calibration",
        operator="QC-A04",
        calibration_scope="right_arm",
    )

    planned = service.run_official_zero_calibration(
        arm_cn=arm_cn,
        canport="can0",
        arm_side="right_arm",
        execute=False,
    )
    assert planned["executed"] is False
    assert planned["command_run"]["command"] == [
        "openarm-can-zero-position-calibration",
        "--canport",
        "can0",
        "--arm_side",
        "right_arm",
        "--skip-gripper-limit-search",
    ]
    assert planned["command_run"]["missing_confirmations"]

    blocked = service.run_official_zero_calibration(
        arm_cn=arm_cn,
        canport="can0",
        arm_side="right_arm",
        execute=True,
        confirmations={"workspace_clear": True},
    )
    assert blocked["executed"] is False
    assert blocked["command_run"]["status"] == "blocked"

    monkeypatch.setattr(workstation.shutil, "which", lambda command: f"/usr/bin/{command}")

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(workstation.subprocess, "run", lambda *args, **kwargs: Completed())
    executed = service.run_official_demo_validation(
        arm_cn=arm_cn,
        command="openarm-can-motor-check 1 17 can0",
        execute=True,
        confirmations={
            "workspace_clear": True,
            "estop_ready": True,
            "zero_calibrated": True,
            "comm_check_passed": True,
            "low_speed": True,
        },
    )
    assert executed["executed"] is True
    assert executed["command_run"]["status"] == "passed"


def test_official_motor_check_and_baudrate_wrappers(monkeypatch):
    service = workstation.WorkstationService()

    planned_check = service.run_official_motor_check(canid=1, recvid=17, socketcan="can0", fd=True)
    assert planned_check["executed"] is False
    assert planned_check["command_run"]["command"] == ["openarm-can-motor-check", "1", "17", "can0", "-fd"]
    assert planned_check["command_run"]["missing_confirmations"]

    planned_baudrate = service.run_official_baudrate_change(canid=1, baudrate=1000000, socketcan="can0", flash=True)
    assert planned_baudrate["command_run"]["command"] == [
        "openarm-can-change-baudrate",
        "--baudrate",
        "1000000",
        "--canid",
        "1",
        "--socketcan",
        "can0",
        "--flash",
    ]

    with pytest.raises(ValueError):
        service.run_official_baudrate_change(canid=1, baudrate=123456, socketcan="can0")

    monkeypatch.setattr(workstation.shutil, "which", lambda command: f"/usr/bin/{command}")

    class Completed:
        returncode = 0
        stdout = "baudrate ok"
        stderr = ""

    monkeypatch.setattr(workstation.subprocess, "run", lambda *args, **kwargs: Completed())
    executed_baudrate = service.run_official_baudrate_change(
        canid=1,
        baudrate=1000000,
        socketcan="can0",
        execute=True,
        confirmations={
            "single_motor_only": True,
            "can20_mode": True,
            "write_limit_ack": True,
            "power_cycle_plan": True,
        },
    )
    assert executed_baudrate["executed"] is True
    assert executed_baudrate["command_run"]["status"] == "passed"


def test_official_zero_output_parser_flags_limit_failure():
    summary = workstation._parse_official_zero_output(
        "[INFO] mechanical stop (Joint J6): 0.8095 rad / 46.38°\n",
        "LimitSearchFailed: Joint J1 did not reach a reliable limit before guard. Refusing reverse motion and zero write.\n",
    )
    assert summary["passed"] is False
    assert summary["zero_written"] is False
    assert summary["restore_completed"] is False
    assert "limit_search_failed" in summary["blocking_items"]
    assert "zero_write_refused" in summary["blocking_items"]
    assert summary["mechanical_stops"][0]["joint"] == "J6"


def test_factory_serial_generation_and_validation():
    service = workstation.WorkstationService()
    arm = service.generate_factory_arm_cn(role="F", date_code="260427", sequence=1)
    assert arm["arm_cn"] == "OAF26042701"
    assert service.validate_factory_arm_cn("OAL26042702")["valid"] is True
    assert service.validate_factory_arm_cn("OA-RF-2026-0001")["valid"] is False

    motor = service.generate_factory_motor_sn(
        motor_type="DM-J8009P-2EC",
        role="F",
        can_id=0x01,
        date_code="260427",
        sequence=1,
    )
    assert motor["motor_sn"] == "DM-J8009P-2EC-F0126042701"
    validated = service.validate_factory_motor_sn("DM-J4310-2EC-L1026042702")
    assert validated["valid"] is True
    assert validated["parts"]["can_id"] == 0x10


def test_workbench_arm_zero_calibration_records_joint_results():
    service = workstation.WorkstationService()
    arm_cn = "OAF26042705"
    service.bind_arm_identity(arm_cn, left_arm_installed=False, right_arm_installed=True)
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.03)

    blocked = service.calibrate_arm_zero(
        session_id=session["device_session_id"],
        profile_id="openarm_v1",
        arm_cn=arm_cn,
        confirmations={"pose_aligned": True},
    )
    assert blocked["status"] == "blocked"
    assert blocked["missing_confirmations"]

    result = service.calibrate_arm_zero(
        session_id=session["device_session_id"],
        profile_id="openarm_v1",
        arm_cn=arm_cn,
        operator="QC-ZERO",
        confirmations={key: True for key in workstation.WORKBENCH_ZERO_CONFIRMATIONS},
        notes="bench zero",
    )
    assert result["calibrated"] is True
    assert len(result["joint_results"]) == 8
    assert all(item["passed"] for item in result["joint_results"])
    assert all(entry["position"] == 0.0 for entry in driver.registry.values())

    overview = service.factory_overview()
    arm = next(item for item in overview["arms"] if item["arm_cn"] == arm_cn)
    assert arm["zero_calibration_records"][0]["method"] == "workbench_native_zero"
    assert len(arm["zero_calibration_records"][0]["joint_results"]) == 8


def test_workbench_arm_zero_calibration_blocks_on_failed_scan():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.01)
    del driver.registry[8]

    result = service.calibrate_arm_zero(
        session_id=session["device_session_id"],
        profile_id="openarm_v1",
        confirmations={key: True for key in workstation.WORKBENCH_ZERO_CONFIRMATIONS},
    )
    assert result["calibrated"] is False
    assert result["status"] == "blocked_by_comm_scan"
    assert result["blocking_reasons"]


def test_workbench_arm_zero_calibration_marks_failed_zero_retry():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.2)
    calls = {"count": 0}

    def fail_zero_after_retry(motor):
        calls["count"] += 1
        driver.calls.append(("set_zero_position", motor.SlaveID))
        return calls["count"] == 1

    driver.set_zero_position = fail_zero_after_retry

    result = service.calibrate_arm_zero(
        session_id=session["device_session_id"],
        profile_id="openarm_v1",
        confirmations={key: True for key in workstation.WORKBENCH_ZERO_CONFIRMATIONS},
    )

    assert result["calibrated"] is False
    assert result["status"] == "failed"
    assert "zero_command_failed" in result["joint_results"][0]["issues"]
    assert "zero_verify_failed" in result["joint_results"][0]["issues"]


def test_workbench_arm_zero_calibration_clears_failed_zero_after_successful_retry():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.2)
    calls = {"count": 0}

    def fail_once_then_zero(motor):
        calls["count"] += 1
        driver.calls.append(("set_zero_position", motor.SlaveID))
        if calls["count"] == 1:
            return False
        entry = driver.registry.get(motor.SlaveID)
        if entry:
            entry["position"] = 0.0
        return True

    driver.set_zero_position = fail_once_then_zero

    result = service.calibrate_arm_zero(
        session_id=session["device_session_id"],
        profile_id="openarm_v1",
        confirmations={key: True for key in workstation.WORKBENCH_ZERO_CONFIRMATIONS},
    )

    first_joint = result["joint_results"][0]
    assert first_joint["passed"] is True
    assert "zero_command_failed" not in first_joint["issues"]
    assert "zero_verify_failed" not in first_joint["issues"]


def test_factory_report_generation_and_bundle():
    service = workstation.WorkstationService()
    arm_cn = "OAF26042706"
    motor_sn = "DM-J4310-2EC-F0826042706"
    service.bind_arm_identity(arm_cn)
    service.bind_motor_identity(
        motor_sn=motor_sn,
        motor_type="DM-J4310-2EC",
        installed_joint="J8",
        arm_cn=arm_cn,
        esc_id=8,
        mst_id=24,
    )
    motor_report = service.generate_motor_parameter_report(motor_sn)
    assert motor_report["report"]["report_type"] == "motor_parameter_report"
    assert Path(motor_report["report_ref"]["html_path"]).exists()
    assert Path(motor_report["report_ref"]["pdf_path"]).exists()

    service.record_zero_calibration(
        arm_cn=arm_cn,
        calibration_scope="right_arm",
        status="passed",
        operator="QC-A05",
    )
    service.record_demo_validation(
        arm_cn=arm_cn,
        demo_name="official_demo",
        validation_scope="official_demo",
        status="passed",
        operator="QC-A05",
    )
    zero_report = service.generate_zero_calibration_report(arm_cn)
    safety_report = service.generate_safety_test_report(arm_cn)
    factory_report = service.generate_factory_acceptance_report(arm_cn)
    assert zero_report["report"]["report_type"] == "zero_calibration_report"
    assert safety_report["report"]["report_type"] == "safety_test_report"
    assert factory_report["report"]["report_type"] == "factory_acceptance_report"
    assert Path(factory_report["report_ref"]["pdf_path"]).exists()
    assert "attached_report_manifest" in factory_report["report"]["summary"]
    factory_html = Path(factory_report["report_ref"]["html_path"]).read_text(encoding="utf-8")
    assert "Attached Report Manifest" in factory_html
    assert "Motor Parameter Report" not in factory_html
    assert "Whole Arm Factory Test Report" in factory_html
    assert "summary-grid" in factory_html
    assert "Release Gate" in factory_html
    assert "Sign-Off" in factory_html

    bundle = service.build_factory_bundle(arm_cn)
    bundled_reports = Path(bundle["bundle_dir"]) / "factory_reports"
    assert bundled_reports.exists()
    assert any(path.suffix == ".html" for path in bundled_reports.iterdir())
    assert any(path.suffix == ".pdf" for path in bundled_reports.iterdir())


def test_motor_report_includes_link_and_micro_test_results():
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    service.scan_device(session["device_session_id"], "single_param_config")
    job_info = service.create_job("single_param_config", session["device_session_id"], "openarm_v1", "J1")
    service.apply_profile(job_info["job_id"], "J1", "openarm_v1")
    motor_sn = "DM-J8009P-2EC-F0126042711"
    service.bind_motor_identity(
        motor_sn=motor_sn,
        motor_type="DM-J8009P-2EC",
        installed_joint="J1",
        esc_id=1,
        mst_id=17,
    )

    service.joint_link_test(session["device_session_id"], "J1", profile_id="openarm_v1", job_id=job_info["job_id"])
    service.joint_micro_response_test(session["device_session_id"], "J1", profile_id="openarm_v1", job_id=job_info["job_id"])
    report = service.generate_motor_parameter_report(motor_sn, job_id=job_info["job_id"])
    rows = report["report"]["rows"]
    assert any(row[0] == "Link Test" for row in rows)
    assert any(row[0] == "Micro Response Test" for row in rows)


def test_interface_statistics_reads_can_counters(tmp_path):
    service = workstation.WorkstationService()
    stat_dir = tmp_path / "can0" / "statistics"
    stat_dir.mkdir(parents=True)
    values = {
        "rx_packets": "100",
        "tx_packets": "50",
        "rx_errors": "2",
        "tx_errors": "1",
        "rx_dropped": "3",
        "tx_dropped": "4",
    }
    for name, value in values.items():
        (stat_dir / name).write_text(value, encoding="utf-8")

    stats = service._interface_statistics(tmp_path / "can0")
    assert stats["total_packets"] == 150
    assert stats["total_errors"] == 3
    assert stats["total_dropped"] == 7


def test_api_factory_endpoints(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    arm = client.post("/api/factory/arms", json={"arm_cn": "OAF26042707"})
    assert arm.status_code == 200
    assert arm.get_json()["arm_cn"] == "OAF26042707"

    motor = client.post(
        "/api/factory/motors",
        json={
            "motor_sn": "DM-J8009P-2EC-F0126042707",
            "motor_type": "DM-J8009P-2EC",
            "installed_joint": "J1",
            "arm_cn": "OAF26042707",
            "esc_id": 1,
            "mst_id": 17,
        },
    )
    assert motor.status_code == 200
    assert motor.get_json()["motor_sn"] == "DM-J8009P-2EC-F0126042707"

    overview = client.get("/api/factory/overview")
    assert overview.status_code == 200
    assert overview.get_json()["summary"]["arm_count"] >= 1

    zero = client.post(
        "/api/factory/zero-calibration",
        json={
            "arm_cn": "OAF26042707",
            "calibration_scope": "right_arm",
            "status": "passed",
            "operator": "QC-A02",
        },
    )
    assert zero.status_code == 200
    assert zero.get_json()["entry"]["record_type"] == "zero_calibration"

    demo = client.post(
        "/api/factory/demo-validation",
        json={
            "arm_cn": "OAF26042707",
            "demo_name": "official_demo",
            "validation_scope": "official_demo",
            "status": "passed",
            "operator": "QC-A02",
        },
    )
    assert demo.status_code == 200
    assert demo.get_json()["entry"]["record_type"] == "demo_validation"

    workflow_arm_cn = "OAF26042708"
    workflow_arm = client.post("/api/factory/arms", json={"arm_cn": workflow_arm_cn})
    assert workflow_arm.status_code == 200

    zero_workflow = client.post(
        "/api/factory/zero-workflows/start",
        json={
            "arm_cn": workflow_arm_cn,
            "operator": "QC-A02",
            "calibration_scope": "right_arm",
            "zero_pose_name": "openarm_home",
        },
    )
    assert zero_workflow.status_code == 200
    workflow_id = zero_workflow.get_json()["workflow"]["workflow_id"]
    assert workflow_id
    zero_advance = client.post(
        "/api/factory/zero-workflows/advance",
        json={"arm_cn": workflow_arm_cn, "action": "complete_step"},
    )
    assert zero_advance.status_code == 200

    demo_workflow = client.post(
        "/api/factory/demo-workflows/start",
        json={
            "arm_cn": workflow_arm_cn,
            "operator": "QC-A02",
            "demo_name": "official_demo",
            "validation_scope": "official_demo",
        },
    )
    assert demo_workflow.status_code == 200
    demo_advance = client.post(
        "/api/factory/demo-workflows/advance",
        json={"arm_cn": workflow_arm_cn, "action": "complete_step"},
    )
    assert demo_advance.status_code == 200

    command_status = client.get("/api/factory/official-commands")
    assert command_status.status_code == 200
    assert "openarm-can-zero-position-calibration" in command_status.get_json()["commands"]

    zero_command = client.post(
        "/api/factory/zero-workflows/run-official",
        json={"arm_cn": workflow_arm_cn, "canport": "can0", "arm_side": "right_arm", "execute": False},
    )
    assert zero_command.status_code == 200
    assert zero_command.get_json()["command_run"]["execute"] is False

    demo_command = client.post(
        "/api/factory/demo-workflows/run-official",
        json={"arm_cn": workflow_arm_cn, "command": "openarm-can-motor-check 1 17 can0", "execute": False},
    )
    assert demo_command.status_code == 200
    assert demo_command.get_json()["command_run"]["command"][0] == "openarm-can-motor-check"

    report_motor = client.post(
        "/api/factory/reports/motor-parameter",
        json={"motor_sn": "DM-J8009P-2EC-F0126042707"},
    )
    assert report_motor.status_code == 200
    assert report_motor.get_json()["report"]["report_type"] == "motor_parameter_report"
    assert report_motor.get_json()["report_ref"]["pdf_path"].endswith(".pdf")

    report_zero = client.post(
        "/api/factory/reports/zero-calibration",
        json={"arm_cn": workflow_arm_cn},
    )
    assert report_zero.status_code == 200
    assert report_zero.get_json()["report"]["report_type"] == "zero_calibration_report"

    report_safety = client.post(
        "/api/factory/reports/safety-test",
        json={"arm_cn": workflow_arm_cn},
    )
    assert report_safety.status_code == 200
    assert report_safety.get_json()["report"]["report_type"] == "safety_test_report"

    report_factory = client.post(
        "/api/factory/reports/factory-acceptance",
        json={"arm_cn": workflow_arm_cn},
    )
    assert report_factory.status_code == 200
    assert report_factory.get_json()["report"]["report_type"] == "factory_acceptance_report"


def test_interface_status_reports_gs_usb(monkeypatch):
    service = workstation.WorkstationService()
    monkeypatch.setattr(
        service,
        "_list_socketcan_interfaces",
        lambda: [
            {
                "name": "can0",
                "driver": "gs_usb",
                "adapter_kind": "gsusb1002enc",
                "is_gs_usb": True,
                "bitrate": 1000000,
                "state": "UP",
                "mtu": "16",
                "manufacturer": "QinHeng",
                "product": "gsusb1002enc",
                "serial": "ABC123",
                "interface_label": "USB2.0-CAN",
                "bus_info": "1-1.2",
            }
        ],
    )

    status = service.interface_status()
    assert status["recommended_channel"] == "can0"
    assert status["interfaces"][0]["adapter_kind"] == "gsusb1002enc"
    assert status["interfaces"][0]["is_gs_usb"] is True


def test_factory_can_health_and_candump_evidence(monkeypatch):
    service = workstation.WorkstationService()
    arm_cn = "OAF26042709"
    service.bind_arm_identity(arm_cn, left_arm_installed=False, right_arm_installed=True)
    monkeypatch.setattr(
        service,
        "_list_socketcan_interfaces",
        lambda: [
            {
                "name": "can0",
                "driver": "gs_usb",
                "adapter_kind": "gsusb1002enc",
                "is_gs_usb": True,
                "bitrate": 1000000,
                "dbitrate": None,
                "fd_enabled": False,
                "can_state": "ERROR-ACTIVE",
                "berr_tx": 0,
                "berr_rx": 0,
                "state": "UP",
                "mtu": "16",
            }
        ],
    )

    class Completed:
        returncode = 0
        stdout = "4: can0: <NOARP,UP,LOWER_UP,ECHO> state UP\n    can state ERROR-ACTIVE\n    bitrate 1000000\n"
        stderr = ""

    monkeypatch.setattr(service, "_run_system_command", lambda *args, **kwargs: Completed())
    health = service.capture_can_health("can0", arm_cn=arm_cn)
    assert health["status"] == "passed"
    assert Path(health["evidence_ref"]["json_path"]).exists()

    monkeypatch.setattr(workstation.shutil, "which", lambda command: "/usr/bin/candump" if command == "candump" else None)

    class CandumpCompleted:
        returncode = 0
        stdout = "(0.000001) can0 011#0102030405060708\n"
        stderr = ""

    monkeypatch.setattr(workstation.subprocess, "run", lambda *args, **kwargs: CandumpCompleted())
    candump = service.capture_candump_evidence("can0", duration_s=0.5, arm_cn=arm_cn)
    assert candump["status"] == "captured"
    assert Path(candump["evidence_ref"]["log_path"]).exists()

    overview = service.factory_overview()
    arm = next(item for item in overview["arms"] if item["arm_cn"] == arm_cn)
    assert len(arm["evidence_records"]) == 2


def test_factory_can_health_warns_on_dropped_frames(monkeypatch):
    service = workstation.WorkstationService()
    monkeypatch.setattr(
        service,
        "_list_socketcan_interfaces",
        lambda: [{
            "name": "can0",
            "is_gs_usb": True,
            "bitrate": 1000000,
            "can_state": "ERROR-ACTIVE",
            "state": "UP",
            "statistics": {"rx_errors": 0, "tx_errors": 0, "rx_dropped": 0, "tx_dropped": 1},
        }],
    )

    class Completed:
        returncode = 0
        stdout = "can state ERROR-ACTIVE bitrate 1000000"
        stderr = ""

    monkeypatch.setattr(service, "_run_system_command", lambda *args, **kwargs: Completed())
    health = service.capture_can_health("can0")
    assert health["status"] == "warning"
    assert health["checks"]["no_dropped_frames"] is False


def test_formal_report_parsers_enforce_integrity_values():
    good_zero = _parse_zero_stdout(
        "[INFO] post-zero arm q: [0.001, -0.002]\n"
        "[INFO] post-zero gripper q: [0.003]\n"
        "wrote zero position to arm\n"
    )
    bad_zero = _parse_zero_stdout(
        "[INFO] post-zero arm q: [0.021]\n"
        "[INFO] post-zero gripper q: [0.0]\n"
        "wrote zero position to arm\n"
    )
    assert good_zero["passed"] is True
    assert bad_zero["passed"] is False
    assert bad_zero["within_threshold"] is False
    assert _report_person("OpenARM workstation", "Peng Cheng") == "Peng Cheng"
    assert _report_person("OpenARM QA", "Xiang Kun") == "Xiang Kun"

    statuses = _status_from_demo_stdout(
        "--- sample 1/1 ---\n"
        "Arm Motor 9 recv=25 position=0.100000 velocity=0.000000 torque=0.010000 tmos=30 trotor=28\n"
        "DISABLE recv_id=0x19 status={'can_id': 25, 'data_hex': '091234567890ABCD', 'status_code': 0, 'status': 'DISABLED'}\n",
        [{"joint_name": "L-J1", "target_mst_id": 0x19}],
    )
    assert statuses["L-J1"]["position"] == 0.1
    assert statuses["L-J1"]["status"] == "DISABLED"
    assert statuses["L-J1"]["last_status_frame"]["data_hex"] == "091234567890ABCD"


def test_factory_release_gate_passes_with_required_evidence(monkeypatch):
    service = workstation.WorkstationService()
    arm_cn = "OAF26042710"
    service.bind_arm_identity(arm_cn, left_arm_installed=False, right_arm_installed=True)
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    driver.registry = _openarm_arm_registry(position=0.0)
    job_info = service.create_job("arm_comm_scan", session["device_session_id"], "openarm_v1")
    result = service.run_arm_scan(job_info["job_id"], confirmed=True)
    assert result["tested"] is True
    service.attach_job_to_arm(arm_cn, job_info["job_id"])
    for joint in range(1, 9):
        service.assign_joint_motor(
            arm_cn=arm_cn,
            joint_name=f"R-J{joint}",
            motor_sn=f"DM-J4310-2EC-F{joint:02X}26042710",
            esc_id=joint,
            mst_id=0x10 + joint,
            motor_type="DM-J4310-2EC",
        )
    service.record_zero_calibration(arm_cn=arm_cn, calibration_scope="right_arm", status="passed")
    service.record_demo_validation(arm_cn=arm_cn, demo_name="official_demo", validation_scope="official_demo", status="passed")

    monkeypatch.setattr(
        service,
        "_list_socketcan_interfaces",
        lambda: [{"name": "can0", "is_gs_usb": True, "bitrate": 1000000, "can_state": "ERROR-ACTIVE", "state": "UP"}],
    )

    class Completed:
        returncode = 0
        stdout = "can state ERROR-ACTIVE bitrate 1000000"
        stderr = ""

    monkeypatch.setattr(service, "_run_system_command", lambda *args, **kwargs: Completed())
    service.capture_can_health("can0", arm_cn=arm_cn)
    gate = service.factory_release_gate(arm_cn)
    assert gate["release_ready"] is True
    assert gate["release_decision"] == "PASS"
    assert gate["warning_items"]


def test_api_interface_status_endpoint(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(
        fake_service,
        "interface_status",
        lambda: {
            "interfaces": [
                {
                    "name": "can0",
                    "driver": "gs_usb",
                    "adapter_kind": "gsusb1002enc",
                    "is_gs_usb": True,
                    "bitrate": 1000000,
                    "state": "UP",
                    "mtu": "16",
                    "manufacturer": "QinHeng",
                    "product": "gsusb1002enc",
                    "serial": "ABC123",
                    "interface_label": "USB2.0-CAN",
                    "bus_info": "1-1.2",
                }
            ],
            "recommended_channel": "can0",
        },
    )
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    response = client.get("/api/device/interface-status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["recommended_channel"] == "can0"
    assert payload["interfaces"][0]["adapter_kind"] == "gsusb1002enc"
    assert payload["interfaces"][0]["bitrate"] == 1000000


def test_system_can_configure_and_toggle(monkeypatch):
    service = workstation.WorkstationService()
    interface_state = {
        "name": "can0",
        "driver": "gs_usb",
        "adapter_kind": "gsusb1002enc",
        "is_gs_usb": True,
        "bitrate": 1000000,
        "dbitrate": None,
        "fd_enabled": False,
        "state": "DOWN",
        "mtu": "16",
        "manufacturer": "QinHeng",
        "product": "gsusb1002enc",
        "serial": "ABC123",
        "interface_label": "USB2.0-CAN",
        "bus_info": "1-1.2",
    }
    commands = []

    monkeypatch.setattr(service, "_list_socketcan_interfaces", lambda: [dict(interface_state)])

    class _Result:
        def __init__(self, stdout=""):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, check=True):
        commands.append(cmd)
        if cmd[:4] == ["ip", "link", "set", "can0"] and cmd[-1] == "down":
            interface_state["state"] = "DOWN"
        elif cmd[:4] == ["ip", "link", "set", "can0"] and cmd[-1] == "up":
            interface_state["state"] = "UP"
        elif cmd[:6] == ["ip", "link", "set", "can0", "type", "can"]:
            interface_state["bitrate"] = int(cmd[7])
            if "dbitrate" in cmd:
                interface_state["dbitrate"] = int(cmd[cmd.index("dbitrate") + 1])
                interface_state["fd_enabled"] = True
            else:
                interface_state["dbitrate"] = None
                interface_state["fd_enabled"] = False
        return _Result()

    monkeypatch.setattr(service, "_run_system_command", fake_run)

    configured = service.configure_can_interface("can0", mode="canfd", bitrate=1000000, dbitrate=5000000, tool="ip_link")
    assert configured["configured"] is True
    assert configured["interface"]["dbitrate"] == 5000000
    assert configured["interface"]["fd_enabled"] is True

    up = service.can_interface_up("can0")
    assert up["ok"] is True
    assert up["interface"]["state"] == "UP"

    down = service.can_interface_down("can0")
    assert down["ok"] is True
    assert down["interface"]["state"] == "DOWN"
    assert any(cmd == ["ip", "link", "set", "can0", "down"] for cmd in commands)


def test_api_system_can_endpoints(monkeypatch):
    import web.app as web_app

    fake_service = workstation.WorkstationService()
    monkeypatch.setattr(
        fake_service,
        "system_can_interfaces",
        lambda: {
            "interfaces": [
                {
                    "name": "can0",
                    "driver": "gs_usb",
                    "adapter_kind": "gsusb1002enc",
                    "is_gs_usb": True,
                    "bitrate": 1000000,
                    "dbitrate": None,
                    "fd_enabled": False,
                    "state": "DOWN",
                    "mtu": "16",
                    "manufacturer": "QinHeng",
                    "product": "gsusb1002enc",
                    "serial": "ABC123",
                    "interface_label": "USB2.0-CAN",
                    "bus_info": "1-1.2",
                }
            ],
            "recommended_channel": "can0",
        },
    )
    monkeypatch.setattr(
        fake_service,
        "configure_can_interface",
        lambda name, mode, bitrate, dbitrate=None, fd_enabled=False, tool="ip_link": {
            "configured": True,
            "interface": {
                "name": name,
                "bitrate": bitrate,
                "dbitrate": dbitrate,
                "fd_enabled": fd_enabled,
                "state": "DOWN",
            },
            "interfaces": [],
            "recommended_channel": name,
        },
    )
    monkeypatch.setattr(fake_service, "can_interface_up", lambda name: {"ok": True, "interface": {"name": name, "state": "UP"}})
    monkeypatch.setattr(fake_service, "can_interface_down", lambda name: {"ok": True, "interface": {"name": name, "state": "DOWN"}})
    monkeypatch.setattr(web_app, "service", fake_service)
    client = web_app.app.test_client()

    response = client.get("/api/system/can-interfaces")
    assert response.status_code == 200
    assert response.get_json()["recommended_channel"] == "can0"

    configured = client.post(
        "/api/system/can-interfaces/configure",
        json={"name": "can0", "mode": "canfd", "bitrate": 1000000, "dbitrate": 5000000, "fd_enabled": True, "tool": "ip_link"},
    )
    assert configured.status_code == 200
    assert configured.get_json()["configured"] is True
    assert configured.get_json()["interface"]["fd_enabled"] is True

    up = client.post("/api/system/can-interfaces/up", json={"name": "can0"})
    assert up.status_code == 200
    assert up.get_json()["interface"]["state"] == "UP"

    down = client.post("/api/system/can-interfaces/down", json={"name": "can0"})
    assert down.status_code == 200
    assert down.get_json()["interface"]["state"] == "DOWN"


def test_cancel_allowed_before_params_saved():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    service.scan_device(session["device_session_id"], "single_commissioning")
    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J1")
    cancelled = service.cancel(job_info["job_id"])
    assert cancelled["cancelled"] is True
    assert service.get_job(job_info["job_id"])["job"]["status"] == "cancelled"


def test_cancel_blocked_after_params_saved():
    service = workstation.WorkstationService()
    session = service.connect_device("serial_bridge", {"serial_port": "/dev/fake", "baudrate": 115200})
    service.scan_device(session["device_session_id"], "single_commissioning")
    job_info = service.create_job("single_commissioning", session["device_session_id"], "openarm_v1", "J1")
    applied = service.apply_profile(job_info["job_id"], "J1", "openarm_v1")
    service.write_params(job_info["job_id"], applied["target_config"])
    service.verify_params(job_info["job_id"])
    service.save_flash(job_info["job_id"])

    with pytest.raises(ValueError):
        service.cancel(job_info["job_id"])


def test_formal_factory_report_does_not_fallback_to_reportlab_pdf(tmp_path):
    profile = {
        "profile_id": "openarm_right_arm_v1",
        "arm_side": "right_arm",
        "joints": [
            {
                "joint_name": f"R-J{index}",
                "target_esc_id": index,
                "target_mst_id": 0x10 + index,
                "motor_type": "DM-J4310-2EC",
            }
            for index in range(1, 9)
        ],
    }
    report = render_formal_factory_report(
        root_dir=tmp_path,
        reports_dir=tmp_path / "reports",
        arm={"arm_cn": "OAF26060999", "bom_profile": "openarm_right_arm_v1"},
        profile=profile,
        report_date="20260609",
        pdf_writer=lambda html_path, pdf_path: False,
    )

    report_ref = report["report_ref"]
    assert report["pdf_generated"] is False
    assert report_ref["pdf_path"] is None
    assert Path(report_ref["html_path"]).exists()
    assert Path(report_ref["json_path"]).exists()
    assert (Path(report["report_dir"]) / "pdf_error.txt").exists()


def test_passed_command_selects_latest_passed_run_for_requested_side():
    arm = {
        "command_run_history": [
            {
                "kind": "official_demo_validation",
                "command": ["openarm-can-demo", "--arm_side", "left_arm"],
                "status": "passed",
                "finished_at": "2026-09-03T09:08:14Z",
                "run_id": "latest-left",
            },
            {
                "kind": "official_demo_validation",
                "command": ["openarm-can-demo", "--arm_side", "left_arm"],
                "status": "passed",
                "finished_at": "2026-09-03T09:07:18Z",
                "run_id": "older-left",
            },
            {
                "kind": "official_demo_validation",
                "command": ["openarm-can-demo", "--arm_side", "right_arm"],
                "status": "passed",
                "finished_at": "2026-09-03T09:09:00Z",
                "run_id": "newer-other-side",
            },
        ]
    }

    selected = _passed_command(arm, "official_demo_validation", "left_arm")

    assert selected["run_id"] == "latest-left"


def test_timeout_adjustments_accept_powercycle_evidence_and_prefer_latest(tmp_path):
    evidence_dir = (
        tmp_path
        / "artifacts"
        / "factory"
        / "arm_records"
        / "OAF26080401"
        / "timeout_adjustments"
    )
    evidence_dir.mkdir(parents=True)
    old_path = evidence_dir / "20260805_right_profile_timeout_standardization.json"
    old_path.write_text(
        '{"ok":true,"arm_side":"right_arm","results":['
        '{"joint_name":"R-J1","after_save":1000,"ok":true}]}'
    )
    new_path = evidence_dir / "20260805_right_all_joints_timeout5000_powercycle_verify.json"
    new_path.write_text(
        '{"arm_side":"right_arm","summary":{"passed":1,"failed":0},"results":['
        '{"joint_name":"R-J1","timeout":5000,"passed":true}]}'
    )

    adjustments = _timeout_adjustments(tmp_path, "OAF26080401", "right_arm")

    assert adjustments["R-J1"]["TIMEOUT"] == 5000
    assert adjustments["R-J1"]["evidence"] == new_path


def test_latest_low_gain_record_is_same_side_passed_and_fully_disabled(tmp_path):
    record_dir = (
        tmp_path
        / "artifacts"
        / "factory"
        / "arm_records"
        / "OAF26080401"
        / "low_gain_enable"
    )
    record_dir.mkdir(parents=True)
    (record_dir / "left.json").write_text(
        '{"arm_side":"left_arm","ok":true,"summary":{"failed":0,"all_disabled_after_check":true}}'
    )
    right_path = record_dir / "right.json"
    right_path.write_text(
        '{"arm_side":"right_arm","ok":true,"keepalive_frames_sent":432,'
        '"summary":{"failed":0,"all_disabled_after_check":true}}'
    )

    record = _latest_low_gain_record(tmp_path, "OAF26080401", "right_arm")

    assert record["keepalive_frames_sent"] == 432
    assert record["_evidence_path"] == str(right_path)


def test_infer_motor_model_from_limit_registers():
    j8009 = workstation._infer_motor_model({"PMAX": 12.5, "VMAX": 45.0, "TMAX": 54.0, "Gr": 9.0}, "DM-J8009P-2EC")
    assert j8009["families"] == ["DM8009"] and j8009["verdict"] == "match"

    wrong_joint = workstation._infer_motor_model({"PMAX": 12.5, "VMAX": 30.0, "TMAX": 10.0}, "DM-J8009P-2EC")
    assert wrong_joint["families"] == ["DM4310"] and wrong_joint["verdict"] == "mismatch"

    j4340 = workstation._infer_motor_model({"PMAX": 12.5, "VMAX": 10.0, "TMAX": 28.0}, "DM-J4340P-2EC")
    assert j4340["verdict"] == "match"

    unreadable = workstation._infer_motor_model({"PMAX": None, "VMAX": 45.0, "TMAX": 54.0}, "DM-J8009P-2EC")
    assert unreadable["verdict"] == "unknown"


def _wizard_service(monkeypatch):
    service = workstation.WorkstationService()
    monkeypatch.setattr(service, "_wizard_can_precheck", lambda channel, bitrate: None)
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    return service, driver


def test_single_wizard_happy_path_saves_record_without_report(monkeypatch):
    service, driver = _wizard_service(monkeypatch)
    driver.registry[1]["params"][int(DM_variable.PMAX)] = 12.5

    identified = service.single_wizard_identify(arm_side="left_arm", joint="J2", product_line="openarm_2_0")
    assert identified["ok"] is True
    assert identified["joint_name"] == "L-J2"
    assert identified["configured_as"] == ["R-J1"]
    rows = {row["field"]: row for row in identified["param_rows"]}
    assert rows["ESC_ID"]["target"] == 0x0A and rows["ESC_ID"]["changes"] is True
    assert rows["TIMEOUT"]["written"] is False
    # Fake motor limits (12.5/30/10) are DM4310 while L-J2 expects DM-J8009P-2EC.
    assert identified["model_check"]["families"] == ["DM4310"]
    assert identified["model_check"]["verdict"] == "mismatch"
    assert len(service.sessions) == 1

    job_id = identified["job_id"]
    written = service.single_wizard_write(job_id)
    assert written["ok"] is True and written["status"] == "params_verified"
    saved = service.single_wizard_save(job_id)
    assert saved["ok"] is True and saved["status"] == "params_saved"

    calls_before_finish = len(driver.calls)
    finished = service.single_wizard_finish(job_id)
    assert finished["ok"] is True
    assert not {call[0] for call in driver.calls[calls_before_finish:]} & {"enable", "controlMIT", "set_zero_position", "change_motor_param", "save_motor_param"}
    record = finished["record"]
    assert record["result"] == "PASS"
    assert record["sn_register"] == 123456
    assert record["product_line"] == "openarm_2_0"
    assert record["joint_name"] == "L-J2"
    assert record["target"]["ESC_ID"] == 0x0A
    assert record["verified"] == {
        "ESC_ID": 0x0A,
        "MST_ID": 0x1A,
        "CTRL_MODE": "MIT",
        "can_br": 1000000,
        "can_br_code": 4,
        "can_mode": "CAN 2.0",
    }
    assert record["motion_performed"] is False and record["zero_saved"] is False

    job = service.jobs[job_id]
    assert not (Path(job.artifact_dir) / "report.html").exists()
    listed = service.list_single_motor_records()
    assert listed["total_records"] == 1
    assert listed["records"][0]["record_id"] == record["record_id"]
    assert listed["configured_joints"][0]["joint_name"] == "L-J2"

    again = service.single_wizard_identify(arm_side="left_arm", joint="J2")
    assert again["ok"] is True
    assert again["configured_as"] == ["L-J2"]
    assert again["needs_write"] is False
    assert again["joint_taken_by"] == []

    # A second factory-new motor reports the same SN register value; it must not be merged or treated as the same motor.
    entry = driver.registry.pop(0x0A)
    entry["params"][int(DM_variable.ESC_ID)] = 1
    entry["params"][int(DM_variable.MST_ID)] = 0
    driver.registry[1] = entry
    other_motor = service.single_wizard_identify(arm_side="left_arm", joint="J2")
    assert other_motor["configured_as"] == []
    assert other_motor["factory_default_ids"] is True
    assert other_motor["joint_taken_by"] == [{"record_id": record["record_id"], "created_at": record["created_at"]}]
    assert service.single_wizard_write(other_motor["job_id"])["ok"] is True
    assert service.single_wizard_save(other_motor["job_id"])["ok"] is True
    second = service.single_wizard_finish(other_motor["job_id"])["record"]
    assert second["sn_register"] == record["sn_register"]
    assert service.list_single_motor_records()["total_records"] == 2


def test_single_motor_records_migrate_legacy_sn_grouped_file(monkeypatch):
    service, _driver = _wizard_service(monkeypatch)
    records_dir = service._single_motor_records_dir()
    records_dir.mkdir(parents=True, exist_ok=True)
    history = [
        {"record_id": f"smr_legacy_{joint}", "record_type": "single_motor_commissioning", "created_at": f"2026-09-17T07:0{index}:00Z",
         "result": "PASS", "motor_hw_sn": "1412444213", "sn_available": True, "joint_name": joint, "product_line": "openarm_2_0",
         "motor_type": "DM-J8009P-2EC", "before": {"PMAX": 12.5, "VMAX": 45.0, "TMAX": 54.0}}
        for index, joint in enumerate(["R-J2", "R-J1"])
    ]
    workstation._atomic_json(records_dir / "1412444213.json", {"motor_hw_sn": "1412444213", "latest": history[0], "history": history})

    listed = service.list_single_motor_records()
    assert [item["joint_name"] for item in listed["records"]] == ["R-J1", "R-J2"]
    assert listed["records"][0]["sn_register"] == "1412444213"
    assert listed["records"][0]["model_check"]["verdict"] == "match"
    assert not (records_dir / "1412444213.json").exists()
    assert (records_dir / "_legacy_by_sn" / "1412444213.json").exists()
    assert service.list_single_motor_records()["total_records"] == 2


def test_single_wizard_reports_no_motor_and_multiple_motors(monkeypatch):
    service, driver = _wizard_service(monkeypatch)
    motor_entry = driver.registry.pop(1)
    empty = service.single_wizard_identify()
    assert empty["ok"] is False
    assert empty["problem"]["code"] == "no_motor_found"
    assert empty["problem"]["solutions"]

    driver.registry[1] = motor_entry
    second = copy.deepcopy(motor_entry)
    second["params"][int(DM_variable.ESC_ID)] = 3
    second["params"][int(DM_variable.MST_ID)] = 0x13
    driver.registry[3] = second
    multiple = service.single_wizard_identify()
    assert multiple["problem"]["code"] == "multiple_motors"
    assert multiple["problem"]["found_esc_ids"] == [1, 3]
    assert not service.jobs


def test_single_wizard_blocks_faulted_motor_and_retries_unanswered_readback(monkeypatch):
    service, driver = _wizard_service(monkeypatch)
    driver.registry[1]["status"] = Motor_Status.OVERCURRENT
    faulted = service.single_wizard_identify()
    assert faulted["problem"]["code"] == "motor_fault"

    driver.registry[1]["status"] = Motor_Status.DISABLED
    identified = service.single_wizard_identify()
    job_id = identified["job_id"]
    assert service.single_wizard_write(job_id)["ok"] is True
    assert service.single_wizard_save(job_id)["ok"] is True

    entry = driver.registry.pop(1)
    no_answer = service.single_wizard_finish(job_id)
    assert no_answer["problem"]["code"] == "readback_no_response"
    assert service.jobs[job_id].status == "params_saved"

    driver.registry[1] = entry
    entry["params"][int(DM_variable.MST_ID)] = 0x7F
    drifted = service.single_wizard_finish(job_id)
    assert drifted["problem"]["code"] == "readback_mismatch"
    assert drifted["problem"]["record"]["result"] == "FAIL"
    assert service.single_wizard_write(job_id)["problem"]["code"] == "job_state_invalid"


def test_single_motor_inspect_reads_without_writing(monkeypatch):
    service, driver = _wizard_service(monkeypatch)
    driver.registry[1]["params"][int(DM_variable.ESC_ID)] = 0x08
    driver.registry[1]["params"][int(DM_variable.MST_ID)] = 0x18
    driver.registry[0x08] = driver.registry.pop(1)
    writes = []
    monkeypatch.setattr(type(driver), "change_motor_param", lambda self, *a, **k: writes.append(a) or True)
    monkeypatch.setattr(type(driver), "save_motor_param", lambda self, *a, **k: writes.append("save") or True)
    monkeypatch.setattr(type(driver), "enable", lambda self, *a, **k: writes.append("enable") or True)
    monkeypatch.setattr(type(driver), "set_zero_position", lambda self, *a, **k: writes.append("zero") or True)

    payload = service.single_motor_inspect(channel="can0", bitrate=1000000)

    assert payload["ok"] is True and payload["read_only"] is True
    assert writes == []  # inspection never writes, enables or zeroes
    assert not service.jobs  # inspection creates no job
    motor = payload["motors"][0]
    assert motor["esc_id"] == 0x08 and motor["mst_id"] == 0x18
    assert motor["matched_joints"] == ["R-J8"]
    rows = {row["field"]: row for row in motor["rows"]}
    assert rows["ESC_ID"]["display"] == "0x08（8）"
    assert rows["can_br"]["display"] == "1 Mbps"  # fake driver reports the decoded bitrate
    assert service._inspect_display("can_br", 4) == "1 Mbps（代码 4）"  # real motors report the register code
    assert rows["TIMEOUT"]["display"] == "500"
    assert service._inspect_display("TIMEOUT", 0) == "0（未启用）"
    assert rows["CTRL_MODE"]["display"] == "MIT（1）"
    assert {row["group"] for row in motor["rows"]} == {"identity", "motor", "protection", "version"}
    assert motor["status"]["status"] == "DISABLED"


def test_single_motor_inspect_reports_problems_and_lists_every_motor(monkeypatch):
    service, driver = _wizard_service(monkeypatch)
    entry = driver.registry.pop(1)
    empty = service.single_motor_inspect()
    assert empty["ok"] is False
    assert empty["problem"]["code"] == "no_motor_found"
    assert empty["problem"]["solutions"]

    driver.registry[1] = entry
    second = copy.deepcopy(entry)
    second["params"][int(DM_variable.ESC_ID)] = 9
    second["params"][int(DM_variable.MST_ID)] = 0x19
    driver.registry[9] = second
    both = service.single_motor_inspect()
    # Unlike commissioning, viewing parameters stays useful with several motors on the bus.
    assert both["ok"] is True
    assert sorted(item["esc_id"] for item in both["motors"]) == [1, 9]
    assert both["motors"][1]["matched_joints"] == ["L-J1"]


def _link_service(monkeypatch, interfaces=None):
    service = workstation.WorkstationService()
    snapshot = interfaces if interfaces is not None else [
        {"name": "can0", "driver": "gs_usb", "adapter_kind": "gs_usb", "is_gs_usb": True, "bitrate": 1000000,
         "dbitrate": None, "fd_enabled": False, "can_state": "ERROR-ACTIVE", "state": "UP"}
    ]
    monkeypatch.setattr(service, "_list_socketcan_interfaces", lambda: [dict(item) for item in snapshot])
    return service


def test_link_wizard_detect_reports_missing_adapter_and_interface_health(monkeypatch):
    empty = _link_service(monkeypatch, interfaces=[])
    problem = empty.link_wizard_detect()
    assert problem["ok"] is False
    assert problem["problem"]["code"] == "adapter_missing"
    assert problem["problem"]["solutions"]

    service = _link_service(monkeypatch)
    detected = service.link_wizard_detect()
    assert detected["ok"] is True
    iface = detected["interfaces"][0]
    assert iface["healthy"] is True and iface["health_text"] == "正常"
    assert iface["bitrate_text"] == "1 Mbps" and iface["mode_text"] == "CAN 2.0"

    down = _link_service(monkeypatch, interfaces=[
        {"name": "can1", "driver": "gs_usb", "is_gs_usb": True, "bitrate": None, "fd_enabled": False,
         "can_state": "STOPPED", "state": "DOWN"}
    ])
    stopped = down.link_wizard_detect()["interfaces"][0]
    assert stopped["healthy"] is False and stopped["health_text"] == "未启动"

    # Any adapter Linux exposes as SocketCAN is usable, not only gs_usb ones.
    peak = _link_service(monkeypatch, interfaces=[
        {"name": "can0", "driver": "peak_usb", "is_gs_usb": False, "bitrate": 1000000, "fd_enabled": True,
         "dbitrate": 5000000, "can_state": "ERROR-ACTIVE", "state": "UP"}
    ])
    other = peak.link_wizard_detect()["interfaces"][0]
    assert other["healthy"] is True and other["health_text"] == "正常"
    assert other["mode_text"] == "CAN FD"


def test_link_wizard_prepare_and_connect_flow(monkeypatch):
    service = _link_service(monkeypatch)
    commands = []
    monkeypatch.setattr(service, "_run_system_command", lambda cmd, **kwargs: commands.append(cmd))

    prepared = service.link_wizard_prepare(channel="can0", mode="can20", bitrate=1000000)
    assert prepared["ok"] is True
    assert prepared["interface"]["healthy"] is True
    assert ["ip", "link", "set", "can0", "up"] in commands

    monkeypatch.setattr(service, "_wizard_can_precheck", lambda channel, bitrate: None)
    connected = service.link_wizard_connect(channel="can0", bitrate=1000000)
    assert connected["ok"] is True
    assert connected["capabilities"]["read_params"] is True
    session_id = connected["device_session_id"]
    # Connecting twice reuses the open session instead of stacking CAN sockets.
    assert service.link_wizard_connect(channel="can0")["device_session_id"] == session_id

    closed = service.link_wizard_disconnect(channel="can0")
    assert closed["closed_sessions"] == [session_id]


def test_link_wizard_prepare_failure_and_bus_check(monkeypatch):
    service = _link_service(monkeypatch)

    def refuse(cmd, **kwargs):
        raise RuntimeError("RTNETLINK answers: Operation not permitted")

    monkeypatch.setattr(service, "_run_system_command", refuse)
    failed = service.link_wizard_prepare(channel="can0")
    assert failed["problem"]["code"] == "interface_prepare_failed"
    assert "Operation not permitted" in failed["problem"]["detail"]

    monkeypatch.setattr(service, "_wizard_can_precheck", lambda channel, bitrate: None)
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    entry = driver.registry.pop(1)
    empty_bus = service.link_wizard_bus_check(channel="can0")
    assert empty_bus["problem"]["code"] == "bus_no_motor"

    entry["params"][int(DM_variable.ESC_ID)] = 0x08
    entry["params"][int(DM_variable.MST_ID)] = 0x18
    driver.registry[0x08] = entry
    checked = service.link_wizard_bus_check(channel="can0")
    assert checked["ok"] is True and checked["read_only"] is True
    assert checked["motors"][0]["matched_joints"] == ["R-J8"]
    assert checked["faulted_esc_ids"] == []


def _interface_control_stub(service, monkeypatch, channel="can0"):
    """Let interface up/down/configure run without touching the real machine."""
    interface = {
        "name": channel,
        "driver": "gs_usb",
        "adapter_kind": "gs_usb",
        "is_gs_usb": True,
        "bitrate": 1000000,
        "dbitrate": None,
        "fd_enabled": False,
        "can_state": "ERROR-ACTIVE",
        "berr_tx": 0,
        "berr_rx": 0,
        "state": "UP",
        "mtu": "16",
    }
    monkeypatch.setattr(service, "_list_socketcan_interfaces", lambda: [dict(interface)])
    monkeypatch.setattr(service, "_run_system_command", lambda cmd, **kwargs: None)
    return interface


def test_interface_restart_closes_the_cached_socketcan_session(monkeypatch):
    # A socket opened before `ip link down` keeps answering "nothing on the bus"
    # afterwards, which reads exactly like a dead motor.
    service, driver = _wizard_service(monkeypatch)
    _interface_control_stub(service, monkeypatch)
    stale = next(iter(service.sessions.values()))
    assert stale.connection_state != "disconnected"

    service.can_interface_down("can0")
    assert stale.connection_state == "disconnected"
    assert driver.connected is False

    fresh = service._wizard_session("can0", 1000000)
    assert fresh.session_id != stale.session_id
    assert fresh.connection["ifindex"] == service._interface_ifindex("can0")


def test_configure_can_interface_closes_the_cached_socketcan_session(monkeypatch):
    service, _driver = _wizard_service(monkeypatch)
    _interface_control_stub(service, monkeypatch)
    stale = next(iter(service.sessions.values()))

    service.configure_can_interface("can0", mode="can20", bitrate=1000000, tool="ip_link")
    assert stale.connection_state == "disconnected"


def test_wizard_precheck_restart_closes_the_cached_socketcan_session(monkeypatch):
    # The precheck restarts the link with raw ip commands, bypassing the methods
    # above, so it has to close the sockets itself. No precheck stub here.
    service = workstation.WorkstationService()
    interface = _interface_control_stub(service, monkeypatch)
    service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    stale = next(iter(service.sessions.values()))

    interface["state"] = "DOWN"  # forces the precheck to restart the link
    assert service._wizard_can_precheck("can0", 1000000) is None
    assert stale.connection_state == "disconnected"


def test_replugged_adapter_is_not_reused(monkeypatch):
    service, _driver = _wizard_service(monkeypatch)
    stale = next(iter(service.sessions.values()))
    stale.connection["ifindex"] = 5
    monkeypatch.setattr(service, "_interface_ifindex", lambda name: 9)

    fresh = service._wizard_session("can0", 1000000)
    assert fresh.session_id != stale.session_id
    assert stale.connection_state == "disconnected"


def test_wizard_reconnects_once_before_blaming_the_motor(monkeypatch):
    service, _driver = _wizard_service(monkeypatch)
    original = service._inventory_scan
    seen = []

    def deaf_first(session, scan_ids):
        seen.append(session.session_id)
        if len(seen) == 1:
            return [], []
        return original(session, scan_ids)

    monkeypatch.setattr(service, "_inventory_scan", deaf_first)

    identified = service.single_wizard_identify()
    assert identified["ok"] is True
    # Scanned twice, on two different sessions: the deaf socket was rebuilt.
    assert len(seen) == 2 and seen[0] != seen[1]


def test_wizard_does_not_rescan_when_it_just_opened_the_session(monkeypatch):
    # Nothing to rule out on a socket we opened ourselves, so no second full scan.
    service = workstation.WorkstationService()
    monkeypatch.setattr(service, "_wizard_can_precheck", lambda channel, bitrate: None)
    seen = []

    def empty(session, scan_ids):
        seen.append(session.session_id)
        return [], []

    monkeypatch.setattr(service, "_inventory_scan", empty)

    problem = service.single_wizard_identify()
    assert problem["problem"]["code"] == "no_motor_found"
    assert len(seen) == 1


def test_default_scan_finds_a_left_arm_motor():
    # Left arm ESC 0x09-0x10 used to sit outside the advanced-path scan range, so a
    # correctly configured L-J8 reported detected=0 unless the operator typed its ID.
    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    driver = service.sessions[session["device_session_id"]].driver
    entry = driver.registry.pop(1)
    entry["params"][int(DM_variable.ESC_ID)] = 0x10
    entry["params"][int(DM_variable.MST_ID)] = 0x20
    driver.registry[0x10] = entry

    scan = service.scan_device(session["device_session_id"], "single_comm_check")
    assert scan["summary"]["detected"] == 1
    assert scan["candidates"][0]["detected_esc_id"] == 0x10


def test_default_scan_range_covers_every_openarm_id():
    assert workstation.DEFAULT_SCAN_IDS == list(range(0x01, 0x21))
    for esc_id in (*range(0x01, 0x09), *range(0x09, 0x11)):
        assert esc_id in workstation.DEFAULT_SCAN_IDS


def test_every_profile_agrees_with_the_commissioning_timeout_policy():
    # The generic profile is the API and CLI default. It used to carry a superseded
    # TIMEOUT=1000 on J1-J4 while the derived arm profiles and the policy said 5000,
    # so a scan run with the default profile would have reported four false mismatches.
    service = workstation.WorkstationService()
    policy = service.config()["commissioning_policy"]["whole_arm_timeout_policy"]
    expected = {value for arm in policy.values() for value in arm.values()}
    assert expected == {workstation.WHOLE_ARM_TARGET_TIMEOUT}

    for profile_id in ("openarm_v1", "openarm_right_arm_v1", "openarm_left_arm_v1"):
        profile = service.profile_manager.get_profile(profile_id)
        timeouts = {int(joint["target_timeout"]) for joint in profile["joints"]}
        assert timeouts == {workstation.WHOLE_ARM_TARGET_TIMEOUT}, f"{profile_id}: {sorted(timeouts)}"


def test_demo_parse_blocks_on_a_gripper_progress_abort():
    # The demo stops a gripper phase when the gripper is not following, most likely
    # because the open direction is wrong for this arm. The report has to say so
    # rather than only showing a short travel.
    stdout = (
        "arm_side: right_arm\n"
        "OPEN gripper: target=-1.047200 start=0.000000\n"
        "GRIPPER_ABORT: OPEN covered -0.0% of the requested -1.047200 rad by the midpoint "
        "(minimum 15%); stopping to avoid holding against a stop.\n"
        "OPEN gripper result: start=0.000000 end=0.000000 delta=0.000000 min=0.000000 "
        "max=0.000000 travel=0.000000 aborted=True\n"
        "Demo completed successfully; motors disabled.\n"
    )
    summary = workstation._parse_official_demo_stdout(stdout)
    assert summary["passed"] is False
    assert "gripper_progress_aborted" in summary["blocking_items"]
    assert summary["gripper_abort_messages"] and "midpoint" in summary["gripper_abort_messages"][0]


def test_a_normal_demo_has_no_gripper_abort():
    # Taken from a real Follower run: the phase-internal travel really is 0.000000
    # because `get_motors()` handed the script a frozen copy; the endpoint values
    # carry the truth. This must keep parsing as it always did.
    stdout = (
        "arm_side: right_arm\n"
        "OPEN gripper: target=-1.047200 start=-0.000191\n"
        "OPEN gripper result: start=-0.000191 end=-0.000191 delta=0.000000 min=-0.000191 "
        "max=-0.000191 travel=0.000000\n"
        "CLOSE gripper: target=0.000000 start=-1.008812\n"
        "CLOSE gripper result: start=-1.008812 end=-1.008812 delta=0.000000 min=-1.008812 "
        "max=-1.008812 travel=0.000000\n"
        "Gripper Motor 8 recv=24 position=-0.041772 velocity=-0.007326 torque=-0.002442 tmos=30 trotor=29\n"
        "Demo completed successfully; motors disabled.\n"
    )
    summary = workstation._parse_official_demo_stdout(stdout)
    assert summary["gripper_abort_messages"] == []
    assert "gripper_progress_aborted" not in summary["blocking_items"]
    assert summary["gripper_travel_rad"] == pytest.approx(abs(-0.041772 - -1.008812), abs=1e-6)


def test_single_motor_record_reads_its_can_mode_from_the_product(monkeypatch):
    # Both products commission over classic CAN today, so the recorded label is
    # unchanged; it is now read from the registry rather than asserted in the code.
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", shared_socketcan_factory())
    service = workstation.WorkstationService()
    assert service._can_mode_label("openarm_1_0", "commissioning") == "CAN 2.0"
    assert service._can_mode_label("openarm_2_0", "commissioning") == "CAN 2.0"
    # The assembled 2.0 arm is meant to run FD; the label follows the registry.
    assert service._can_mode_label("openarm_2_0", "operation") == "CAN FD"
    assert service._can_mode_label("openarm_1_0", "operation") == "CAN 2.0"
    # Records written before the registry existed state no product.
    assert service._can_mode_label(None, "commissioning") == "CAN 2.0"
    assert service._can_mode_label("openarm_9_9", "commissioning") == "CAN 2.0"
