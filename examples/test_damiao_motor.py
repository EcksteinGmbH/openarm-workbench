"""
Damiao电机测试示例
演示如何使用damiao电机驱动器
"""

import time
from src.damiao_motor_driver import (
    DamiaoMotorDriver, Motor, 
    DM_Motor_Type, Control_Type, Motor_Status
)


def demo_basic_connection():
    """测试基本连接"""
    print("=" * 50)
    print("测试1: 基本连接测试")
    print("=" * 50)
    
    # 创建驱动器实例（根据实际串口修改）
    driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
    
    # 连接串口
    if not driver.connect():
        print("连接失败！")
        return False
    
    print("连接成功！")
    driver.disconnect()
    return True


def demo_motor_enable_disable():
    """测试电机使能和失能"""
    print("\n" + "=" * 50)
    print("测试2: 电机使能/失能测试")
    print("=" * 50)
    
    driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
    
    if not driver.connect():
        return False
    
    # 创建电机实例（根据实际电机型号修改）
    motor = Motor(MotorType=DM_Motor_Type.DM4310, SlaveID=1, MasterID=0)
    driver.addMotor(motor)
    
    print(f"电机ID: {motor.SlaveID}")
    print(f"电机类型: DM4310")
    
    # 使能电机
    print("\n使能电机...")
    if driver.enable(motor):
        print("使能成功")
    else:
        print("使能失败")
    
    # 等待2秒
    time.sleep(2)
    
    # 失能电机
    print("\n失能电机...")
    if driver.disable(motor):
        print("失能成功")
    else:
        print("失能失败")
    
    driver.disconnect()
    return True


def demo_velocity_control():
    """测试速度控制"""
    print("\n" + "=" * 50)
    print("测试3: 速度控制测试")
    print("=" * 50)
    
    driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
    
    if not driver.connect():
        return False
    
    motor = Motor(MotorType=DM_Motor_Type.DM4310, SlaveID=1, MasterID=0)
    driver.addMotor(motor)
    
    # 使能电机
    print("使能电机...")
    driver.enable(motor)
    time.sleep(1)
    
    # 切换到速度控制模式
    print("\n切换到速度控制模式...")
    driver.switchControlMode(motor, Control_Type.VEL)
    time.sleep(0.5)
    
    # 发送速度指令（正转）
    print("\n正转 5 rad/s...")
    for i in range(10):
        driver.control_Vel(motor, 5.0)
        driver.recv()
        print(f"位置: {motor.getPosition():.3f} rad, "
              f"速度: {motor.getVelocity():.3f} rad/s, "
              f"扭矩: {motor.getTorque():.3f} Nm, "
              f"MOS温度: {motor.getT_MOS():.1f}°C, "
              f"线圈温度: {motor.getT_Rotor():.1f}°C, "
              f"状态: {motor.getMotorStatus()}")
        time.sleep(0.1)
    
    # 停止
    print("\n停止...")
    for i in range(10):
        driver.control_Vel(motor, 0.0)
        driver.recv()
        print(f"位置: {motor.getPosition():.3f} rad, "
              f"速度: {motor.getVelocity():.3f} rad/s")
        time.sleep(0.1)
    
    # 失能电机
    print("\n失能电机...")
    driver.disable(motor)
    
    driver.disconnect()
    return True


def demo_position_velocity_control():
    """测试位置+速度控制"""
    print("\n" + "=" * 50)
    print("测试4: 位置+速度控制测试")
    print("=" * 50)
    
    driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
    
    if not driver.connect():
        return False
    
    motor = Motor(MotorType=DM_Motor_Type.DM4310, SlaveID=1, MasterID=0)
    driver.addMotor(motor)
    
    # 使能电机
    print("使能电机...")
    driver.enable(motor)
    time.sleep(1)
    
    # 切换到位置+速度控制模式
    print("\n切换到位置+速度控制模式...")
    driver.switchControlMode(motor, Control_Type.POS_VEL)
    time.sleep(0.5)
    
    # 设置零位
    print("\n设置零位...")
    driver.set_zero_position(motor)
    time.sleep(1)
    
    # 移动到不同位置
    positions = [1.0, 2.0, 3.0, 2.0, 1.0, 0.0]
    for pos in positions:
        print(f"\n移动到位置: {pos} rad")
        driver.control_Pos_Vel(motor, pos, 1.0)
        
        # 等待运动完成
        for i in range(20):
            driver.recv()
            if abs(motor.getPosition() - pos) < 0.05:
                print(f"到达位置: {motor.getPosition():.3f} rad")
                break
            time.sleep(0.1)
        
        if motor.hasError():
            print(f"错误: 电机状态异常 - {motor.getMotorStatus()}")
            break
    
    # 失能电机
    print("\n失能电机...")
    driver.disable(motor)
    
    driver.disconnect()
    return True


