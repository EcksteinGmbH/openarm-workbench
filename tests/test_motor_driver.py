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
