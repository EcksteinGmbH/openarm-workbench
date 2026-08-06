export function factorySerialPayloadBase() {
    return {
        role: document.getElementById('factorySerialRole').value,
        date_code: document.getElementById('factorySerialDate').value.trim() || null,
        sequence: Number(document.getElementById('factorySerialSequence').value || 1)
    };
}

export function factoryEvidenceInterface() {
    return document.getElementById('factoryEvidenceInterface').value.trim()
        || document.getElementById('socketcanChannel').value.trim()
        || 'can0';
}

export function currentFactoryArmCn() {
    const armCn = document.getElementById('factoryArmCn').value.trim();
    if (!armCn) {
        throw new Error('请先填写并保存机械臂 CN');
    }
    return armCn;
}

export function optionalFactoryArmCn() {
    return document.getElementById('factoryArmCn')?.value.trim() || null;
}

export function officialZeroConfirmations() {
    return {
        workspace_clear: true,
        estop_ready: true,
        zero_pose_confirmed: true,
        power_stable: true,
        one_arm_only: true,
    };
}

export function nativeZeroConfirmations() {
    return {
        pose_aligned: true,
        gripper_closed: true,
        comm_scan_passed: true,
        workspace_clear: true,
        estop_ready: true,
        no_motion_ack: true,
        one_arm_only: true,
    };
}

export function officialDemoConfirmations() {
    return {
        workspace_clear: true,
        estop_ready: true,
        zero_calibrated: true,
        comm_check_passed: true,
        low_speed: true,
    };
}

export function officialMotorCheckConfirmations() {
    return {
        motor_powered: true,
        can_interface_up: true,
        id_pair_verified: true,
        no_motion_expected: true,
    };
}

export function officialBaudrateConfirmations() {
    return {
        single_motor_only: true,
        can20_mode: true,
        write_limit_ack: true,
        power_cycle_plan: true,
    };
}

export function officialMotorCheckPayload(execute) {
    return {
        canid: Number(document.getElementById('officialCheckCanid').value),
        recvid: Number(document.getElementById('officialCheckRecvid').value),
        socketcan: document.getElementById('officialCheckSocketcan').value.trim() || 'can0',
        fd: document.getElementById('officialCheckFd').checked,
        execute,
        confirmations: execute ? officialMotorCheckConfirmations() : {},
        arm_cn: optionalFactoryArmCn(),
    };
}

export function officialBaudratePayload(execute) {
    return {
        canid: Number(document.getElementById('officialBaudrateCanid').value),
        baudrate: Number(document.getElementById('officialBaudrateValue').value),
        socketcan: document.getElementById('officialBaudrateSocketcan').value.trim() || 'can0',
        flash: document.getElementById('officialBaudrateFlash').checked,
        execute,
        confirmations: execute ? officialBaudrateConfirmations() : {},
        arm_cn: optionalFactoryArmCn(),
    };
}
