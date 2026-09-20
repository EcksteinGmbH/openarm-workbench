import { api } from './api.js';
import { addLog } from './log.js';
import { showProblemModal } from './problem-modal.js?v=20260920-arm-wizard';

// Beginner wizard for tab 03 (整臂测试). Every step is laid out on the page with its
// own button - the operator sees the whole flow, what is done, what is next and what
// is blocked, without a dialog driving them. Dialogs are reserved for failures the
// operator cannot clear from the page, exactly as in the other two wizards.

const SAFETY_CHECKS = [
    { id: 'estop', label: '急停按钮在手边，我知道怎么按' },
    { id: 'clear', label: '机械臂活动范围内没有人和障碍物' },
    { id: 'hands', label: '手远离夹爪和关节缝隙' }
];

const STATE_TEXT = {
    done: { mark: '✓', label: '已完成', cls: 'done' },
    current: { mark: '▶', label: '现在做这一步', cls: 'current' },
    pending: { mark: '', label: '等前面的步骤', cls: 'pending' },
    locked: { mark: '🔒', label: '暂时做不了', cls: 'locked' },
    skipped: { mark: '–', label: '本版本不需要', cls: 'skipped' },
    no_record: { mark: '?', label: '没有执行记录', cls: 'no-record' }
};

const arm = {
    arms: [],
    armCn: null,
    status: null,
    records: null,
    problem: null,
    busy: '',
    safety: {},
    open: null
};

