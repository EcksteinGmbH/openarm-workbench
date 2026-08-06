import { state } from './store.js';

export function initSocket({
    addLog,
    refreshCurrentJob,
    renderInterfaceStatus,
    updateCanHealthStatus,
    updateLiveStatus,
}) {
    state.socket = window.io();
    state.socket.on('job_state', payload => {
        if (payload.job_id && state.currentJobId && payload.job_id === state.currentJobId) {
            addLog(payload.message, payload.status === 'failed' ? 'error' : 'info', payload.step);
            refreshCurrentJob();
        } else if (!payload.job_id) {
            addLog(payload.message, 'info', payload.step);
        }
    });

    state.socket.on('motor_status', payload => {
        updateLiveStatus(payload);
    });

    state.socket.on('interface_status', payload => {
        if (payload.interfaces) {
            state.interfaceStatus = payload;
            renderInterfaceStatus();
            updateCanHealthStatus(payload);
            addLog('系统 CAN 接口状态已刷新', 'info', 'system_can');
        }
    });
}
