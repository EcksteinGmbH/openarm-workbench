import { state } from './store.js';

export function addLog(message, type = 'info', step = 'ui') {
    state.logEntries.unshift({
        time: new Date().toLocaleTimeString(),
        type,
        step,
        message
    });
    state.logEntries = state.logEntries.slice(0, 20);
    renderLog();
}

export function renderLog() {
    const container = document.getElementById('eventLog');
    if (!state.logEntries.length) {
        container.innerHTML = '<div class="empty-state">暂无事件</div>';
        return;
    }

    container.innerHTML = state.logEntries.map(entry => `
        <div class="log-entry ${entry.type}">
            <div class="log-head">
                <span>${entry.step}</span>
                <span>${entry.time}</span>
            </div>
            <div>${entry.message}</div>
        </div>
    `).join('');
}
