export const ARM_MATRIX_FIELDS = ['ESC_ID', 'MST_ID', 'CTRL_MODE', 'TIMEOUT', 'can_br', 'Gr', 'KT_Value', 'PMAX', 'VMAX', 'TMAX'];

export function isSingleCommissioning(jobType) {
    return jobType === 'single_commissioning' || jobType === 'single_id_config';
}

export function isSingleParamConfig(jobType) {
    return jobType === 'single_param_config';
}

export function isSingleParameterTask(jobType) {
    return isSingleCommissioning(jobType) || isSingleParamConfig(jobType);
}

export function isArmVerification(jobType) {
    return jobType === 'arm_verification' || jobType === 'arm_comm_scan' || jobType === 'arm_acceptance';
}

export function isArmAcceptance(jobType) {
    return jobType === 'arm_acceptance';
}

export function isSingleCommCheck(jobType) {
    return jobType === 'single_comm_check';
}
