import { api } from './api.js';
import { addLog } from './log.js';
import { showProblemModal } from './problem-modal.js?v=20260920-problem-modal';

// Beginner wizard for tab 03 (整臂测试). Same contract as the link and single-motor
// wizards: one primary button per step, every failure explains cause and fix. Twelve
// steps do not fit a horizontal strip, so the rail runs down the left instead.

const STATE_ICON = { done: '✓', current: '▶', pending: '', locked: '🔒', skipped: '–', no_record: '?' };

// Ticked before any step that moves the arm. Deliberately short: a checklist nobody
// reads is worse than none.
const SAFETY_CHECKS = [
    { id: 'estop', label: '急停按钮在手边，我知道怎么按' },
    { id: 'clear', label: '机械臂活动范围内没有人和障碍物' },
    { id: 'hands', label: '手远离夹爪和关节缝隙' }
];

const arm = {
    options: null,
    arms: [],
    armCn: null,
    status: null,
    records: null,
    problem: null,
    busy: '',
    safety: {}
};

function esc(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

function currentStep() {
    return (arm.status?.steps || []).find(step => step.state === 'current') || null;
}

function stepById(stepId) {
    return (arm.status?.steps || []).find(step => step.id === stepId) || null;
}

// ---- rendering -------------------------------------------------------------------

function renderPicker() {
    const picker = document.getElementById('awPicker');
    if (!arm.arms.length) {
        picker.innerHTML = `
            <div class="aw-picker-empty">
                <strong>还没有建档的机械臂</strong>
                <p class="muted">整臂测试从建档开始：先在「高级工具 → 官方动态测试 → 身份档案」为这台臂建立整机编号，再回到这里。</p>
            </div>`;
        return;
    }
    picker.innerHTML = `
        <label class="aw-picker-label" for="awArmSelect">机械臂</label>
        <select id="awArmSelect" class="aw-select">
            ${arm.arms.map(item => `
                <option value="${esc(item.arm_cn)}" ${item.arm_cn === arm.armCn ? 'selected' : ''}>
                    ${esc(item.arm_cn)} · ${esc(item.product_label)}${item.attached_motor_records ? ` · 已挂 ${item.attached_motor_records} 颗电机` : ''}
                </option>`).join('')}
        </select>
        <span class="muted aw-picker-hint">换一台臂只是切换查看，不会改动任何记录。</span>`;
}

function renderBadge() {
    const badge = document.getElementById('awArmBadge');
    if (!arm.status) {
        badge.textContent = arm.arms.length ? '请选择机械臂' : '请先建档';
        badge.className = 'smw-can-status';
        return;
    }
    const pass = arm.status.release_decision === 'PASS';
    badge.className = `smw-can-status ${pass ? 'ok' : 'warn'}`;
    badge.textContent = `${arm.status.product_label} · 放行：${arm.status.release_decision}`;
}

function renderRail() {
    const rail = document.getElementById('awRail');
    if (!arm.status) {
        rail.innerHTML = '';
        return;
    }
    rail.innerHTML = arm.status.steps.map((step, index) => `
        <li class="aw-step ${step.state}" data-step="${esc(step.id)}">
            <span class="aw-step-mark">${STATE_ICON[step.state] || ''}</span>
            <span class="aw-step-no">${String(index + 1).padStart(2, '0')}</span>
            <span class="aw-step-text">
                <strong>${esc(step.label)}</strong>
                <small>${stepNote(step)}</small>
            </span>
        </li>`).join('');
}

function stepNote(step) {
    if (step.state === 'skipped') return '本版本不需要';
    // This arm passed the release gate but this step left no record. Saying "not done"
    // would send an operator to redo a Flash write on a finished arm.
    if (step.state === 'no_record') return '无执行记录';
    return stepTag(step);
}

function stepTag(step) {
    if (step.locked) return '待真机验证';
    if (step.motion) return '机械臂会运动';
    if (step.writes) return '写入电机，不运动';
    return '只读';
}

function safetyReady(step) {
    if (!step.motion) return true;
    return SAFETY_CHECKS.every(check => arm.safety[`${step.id}:${check.id}`]);
}

function renderMain() {
    const main = document.getElementById('awMain');
    if (!arm.armCn) {
        main.innerHTML = `
            <div class="smw-card">
                <h3>先选一台机械臂</h3>
                <p class="muted">选定之后，这里会按官方顺序显示当前该做哪一步。</p>
            </div>`;
        return;
    }
    if (arm.problem) {
        main.innerHTML = renderProblem();
        return;
    }
    const step = currentStep();
    if (!step) {
        main.innerHTML = renderFinished();
        return;
    }
    main.innerHTML = renderStep(step);
}

function renderStep(step) {
    const badges = [
        step.motion ? '<span class="aw-badge motion">机械臂会运动</span>' : '',
        step.writes ? '<span class="aw-badge writes">会写入电机</span>' : '',
        !step.motion && !step.writes ? '<span class="aw-badge readonly">只读，不动电机</span>' : ''
    ].join('');

    const safety = step.motion ? `
        <div class="aw-safety">
            <strong>动手之前，逐条确认</strong>
            ${SAFETY_CHECKS.map(check => `
                <label class="smw-confirm">
                    <input type="checkbox" data-safety="${esc(step.id)}:${esc(check.id)}"
                        ${arm.safety[`${step.id}:${check.id}`] ? 'checked' : ''}>
                    <span>${esc(check.label)}</span>
                </label>`).join('')}
        </div>` : '';

    const ready = safetyReady(step);
    const blocked = arm.busy || !ready;

    return `
        <div class="smw-card aw-step-card">
            <div class="group-kicker">当前步骤</div>
            <h3>${esc(step.label)}</h3>
            <p>${esc(step.purpose)}</p>
            <div class="aw-badges">${badges}</div>
            ${safety}
            <div class="smw-actions">
                <button class="btn btn-primary" data-arm-action="run" ${blocked ? 'disabled' : ''}>
                    ${arm.busy ? esc(arm.busy) : `开始「${esc(step.label)}」`}
                </button>
                ${step.motion && !ready ? '<span class="muted">勾选完上面三条才能开始</span>' : ''}
            </div>
        </div>
        ${renderMotorRecords()}`;
}

function renderFinished() {
    const pass = arm.status.release_decision === 'PASS';
    return `
        <div class="smw-card aw-step-card ${pass ? 'aw-pass' : ''}">
            <div class="group-kicker">${pass ? '全部完成' : '还差一点'}</div>
            <h3>${pass ? '这台臂已经可以放行' : '流程走完了，但放行门拦住了'}</h3>
            ${pass
                ? `<p>放行门已通过：证据齐全、版本一致。</p>${renderNoRecordNote()}`
                : `<p>放行门列出的问题要先处理：</p><ul>${(arm.status.blocking_items || []).map(item => `<li>${esc(item)}</li>`).join('')}</ul>`}
        </div>
        ${renderMotorRecords()}`;
}

function renderNoRecordNote() {
    const missing = (arm.status?.steps || []).filter(step => step.state === 'no_record');
    if (!missing.length) return '';
    return `
        <div class="smw-note">
            <strong>这些步骤没有留下执行记录：</strong>${missing.map(step => esc(step.label)).join('、')}。
            这台臂是在工作站记录这些步骤之前测的，不代表没做过——放行门和出厂报告不受影响。
        </div>`;
}

function renderMotorRecords() {
    const attached = arm.status?.motor_records || [];
    const available = arm.records?.records || [];
    if (!available.length && !attached.length) return '';
    const byJoint = new Map(attached.map(item => [item.joint_name, item]));
    const joints = [...new Set([...available.map(item => item.joint_name), ...byJoint.keys()])].sort();
    return `
        <section class="smw-card aw-motors">
            <div class="smw-records-heading">
                <h3>这台臂的电机记录</h3>
                <span class="muted">单电机工位配好的电机挂到对应关节，出厂报告会用它们（已挂 ${attached.length} / ${joints.length}）</span>
            </div>
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
            </div>
        </section>`;
}

function renderProblem() {
    const problem = arm.problem;
    return `
        <div class="smw-card smw-problem">
            <div class="smw-problem-kicker">需要处理</div>
            <h3>${esc(problem.title)}</h3>
            <p>${esc(problem.message)}</p>
            <strong>怎么解决</strong>
            <ol>${(problem.solutions || []).map(item => `<li>${esc(item)}</li>`).join('')}</ol>
            <div class="smw-actions">
                <button class="btn btn-primary" data-arm-action="reload" ${arm.busy ? 'disabled' : ''}>处理好了，刷新</button>
            </div>
            ${problem.detail ? `<details><summary>技术信息（发给工程师）</summary><code>${esc(problem.code)}: ${esc(problem.detail)}</code></details>` : ''}
        </div>`;
}

function renderHelp() {
    const help = document.getElementById('awHelp');
    const step = currentStep();
    const locked = (arm.status?.steps || []).filter(item => item.state === 'locked');
    help.innerHTML = `
        ${step ? `
        <div class="smw-help-card">
            <h4>这一步要注意</h4>
            <ul>
                <li>${step.motion ? '机械臂会运动，请先做完安全确认。' : '这一步不会让机械臂运动。'}</li>
                <li>${step.writes ? '参数会写入电机并保存，写完会自动回读复核。' : '不会改动电机里的参数。'}</li>
                <li>出错时页面会说明原因和处理办法，照着做再重试即可。</li>
            </ul>
        </div>` : ''}
        ${locked.length ? `
        <div class="smw-help-card aw-locked-card">
            <h4>暂时做不了的步骤</h4>
            <ul>${locked.map(item => `<li><strong>${esc(item.label)}</strong>：${esc(item.locked_reason)}</li>`).join('')}</ul>
            <p class="muted">这些步骤会在对应项目通过真机验证后自动开放。</p>
        </div>` : ''}`;
}

function render() {
    renderPicker();
    renderBadge();
    renderRail();
    renderMain();
    renderHelp();
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

function raiseIfBlocking(problem) {
    if (!problem?.blocking) return;
    showProblemModal(problem, () => loadArm(arm.armCn));
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
            raiseIfBlocking(payload.problem);
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

function runStep() {
    const step = currentStep();
    if (!step) return;
    if (step.locked) {
        arm.problem = {
            code: 'arm_step_locked',
            title: '这一步还不能执行',
            message: step.locked_reason,
            solutions: ['先完成该项的真机验证，再回到这一步。'],
            blocking: true
        };
        raiseIfBlocking(arm.problem);
        render();
        return;
    }
    // The per-step handlers land with the execution release; until then the wizard
    // shows the flow and hands the operator to the engineer tools for this step.
    showProblemModal({
        code: 'step_not_wired',
        title: `「${step.label}」还没接上执行`,
        message: '这一步的流程和判据已经就位，但执行入口还在工程工具里。',
        solutions: [
            '点页面右上角「高级工具（工程师）」，在那里执行这一步。',
            '完成后回到本页，进度会自动更新。'
        ]
    }, () => loadArm(arm.armCn));
}

// ---- wiring ----------------------------------------------------------------------

function handleClick(event) {
    const attach = event.target.closest('[data-attach]');
    if (attach && !attach.disabled) {
        attachRecord(attach.dataset.attach);
        return;
    }
    const action = event.target.closest('[data-arm-action]');
    if (!action || action.disabled) return;
    if (action.dataset.armAction === 'run') runStep();
    if (action.dataset.armAction === 'reload') loadArm(arm.armCn);
}

function handleChange(event) {
    const select = event.target.closest('#awArmSelect');
    if (select) {
        loadArm(select.value);
        return;
    }
    const safety = event.target.closest('[data-safety]');
    if (safety) {
        arm.safety[safety.dataset.safety] = safety.checked;
        render();
    }
}

export async function initArmWizard() {
    const root = document.getElementById('armWizard');
    if (!root) return;
    root.addEventListener('click', handleClick);
    root.addEventListener('change', handleChange);
    document.getElementById('awAdvancedBtn').addEventListener('click', () => {
        document.querySelector('.tab-button[data-tab="staticAcceptanceTab"]')?.click();
    });
    render();
    try {
        arm.options = await api('/api/arm/wizard/options');
        await loadArms();
    } catch (error) {
        arm.problem = clientProblem(error);
    }
    render();
    if (arm.armCn) await loadArm(arm.armCn);
}
