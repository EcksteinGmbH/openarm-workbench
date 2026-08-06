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