def demo_mit_control():
    """测试MIT控制模式"""
    print("\n" + "=" * 50)
    print("测试5: MIT控制模式测试")
    print("=" * 50)
    
    driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
    
    if not driver.connect():
        return False
    
    motor = Motor(MotorType=DM_Motor_Type.DM4310, SlaveID=1, MasterID=0)
    driver.addMotor(motor)
    
    # 使能电机
    print("使能电机...")
    driver.enable(motor)
    time.sleep(1)
    
    # 切换到MIT模式
    print("\n切换到MIT控制模式...")
    driver.switchControlMode(motor, Control_Type.MIT)
    time.sleep(0.5)
    
    # 设置零位
    print("\n设置零位...")
    driver.set_zero_position(motor)
    time.sleep(1)
    
    # MIT控制：位置控制（kp=50, kd=0.5）
    print("\nMIT位置控制...")
    target_positions = [1.0, 2.0, 3.0, 2.0, 1.0, 0.0]
    for pos in target_positions:
        print(f"目标位置: {pos} rad")
        for i in range(10):
            driver.controlMIT(motor, kp=50, kd=0.5, q=pos, dq=0, tau=0)
            driver.recv()
            print(f"  实际位置: {motor.getPosition():.3f} rad, "
                  f"速度: {motor.getVelocity():.3f} rad/s, "
                  f"扭矩: {motor.getTorque():.3f} Nm")
            time.sleep(0.1)
        time.sleep(0.5)
    
    # 失能电机
    print("\n失能电机...")
    driver.disable(motor)
    
    driver.disconnect()
    return True


def demo_status_monitoring():
    """测试状态监控"""
    print("\n" + "=" * 50)
    print("测试6: 状态监控测试")
    print("=" * 50)
    
    driver = DamiaoMotorDriver(serial_port='/dev/ttyUSB0', baudrate=115200)
    
    if not driver.connect():
        return False
    
    motor = Motor(MotorType=DM_Motor_Type.DM4310, SlaveID=1, MasterID=0)
    driver.addMotor(motor)
    
    # 使能电机
    print("使能电机...")
    driver.enable(motor)
    time.sleep(1)
    
    # 监控状态
    print("\n监控电机状态（10秒）...")
    start_time = time.time()
    while time.time() - start_time < 10:
        driver.recv()
        
        print(f"位置: {motor.getPosition():.3f} rad | "
              f"速度: {motor.getVelocity():.3f} rad/s | "
              f"扭矩: {motor.getTorque():.3f} Nm | "
              f"MOS温度: {motor.getT_MOS():.1f}°C | "
              f"线圈温度: {motor.getT_Rotor():.1f}°C | "
              f"状态: {motor.getMotorStatus()}")
        
        if motor.hasError():
            print(f"警告: 电机处于错误状态！")
            break
        
        time.sleep(1)
    
    # 失能电机
    print("\n失能电机...")
    driver.disable(motor)
    
    driver.disconnect()
    return True


def main():
    """主函数"""
    print("Damiao电机测试程序")
    print("警告: 使用前请确保电机已正确连接！\n")
    
    # 测试选择
    tests = {
        '1': ("基本连接测试", demo_basic_connection),
        '2': ("使能/失能测试", demo_motor_enable_disable),
        '3': ("速度控制测试", demo_velocity_control),
        '4': ("位置+速度控制测试", demo_position_velocity_control),
        '5': ("MIT控制测试", demo_mit_control),
        '6': ("状态监控测试", demo_status_monitoring),
    }
    
    print("请选择测试:")
    for key, (name, _) in tests.items():
        print(f"  {key}. {name}")
    print("  0. 退出")
    
    choice = input("\n请输入选项: ")
    
    if choice == '0':
        print("退出程序")
        return
    
    if choice in tests:
        name, test_func = tests[choice]
        print(f"\n开始: {name}")
        try:
            result = test_func()
            if result:
                print(f"\n✓ {name} 完成")
            else:
                print(f"\n✗ {name} 失败")
        except Exception as e:
            print(f"\n✗ {name} 出错: {e}")
    else:
        print("无效选项")


if __name__ == '__main__':
    main()
