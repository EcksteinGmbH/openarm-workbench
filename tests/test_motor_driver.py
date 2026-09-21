"""
Damiao电机驱动模块测试
"""

import pytest
from src.motor_driver import DamiaoMotor


class TestDamiaoMotor:
    
    def test_motor_initialization(self):
        """测试电机初始化"""
        motor = DamiaoMotor(can_id=1, channel='can0')
        assert motor.can_id == 1
        assert motor.channel == 'can0'
        assert motor.bitrate == 1000000
        assert motor.bus is None
    
    def test_connect_without_hardware(self):
        """测试连接（无硬件时）"""
        motor = DamiaoMotor(can_id=1)
        result = motor.connect()
        # 无硬件时会返回False，这是预期的
        assert isinstance(result, bool)
    
    def test_disconnect(self):
        """测试断开连接"""
        motor = DamiaoMotor(can_id=1)
        motor.disconnect()
        assert motor.bus is None
    
    def test_send_command_without_connection(self):
        """测试未连接时发送命令"""
        motor = DamiaoMotor(can_id=1)
        result = motor.send_command([0x01, 0x02, 0x03])
        assert result is False
    
    def test_receive_response_without_connection(self):
        """测试未连接时接收响应"""
        motor = DamiaoMotor(can_id=1)
        msg = motor.receive_response()
        assert msg is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


class TestStatusFrameIdDecoding:
    """Damiao packs ERR/status in D0[7:4] and ESC_ID in D0[3:0].

    Plan A puts L-J8 at ESC 0x10, which does not fit in that 4-bit field. Reading the
    high nibble as status there reports a DISABLED motor as ENABLED - the single most
    dangerous misread the workstation can make, since "already enabled" changes what an
    operator does next. All 16 motors for 2.0 are commissioned, L-J8 among them, and
    none of this could be re-checked on hardware, so it is pinned down here.
    """

    @staticmethod
    def _driver_with(slave_id: int, master_id: int):
        from src.damiao_motor_driver import DamiaoSocketCANDriver, DM_Motor_Type, Motor

        driver = DamiaoSocketCANDriver("can0")
        motor = Motor(DM_Motor_Type.DM4310, slave_id, master_id)
        driver.addMotor(motor)
        return driver, motor

    @staticmethod
    def _frame(d0: int):
        # D0, then position/velocity/torque/temperatures - the values do not matter here.
        return [d0, 0x80, 0x00, 0x80, 0x00, 0x00, 30, 35]

    def test_left_arm_j8_at_esc_0x10_is_not_misread_as_enabled(self):
        from src.damiao_motor_driver import Motor_Status

        driver, motor = self._driver_with(0x10, 0x20)
        driver._process_status_payload(self._frame(0x10), can_id=0x20)

        assert motor.motor_id == 0x10, "the full byte is the ESC_ID, not id 0x00"
        assert motor.motor_status == Motor_Status.DISABLED, "high nibble 0x1 is not a status here"

    def test_a_normal_joint_still_decodes_status_from_the_high_nibble(self):
        from src.damiao_motor_driver import Motor_Status

        driver, motor = self._driver_with(0x08, 0x18)
        driver._process_status_payload(self._frame(0x18), can_id=0x18)

        assert motor.motor_id == 0x08
        assert motor.motor_status == Motor_Status.ENABLED

    def test_the_special_case_only_applies_when_the_byte_matches_that_motor(self):
        from src.damiao_motor_driver import Motor_Status

        # 0x18 on the L-J8 motor is a normal frame: id 0x08, status ENABLED. The
        # special case must not swallow every frame a >0x0F motor receives.
        driver, motor = self._driver_with(0x10, 0x20)
        driver._process_status_payload(self._frame(0x18), can_id=0x20)

        assert motor.motor_id == 0x08
        assert motor.motor_status == Motor_Status.ENABLED

    def test_the_raw_frame_is_kept_as_evidence(self):
        driver, motor = self._driver_with(0x10, 0x20)
        driver._process_status_payload(self._frame(0x10), can_id=0x20)

        # The release gate accepts a raw status frame in place of a candump trace.
        assert motor.last_status_frame["data_hex"].startswith("10")
        assert motor.last_status_frame["can_id"] == 0x20


class TestLimitParamsMatchOfficial:
    """(PMAX, VMAX, TMAX) scale every packed and unpacked MIT value.

    A wrong entry does not fail loudly; it silently mis-scales that motor's readings,
    and those readings go into a factory report. DM4340 carried VMAX 8 against the
    official 10, so velocity for J3 and J4 was recorded 20% low on every arm.
    """

    # openarm_can 1.4.0, include/openarm/damiao_motor/dm_motor_constants.hpp
    OFFICIAL = {
        "DM4310": (12.5, 30, 10),
        "DM4310_48V": (12.5, 50, 10),
        "DM4340": (12.5, 10, 28),
        "DM4340_48V": (12.5, 10, 28),
        "DM6006": (12.5, 45, 20),
        "DM8006": (12.5, 45, 40),
        "DM8009": (12.5, 45, 54),
        "DM10010L": (12.5, 25, 200),
        "DM10010": (12.5, 20, 200),
        "DMH3510": (12.5, 280, 1),
        "DMH6215": (12.5, 45, 10),
        "DMG6220": (12.5, 45, 10),
    }

    def test_every_motor_type_matches_the_official_table(self):
        from src.damiao_motor_driver import LIMIT_PARAM, DM_Motor_Type

        for motor_type in DM_Motor_Type:
            expected = self.OFFICIAL[motor_type.name]
            actual = tuple(float(value) for value in LIMIT_PARAM[int(motor_type)])
            assert actual == tuple(float(v) for v in expected), motor_type.name

    def test_the_table_is_indexed_by_our_own_enum_not_the_official_one(self):
        # Official numbers DM3507 = 0 and DM4310 = 1; ours has no DM3507 and starts at
        # DM4310 = 0. The indices are not interchangeable, and nothing may pass one
        # across - the official library is addressed by name (oa.MotorType.DM8009).
        from src.damiao_motor_driver import LIMIT_PARAM, DM_Motor_Type

        assert int(DM_Motor_Type.DM4310) == 0
        assert len(LIMIT_PARAM) == len(DM_Motor_Type)

    def test_the_table_agrees_with_what_the_real_motors_reported(self):
        """The 16 motors commissioned on 2026-09-17 read their own limits back."""
        import json
        from pathlib import Path

        from src.damiao_motor_driver import LIMIT_PARAM, DM_Motor_Type

        by_model = {
            "DM-J4310-2EC": DM_Motor_Type.DM4310,
            "DM-J4340-2EC": DM_Motor_Type.DM4340,
            "DM-J4340P-2EC": DM_Motor_Type.DM4340,
            "DM-J8009P-2EC": DM_Motor_Type.DM8009,
        }
        records = Path(__file__).parent / "golden" / "fixture" / "single_motor_records"
        checked = 0
        for path in records.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            before = record.get("before") or {}
            motor_type = by_model.get(record["motor_type"])
            if motor_type is None or before.get("VMAX") is None:
                continue
            pmax, vmax, tmax = LIMIT_PARAM[int(motor_type)]
            assert float(before["PMAX"]) == float(pmax), record["joint_name"]
            assert float(before["VMAX"]) == float(vmax), record["joint_name"]
            assert float(before["TMAX"]) == float(tmax), record["joint_name"]
            checked += 1
        assert checked == 16, f"expected all 16 motors checked, got {checked}"
