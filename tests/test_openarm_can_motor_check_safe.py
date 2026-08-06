from tools.openarm_can_motor_check_safe import motor_type_for_can_id
from src.damiao_motor_driver import DM_Motor_Type


def test_motor_type_for_right_and_left_arm_can_ids():
    expected = [
        DM_Motor_Type.DM8009,
        DM_Motor_Type.DM8009,
        DM_Motor_Type.DM4340,
        DM_Motor_Type.DM4340,
        DM_Motor_Type.DM4310,
        DM_Motor_Type.DM4310,
        DM_Motor_Type.DM4310,
        DM_Motor_Type.DM4310,
    ]

    assert [motor_type_for_can_id(can_id) for can_id in range(0x01, 0x09)] == expected
    assert [motor_type_for_can_id(can_id) for can_id in range(0x09, 0x11)] == expected
