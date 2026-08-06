from __future__ import annotations

import json

import pytest

import src.arm_can_scan_cli as cli
import src.workstation as workstation
from src.damiao_motor_driver import DM_variable, Motor_Status


class FakeFullArmSocketCANDriver:
    def __init__(self, *args, **kwargs):
        self.connected = False
        self.registry = {}
        self.motors = {}
        for esc_id in range(1, 9):
            self.registry[esc_id] = {
                "params": {
                    int(DM_variable.ESC_ID): esc_id,
                    int(DM_variable.MST_ID): 0x10 + esc_id,
                    int(DM_variable.CTRL_MODE): 1,
                    int(DM_variable.TIMEOUT): 5000 if esc_id >= 5 else 1000,
                    int(DM_variable.can_br): 1000000,
                    int(DM_variable.sw_ver): 100,
                    int(DM_variable.sub_ver): 1,
                    int(DM_variable.SN): 200000 + esc_id,
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


@pytest.fixture(autouse=True)
def fake_socketcan_driver(monkeypatch):
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", FakeFullArmSocketCANDriver)


def test_cli_generates_json_and_csv_reports(tmp_path):
    exit_code = cli.main(
        [
            "--channel",
            "can0",
            "--bitrate",
            "1000000",
            "--profile",
            "openarm_v1",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    output_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(output_dirs) == 1
    output_dir = output_dirs[0]

    summary = json.loads((output_dir / "scan_summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is True
    assert summary["scan_summary"]["passed"] is True
    assert (output_dir / "joint_results.csv").exists()
    assert (output_dir / "report.html").exists()
