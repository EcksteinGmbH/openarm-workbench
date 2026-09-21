// Blocking problems (no CAN port, the port will not start, it cannot be opened)
// get a modal on top of the in-page panel. The operator cannot work around these
// inside the wizard, so the page must not let them click on past the message.

function esc(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

let retryHandler = null;

function elements() {
    return {
        modal: document.getElementById('problemModal'),
        title: document.getElementById('problemModalTitle'),
        body: document.getElementById('problemModalBody'),
        retry: document.getElementById('problemModalRetryBtn'),
        close: document.getElementById('problemModalCloseBtn')
    };
}

export function closeProblemModal() {
    retryHandler = null;
    const { modal } = elements();
    if (modal) modal.classList.add('hidden');
}

/**
 * @param problem   problem envelope from the API (title/message/solutions/detail/code)
 * @param onRetry   optional; when given, the modal offers 「我已处理，重试」
 */
export function showProblemModal(problem, onRetry) {
    const { modal, title, body, retry } = elements();
    if (!modal) return;
    retryHandler = typeof onRetry === 'function' ? onRetry : null;
    title.textContent = problem.title || '出错了';
    const solutions = (problem.solutions || []).map(item => `<li>${esc(item)}</li>`).join('');
    body.innerHTML = `
        <p>${esc(problem.message)}</p>
        ${solutions ? `<strong>怎么解决</strong><ol>${solutions}</ol>` : ''}
        ${problem.detail ? `<details><summary>技术信息（发给工程师）</summary><code>${esc(problem.code)}: ${esc(problem.detail)}</code></details>` : ''}`;
    retry.classList.toggle('hidden', !retryHandler);
    modal.classList.remove('hidden');
}

export function bindProblemModal() {
    const { modal, retry, close } = elements();
    if (!modal) return;
    close.addEventListener('click', closeProblemModal);
    retry.addEventListener('click', () => {
        const handler = retryHandler;
        closeProblemModal();
        if (handler) handler();
    });
    // No click-outside dismissal: a blocking problem should be acknowledged, and
    // the in-page panel keeps the same text after the modal is closed.
}
