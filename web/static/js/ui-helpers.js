export function kvRow(label, value) {
    return `
        <div class="kv-row">
            <span class="kv-key">${label}</span>
            <span class="kv-value">${value}</span>
        </div>
    `;
}

export function updateActionStatus(id, text, tone = 'blocked') {
    const node = document.getElementById(id);
    node.textContent = text;
    node.className = `action-status ${tone}`;
}

export function setButtonDisabled(id, disabled, reason = '') {
    const button = document.getElementById(id);
    if (button) {
        const isDisabled = Boolean(disabled);
        button.disabled = isDisabled;
        button.setAttribute('aria-disabled', String(isDisabled));
        if (isDisabled && reason) {
            button.title = reason;
        } else {
            button.removeAttribute('title');
        }
    }
}