function esc(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

function stepTag(step) {
    if (step.motion) return { text: '机械臂会运动', cls: 'motion' };
    if (step.writes) return { text: '会写入电机，但不运动', cls: 'writes' };
    return { text: '只读，不动电机', cls: 'readonly' };
}

function safetyReady(step) {
    if (!step.motion) return true;
    return SAFETY_CHECKS.every(check => arm.safety[`${step.id}:${check.id}`]);
}

// ---- 1. picking an arm -----------------------------------------------------------

function renderPicker() {
    const picker = document.getElementById('awPicker');
    if (!arm.arms.length) {
        picker.innerHTML = `
            <div class="aw-empty">
                <strong>还没有建档的机械臂</strong>
                <p class="muted">整臂测试从建档开始。点右上角「高级工具（工程师）」，在「官方动态测试 → 身份档案」里为这台臂建立整机编号，再回到这里。</p>
            </div>`;
        return;
    }
    picker.innerHTML = `
        <p class="muted aw-hint">整机编号是一台机械臂的身份证号，出厂报告按它归档。选中哪台，下面就显示哪台的进度。</p>
        <div class="aw-arm-list">
            ${arm.arms.map(item => `
                <button class="aw-arm ${item.arm_cn === arm.armCn ? 'selected' : ''}" data-arm="${esc(item.arm_cn)}" ${arm.busy ? 'disabled' : ''}>
                    <span class="aw-arm-cn">${esc(item.arm_cn)}</span>
                    <span class="aw-arm-meta">${esc(item.product_label)} · ${esc(item.arm_type || '-')}</span>
                    <span class="aw-arm-meta">已挂电机记录 ${item.attached_motor_records} / 16</span>
                </button>`).join('')}
        </div>`;
}

// ---- 2. the steps ----------------------------------------------------------------

function renderProgress() {
    const target = document.getElementById('awProgress');
    if (!arm.status) {
        target.textContent = '';
        return;
    }
    const steps = arm.status.steps.filter(step => step.state !== 'skipped');
    const done = steps.filter(step => step.state === 'done').length;
    const skipped = arm.status.steps.length - steps.length;
    target.textContent = `${done} / ${steps.length} 已完成${skipped ? `（${skipped} 步本版本不需要）` : ''}`;
}

function renderSteps() {
    const target = document.getElementById('awSteps');
    document.getElementById('awStepsSection').classList.toggle('hidden', !arm.status);
    document.getElementById('awMotorsSection').classList.toggle('hidden', !arm.status);
    if (!arm.status) {
        target.innerHTML = '';
        return;
    }
    target.innerHTML = arm.status.steps.map((step, index) => renderStep(step, index)).join('');
}

function renderStep(step, index) {
    const state = STATE_TEXT[step.state] || STATE_TEXT.pending;
    const tag = stepTag(step);
    const expanded = arm.open === step.id || (arm.open === null && step.state === 'current');
    const canRun = step.state !== 'skipped' && step.state !== 'locked';

    return `
        <article class="aw-step ${state.cls} ${expanded ? 'open' : ''}" data-step="${esc(step.id)}">
            <button class="aw-step-head" data-toggle="${esc(step.id)}">
                <span class="aw-step-mark">${state.mark}</span>
                <span class="aw-step-no">${String(index + 1).padStart(2, '0')}</span>
                <span class="aw-step-name">${esc(step.label)}</span>
                <span class="aw-step-state">${state.label}</span>
                <span class="aw-tag ${tag.cls}">${tag.text}</span>
            </button>
            ${expanded ? `
            <div class="aw-step-body">
                <p>${esc(step.purpose)}</p>
                ${step.locked ? `
                    <div class="aw-lock">
                        <strong>为什么做不了</strong>
                        <p>${esc(step.locked_reason)}</p>
                        <p class="muted">这一项通过真机验证后，这一步会自动开放。</p>
                    </div>` : ''}
                ${step.state === 'no_record' ? `
                    <div class="smw-note">这台臂是在工作站开始记录这一步之前测的。<strong>不代表没做过</strong>，放行门和出厂报告都不受影响；需要留证可以重测一次。</div>` : ''}
                ${step.state === 'skipped' ? '<p class="muted">这一步只有另一个产品版本需要。</p>' : ''}
                ${canRun && step.motion ? `
                    <div class="aw-safety">
                        <strong>这一步机械臂会动，逐条确认后才能开始</strong>
                        ${SAFETY_CHECKS.map(check => `
                            <label class="smw-confirm">
                                <input type="checkbox" data-safety="${esc(step.id)}:${esc(check.id)}"
                                    ${arm.safety[`${step.id}:${check.id}`] ? 'checked' : ''}>
                                <span>${esc(check.label)}</span>
                            </label>`).join('')}
                    </div>` : ''}
                ${canRun ? `
                    <div class="smw-actions">
                        <button class="btn ${step.state === 'done' ? 'btn-secondary' : 'btn-primary'}"
                            data-run="${esc(step.id)}"
                            ${arm.busy || !safetyReady(step) ? 'disabled' : ''}>
                            ${step.state === 'done' || step.state === 'no_record' ? '重新测这一步' : `开始「${esc(step.label)}」`}
                        </button>
                        ${step.motion && !safetyReady(step) ? '<span class="muted">勾选完上面三条才能开始</span>' : ''}
                    </div>` : ''}
            </div>` : ''}
        </article>`;
}

// ---- 3. motor records ------------------------------------------------------------

function renderMotors() {
    const target = document.getElementById('awMotors');
    if (!arm.status) {
        target.innerHTML = '';
        return;
    }
    const attached = arm.status.motor_records || [];
    const available = (arm.records?.records) || [];
    if (!attached.length && !available.length) {
        target.innerHTML = '<p class="muted">还没有属于这台臂的单电机记录。先在「02 单电机测试」里配置电机，记录会自动出现在这里。</p>';
        return;
    }
    const byJoint = new Map(attached.map(item => [item.joint_name, item]));
    const joints = [...new Set([...available.map(item => item.joint_name), ...byJoint.keys()])].sort();
    target.innerHTML = `
        <p class="muted aw-hint">单电机工位配好的电机挂到对应关节后，出厂报告会引用它们（已挂 ${attached.length} / ${joints.length}）。</p>
        <div class="aw-motor-grid">
            ${joints.map(joint => {
                const done = byJoint.get(joint);
                const candidate = available.find(item => item.joint_name === joint);
                return `
                <div class="aw-motor ${done ? 'done' : ''}">
                    <strong>${esc(joint)}</strong>
                    <small>${esc((done || candidate)?.motor_type || '-')}</small>
                    ${done
                        ? '<span class="aw-motor-state">已挂载</span>'
                        : candidate
                            ? `<button class="btn btn-secondary slim" data-attach="${esc(candidate.record_id)}" ${arm.busy ? 'disabled' : ''}>挂载</button>`
                            : '<span class="aw-motor-state missing">缺记录</span>'}
                </div>`;
            }).join('')}
        </div>`;
}

function renderBadge() {
    const badge = document.getElementById('awArmBadge');
    if (!arm.status) {
        badge.className = 'smw-can-status';
        badge.textContent = arm.arms.length ? '请选择机械臂' : '请先建档';
        return;
    }
    const pass = arm.status.release_decision === 'PASS';
    badge.className = `smw-can-status ${pass ? 'ok' : 'warn'}`;
    badge.textContent = `${arm.status.product_label} · 放行：${arm.status.release_decision}`;
}

function renderProblem() {
    const target = document.getElementById('awSteps');
    target.insertAdjacentHTML('afterbegin', `
        <div class="smw-card smw-problem">
            <div class="smw-problem-kicker">需要处理</div>
            <h3>${esc(arm.problem.title)}</h3>
            <p>${esc(arm.problem.message)}</p>
            <strong>怎么解决</strong>
            <ol>${(arm.problem.solutions || []).map(item => `<li>${esc(item)}</li>`).join('')}</ol>
            <div class="smw-actions">
                <button class="btn btn-primary" data-reload="1" ${arm.busy ? 'disabled' : ''}>处理好了，刷新</button>
            </div>
            ${arm.problem.detail ? `<details><summary>技术信息（发给工程师）</summary><code>${esc(arm.problem.code)}: ${esc(arm.problem.detail)}</code></details>` : ''}
        </div>`);
}

function render() {
    renderPicker();
    renderBadge();
    renderProgress();
    renderSteps();
    renderMotors();
    if (arm.problem) renderProblem();
}

// ---- data ------------------------------------------------------------------------

function clientProblem(error) {
    return {
        code: 'unknown_error',
        title: '发生未知错误',
        message: '请求失败。',
        solutions: ['点「处理好了，刷新」再试一次；仍失败请截图发给工程师。'],
        detail: error?.message
    };
}

async function run(busyText, request, onSuccess) {
    arm.busy = busyText;
    arm.problem = null;
    render();
    try {
        const payload = await request();
        if (payload.ok === false) {
            arm.problem = payload.problem;
            addLog(`整臂向导：${payload.problem.title}`, 'error', 'arm');
            if (payload.problem.blocking) showProblemModal(payload.problem, () => loadArm(arm.armCn));
        } else {
            await onSuccess(payload);
        }
    } catch (error) {
        arm.problem = clientProblem(error);
        addLog(`整臂向导：${error.message}`, 'error', 'arm');
    } finally {
        arm.busy = '';
        render();
    }
}

async function loadArms() {
    const payload = await api('/api/arm/wizard/arms');
    arm.arms = payload.arms || [];
    if (!arm.armCn || !arm.arms.some(item => item.arm_cn === arm.armCn)) {
        arm.armCn = arm.arms[0]?.arm_cn || null;
    }
}

async function loadArm(armCn) {
    if (!armCn) {
        arm.status = null;
        arm.records = null;
        render();
        return;
    }
    await run('正在读取…', () => api(`/api/arm/wizard/${encodeURIComponent(armCn)}/status`), async payload => {
        arm.armCn = armCn;
        arm.status = payload;
        arm.open = null;
        try {
            arm.records = await api(`/api/arm/wizard/${encodeURIComponent(armCn)}/motor-records`);
        } catch (error) {
            arm.records = null;
        }
    });
}

function attachRecord(recordId) {
    return run('正在挂载…', () => api(`/api/arm/wizard/${encodeURIComponent(arm.armCn)}/motor-records`, {
        method: 'POST',
        body: JSON.stringify({ record_id: recordId })
    }), async () => {
        addLog('整臂向导：电机记录已挂载', 'success', 'arm');
        await loadArms();
        await loadArm(arm.armCn);
    });
}

function runStep(stepId) {
    const step = (arm.status?.steps || []).find(item => item.id === stepId);
    if (!step) return;
    // Execution lands with the next release. Said on the step itself rather than in a
    // dialog: the operator asked a question by pressing it, and an answer that covers
    // the page is a worse answer.
    arm.problem = {
        code: 'step_not_wired',
        title: `「${step.label}」的执行入口还在工程工具里`,
        message: '这一步的顺序、判据和安全检查已经就位，执行按钮下一版接入向导。',
        solutions: [
            '点右上角「高级工具（工程师）」，在工程界面里执行这一步。',
            '做完点「返回整臂向导」，这里的进度会自动更新。'
        ]
    };
    render();
}

// ---- wiring ----------------------------------------------------------------------

function setAdvanced(open) {
    document.getElementById('armWizard').classList.toggle('hidden', open);
    document.getElementById('armAdvancedTools').classList.toggle('hidden', !open);
    document.body.classList.toggle('arm-advanced', open);
}

function handleClick(event) {
    if (arm.busy) return;
    const armButton = event.target.closest('[data-arm]');
    if (armButton) {
        loadArm(armButton.dataset.arm);
        return;
    }
    const toggle = event.target.closest('[data-toggle]');
    if (toggle) {
        arm.open = arm.open === toggle.dataset.toggle ? '' : toggle.dataset.toggle;
        render();
        return;
    }
    const attach = event.target.closest('[data-attach]');
    if (attach) {
        attachRecord(attach.dataset.attach);
        return;
    }
    const runButton = event.target.closest('[data-run]');
    if (runButton && !runButton.disabled) {
        runStep(runButton.dataset.run);
        return;
    }
    if (event.target.closest('[data-reload]')) loadArm(arm.armCn);
}

function handleChange(event) {
    const safety = event.target.closest('[data-safety]');
    if (!safety) return;
    arm.safety[safety.dataset.safety] = safety.checked;
    render();
}

export async function initArmWizard() {
    const root = document.getElementById('armWizard');
    if (!root) return;
    root.addEventListener('click', handleClick);
    root.addEventListener('change', handleChange);
    document.getElementById('awAdvancedBtn').addEventListener('click', () => setAdvanced(true));
    document.getElementById('awBackBtn').addEventListener('click', () => setAdvanced(false));
    render();
    try {
        await loadArms();
    } catch (error) {
        arm.problem = clientProblem(error);
    }
    render();
    if (arm.armCn) await loadArm(arm.armCn);
}
