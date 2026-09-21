import { api } from './api.js';
import { addLog } from './log.js';
import { showModal } from './modal.js';
import { showProblemModal } from './problem-modal.js?v=20260921-words';
import { PROBLEM_KICKER, FIX_HEADING, RETRY, restartLabel } from './wizard-words.js?v=20260921-words';

const STEPS = [
    { id: 'select', label: '选择关节' },
    { id: 'review', label: '识别并核对' },
    { id: 'save', label: '保存到电机' },
    { id: 'power', label: '断电重上电复核' },
    { id: 'done', label: '完成' }
];

const STEP_TIPS = {
    select: [
        '总线上只接要配置的这一颗电机。',
        '接好 CAN 线后给电机上电，确认急停 / 断电开关在手边。',
        '整个流程只改通信参数，电机不会转动。'
    ],
    review: [
        '标黄的参数会被修改，其余保持不变。',
        'TIMEOUT 只记录不修改，整臂验收时统一设置。',
        '确认关节选对了再点「写入并校验」。'
    ],
    save: [
        '参数已写入并校验通过，但还没保存，现在断电会丢失。',
        '点「保存到电机」，保存时不要断电。'
    ],
    power: [
        '关闭电机电源，等 3 秒再打开。',
        'USB-CAN 适配器不要拔。',
        '上电后等 2 秒，再点「复核并保存记录」。'
    ],
    done: [
        '记录已保存，整臂出厂报告会使用它。',
        '给电机贴上关节标签，避免装错位置。',
        '下一颗：断电 → 换电机 → 上电 → 点「配置下一颗电机」。'
    ]
};

// Problems that can be retried in place; every other problem requires restarting this motor.
const RETRY_ACTION = {
    can_interface_missing: 'identify',
    can_interface_down: 'identify',
    can_bus_error: 'identify',
    connect_failed: 'identify',
    no_motor_found: 'identify',
    multiple_motors: 'identify',
    motor_fault: 'identify',
    status_read_anomaly: 'identify',
    motor_overtemp: 'identify',
    save_failed: 'save',
    readback_no_response: 'finish'
};

const wizard = {
    options: null,
    selection: { product_line: 'openarm_2_0', arm_side: 'right_arm', joint: 'J1', channel: 'can0' },
    step: 'select',
    data: null,
    record: null,
    problem: null,
    busy: '',
    powerCycled: false,
    records: [],
    interfaces: []
};

function esc(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

function hex(value) {
    const number = Number(value);
    return Number.isFinite(number) && value !== null && value !== '' ? `0x${number.toString(16).toUpperCase().padStart(2, '0')}` : '-';
}

function formatValue(field, value) {
    if (value === null || value === undefined || value === '') return '<span class="smw-missing">读不到</span>';
    if (field === 'ESC_ID' || field === 'MST_ID') return `${hex(value)} <small>(${esc(value)})</small>`;
    if (field === 'can_br') return Number(value) >= 1000 ? `${Number(value) / 1000000} Mbps` : esc(value);
    return esc(value);
}

// Damiao can_br register codes -> bitrate; older records only store the raw readback code.
const CAN_BR_CODES = { 0: 125000, 1: 200000, 2: 250000, 3: 500000, 4: 1000000, 5: 2000000, 6: 2500000, 7: 3200000, 8: 4000000, 9: 5000000 };
const CTRL_MODES = { 1: 'MIT', 2: 'POS_VEL', 3: 'VEL', 4: 'Torque_Pos' };

function formatBitrate(bitrate) {
    return bitrate ? `${Number(bitrate) / 1000000} Mbps` : '-';
}

function verifiedValues(record) {
    const after = record?.after || {};
    const verified = record?.verified || {};
    const code = verified.can_br_code ?? after.can_br;
    const bitrate = verified.can_br ?? (code in CAN_BR_CODES ? CAN_BR_CODES[code] : code);
    return {
        escId: verified.ESC_ID ?? after.ESC_ID,
        mstId: verified.MST_ID ?? after.MST_ID,
        ctrlMode: verified.CTRL_MODE ?? CTRL_MODES[after.CTRL_MODE] ?? after.CTRL_MODE,
        canBr: bitrate ? `${formatBitrate(bitrate)}${code !== undefined && code !== null ? `（代码 ${code}）` : ''}` : '-',
        canMode: verified.can_mode || 'CAN 2.0'
    };
}

function selectedArm() {
    return wizard.options?.arms.find(arm => arm.arm_side === wizard.selection.arm_side);
}

function selectedJoint() {
    return selectedArm()?.joints.find(joint => joint.joint === wizard.selection.joint);
}

function productLabel(id) {
    return wizard.options?.product_lines.find(item => item.id === id)?.label || id || '-';
}

function formatTime(iso) {
    if (!iso) return '-';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('zh-CN', { hour12: false });
}

function renderSteps() {
    const activeIndex = STEPS.findIndex(step => step.id === wizard.step);
    document.getElementById('smwSteps').innerHTML = STEPS.map((step, index) => {
        const state = index < activeIndex ? 'done' : index === activeIndex ? (wizard.problem ? 'error' : 'active') : '';
        return `<li class="smw-step ${state}"><span>${index < activeIndex ? '✓' : index + 1}</span>${step.label}</li>`;
    }).join('');
}

function renderCanStatus() {
    const container = document.getElementById('smwCanStatus');
    const iface = wizard.interfaces.find(item => item.name === wizard.selection.channel);
    if (!wizard.interfaces.length) {
        container.className = 'smw-can-status bad';
        container.textContent = '未检测到 USB-CAN 适配器';
        return;
    }
    if (!iface) {
        container.className = 'smw-can-status bad';
        container.textContent = `未找到 ${wizard.selection.channel}`;
        return;
    }
    const up = String(iface.state || '').toUpperCase() === 'UP';
    const canState = String(iface.can_state || '').toUpperCase();
    const healthy = up && canState === 'ERROR-ACTIVE';
    container.className = `smw-can-status ${healthy ? 'good' : 'warn'}`;
    const rate = iface.bitrate ? `${iface.bitrate / 1000000} Mbps` : '未设置波特率';
    container.textContent = healthy
        ? `USB-CAN 正常 · ${iface.name} · ${rate}`
        : `USB-CAN ${iface.name} ${up ? canState || '状态未知' : '未启动'}（识别时会自动启动）`;
}

function busyButton(label, action, extraClass = 'btn-primary', disabled = false) {
    const isBusy = Boolean(wizard.busy);
    return `<button class="btn ${extraClass} smw-big-btn" data-action="${action}" ${isBusy || disabled ? 'disabled' : ''}>${isBusy ? esc(wizard.busy) : label}</button>`;
}

function targetSummary() {
    const joint = selectedJoint();
    if (!joint) return '';
    return `
        <div class="smw-target">
            <div><span>目标关节</span><strong>${esc(joint.joint_name)}</strong></div>
            <div><span>应装型号</span><strong>${esc(joint.motor_type)}</strong></div>
            <div><span>ESC_ID</span><strong>${hex(joint.target_esc_id)}</strong></div>
            <div><span>MST_ID</span><strong>${hex(joint.target_mst_id)}</strong></div>
            <div><span>模式</span><strong>${esc(joint.target_ctrl_mode)}</strong></div>
            <div><span>波特率</span><strong>${joint.target_can_br / 1000000} Mbps</strong></div>
        </div>`;
}

function renderSelect() {
    const options = wizard.options;
    if (!options) return '<div class="smw-card">正在加载…</div>';
    const arm = selectedArm();
    const channels = wizard.interfaces.length ? wizard.interfaces.map(item => item.name) : ['can0'];
    return `
        <div class="smw-card">
            <h3>1. 这颗电机装在哪里？</h3>
            <div class="smw-field">
                <span>产品</span>
                <div class="smw-segment">
                    ${options.product_lines.map(item => `<button data-select="product_line" data-value="${item.id}" class="${wizard.selection.product_line === item.id ? 'on' : ''}">${esc(item.label)}</button>`).join('')}
                </div>
            </div>
            <div class="smw-field">
                <span>左右臂</span>
                <div class="smw-segment">
                    ${options.arms.map(item => `<button data-select="arm_side" data-value="${item.arm_side}" class="${wizard.selection.arm_side === item.arm_side ? 'on' : ''}">${esc(item.label)}</button>`).join('')}
                </div>
            </div>
            <div class="smw-field">
                <span>关节</span>
                <div class="smw-joints">
                    ${(arm?.joints || []).map(joint => `
                        <button data-select="joint" data-value="${joint.joint}" class="${wizard.selection.joint === joint.joint ? 'on' : ''}">
                            <strong>${esc(joint.joint)}</strong><small>${hex(joint.target_esc_id)}</small>
                        </button>`).join('')}
                </div>
            </div>
            <div class="smw-field">
                <span>CAN 口</span>
                <div class="smw-segment">
                    ${channels.map(name => `<button data-select="channel" data-value="${name}" class="${wizard.selection.channel === name ? 'on' : ''}">${esc(name)}</button>`).join('')}
                </div>
            </div>
            ${targetSummary()}
            ${wizard.selection.product_line === 'openarm_2_0' ? '<p class="smw-note">OpenArm 2.0 电机现阶段按 CAN 2.0 / 1 Mbps 配置，装配后再统一调整。</p>' : ''}
            <div class="smw-start-row">
                <div class="smw-checklist">
                    <strong>开始前确认</strong>
                    <label><input type="checkbox" data-check="single"> 总线上只接了这一颗电机</label>
                    <label><input type="checkbox" data-check="power"> 电机已上电，断电开关在手边</label>
                </div>
                ${busyButton('识别电机', 'identify', 'btn-primary', !checklistDone())}
            </div>
        </div>`;
}

function checklistDone() {
    return Boolean(wizard.checks?.single && wizard.checks?.power);
}

const FAMILY_LABELS = { DM4310: 'DM-J4310 系列', DM4340: 'DM-J4340 系列', DM8009: 'DM-J8009 系列', DM6006: 'DM-J6006 系列', DM8006: 'DM-J8006 系列', DM10010: 'DM-J10010 系列', DM10010L: 'DM-J10010L 系列', DMH3510: 'DMH3510', DMH6215: 'DMH6215', DMG6220: 'DMG6220' };

function familyText(families) {
    return (families || []).map(item => FAMILY_LABELS[item] || item).join(' / ') || '无法判断';
}

function modelNeedsConfirm(check) {
    return Boolean(check) && check.verdict !== 'match';
}

function modelCheckBlock(data) {
    const check = data.model_check;
    if (!check) return '';
    const ev = check.evidence || {};
    const evidence = `电机内限位参数 PMAX ${esc(ev.PMAX ?? '-')} / VMAX ${esc(ev.VMAX ?? '-')} / TMAX ${esc(ev.TMAX ?? '-')}，减速比 Gr ${esc(ev.Gr ?? '-')}`;
    const sameFamilyNote = String(check.expected_motor_type || '').includes('4340')
        ? '<div class="muted">J3（DM-J4340P）和 J4（DM-J4340）参数相同，工作站分不出来，请看铭牌区分。</div>'
        : '';
    if (check.verdict === 'match') {
        return `
            <div class="smw-ok smw-model">
                <div>型号匹配：读到 <b>${esc(familyText(check.families))}</b>，符合 ${esc(data.joint_name)} 要求的 <b>${esc(check.expected_motor_type)}</b></div>
                <div class="smw-evidence">${evidence}</div>
                ${sameFamilyNote}
            </div>`;
    }
    const confirm = `<label class="smw-confirm"><input type="checkbox" data-check="modelConfirmed" ${wizard.modelConfirmed ? 'checked' : ''}> 我已对照电机铭牌，确认是 ${esc(check.expected_motor_type)}</label>`;
    if (check.verdict === 'mismatch') {
        return `
            <div class="smw-warning smw-model">
                <div><b>型号不符，可能接错关节！</b>这颗电机看起来是 <b>${esc(familyText(check.families))}</b>，但 ${esc(data.joint_name)} 需要 <b>${esc(check.expected_motor_type)}</b>。</div>
                <div class="smw-evidence">${evidence}</div>
                <div>请先看电机铭牌：如果确实接错，点「选错了，返回」换关节或换电机。</div>
            </div>
            ${confirm}`;
    }
    return `
        <div class="smw-note smw-model">
            <div><b>无法根据参数判断型号</b>，请对照铭牌确认是 <b>${esc(check.expected_motor_type)}</b>。</div>
            <div class="smw-evidence">${evidence}</div>
        </div>
        ${confirm}`;
}

function paramTable(rows) {
    return `
        <table class="smw-table">
            <thead><tr><th>参数</th><th>电机当前</th><th></th><th>目标</th></tr></thead>
            <tbody>
                ${rows.map(row => `
                    <tr class="${row.changes ? 'changed' : ''}">
                        <td>${esc(row.field)}</td>
                        <td>${formatValue(row.field, row.current)}</td>
                        <td class="smw-arrow">${row.written ? (row.changes ? '→ 修改' : '= 不变') : '只记录'}</td>
                        <td>${row.written ? formatValue(row.field, row.target) : '-'}</td>
                    </tr>`).join('')}
            </tbody>
        </table>`;
}

// ---- Read-only parameter viewer (no write, no motion) ----

const INSPECT_GROUPS = [
    { id: 'identity', label: '通信身份' },
    { id: 'motor', label: '电机参数' },
    { id: 'protection', label: '保护阈值' },
    { id: 'version', label: '版本与序列号' }
];

function inspectStatusBlock(motor) {
    const status = motor.status || {};
    const position = Number(status.position);
    return `
        <div class="smw-identity">
            <div><span>节点 ID</span><strong>${hex(motor.esc_id)} / ${hex(motor.mst_id)}</strong></div>
            <div><span>对应关节</span><strong>${motor.matched_joints?.length ? esc(motor.matched_joints.join(' / ')) : (motor.factory_default_ids ? '出厂默认（未配置）' : '不匹配任何关节')}</strong></div>
            <div><span>型号（参数推断）</span><strong>${esc(familyText(motor.model_check?.families))}</strong></div>
            <div><span>状态</span><strong class="${status.has_error ? 'smw-bad' : 'smw-good'}">${esc(status.status ?? '-')}${status.has_error ? '（有故障）' : ''}</strong></div>
            <div><span>位置</span><strong>${Number.isFinite(position) ? `${position.toFixed(4)} rad` : '-'}</strong></div>
            <div><span>温度 MOS/线圈</span><strong>${esc(status.t_mos ?? '-')} / ${esc(status.t_rotor ?? '-')} °C</strong></div>
        </div>`;
}

function inspectMotorBlock(motor) {
    const groups = INSPECT_GROUPS.map(group => {
        const rows = (motor.rows || []).filter(row => row.group === group.id);
        if (!rows.length) return '';
        return `
            <table class="smw-table smw-inspect-table">
                <thead><tr><th>${esc(group.label)}</th><th>读数</th></tr></thead>
                <tbody>
                    ${rows.map(row => `
                        <tr>
                            <td>${esc(row.label)}</td>
                            <td>${row.display === null || row.display === undefined ? '<span class="smw-missing">读不到</span>' : esc(row.display)}</td>
                        </tr>`).join('')}
                </tbody>
            </table>`;
    }).join('');
    return `<div class="smw-inspect-motor">${inspectStatusBlock(motor)}${groups}</div>`;
}

function renderInspect() {
    const body = document.getElementById('smwInspectBody');
    const meta = document.getElementById('smwInspectMeta');
    const refresh = document.getElementById('smwInspectRefreshBtn');
    refresh.disabled = Boolean(wizard.inspectBusy);
    refresh.textContent = wizard.inspectBusy ? '正在读取…' : '重新读取';
    if (wizard.inspectBusy) {
        meta.textContent = `正在读取 ${wizard.selection.channel} 上的电机…`;
        body.innerHTML = '<div class="smw-card">正在读取电机参数…</div>';
        return;
    }
    if (wizard.inspectProblem) {
        const problem = wizard.inspectProblem;
        meta.textContent = PROBLEM_KICKER;
        body.innerHTML = `
            <div class="smw-problem">
                <div class="smw-problem-kicker">${PROBLEM_KICKER}</div>
                <h3>${esc(problem.title)}</h3>
                <p>${esc(problem.message)}</p>
                <ol>${(problem.solutions || []).map(item => `<li>${esc(item)}</li>`).join('')}</ol>
                ${problem.detail ? `<code>${esc(problem.detail)}</code>` : ''}
            </div>`;
        return;
    }
    const data = wizard.inspect;
    if (!data) {
        meta.textContent = '只读查看，不会写入任何参数，电机不会转动。';
        body.innerHTML = '<div class="smw-card">点「重新读取」开始。</div>';
        return;
    }
    meta.textContent = `${data.channel} · 扫描范围 ${data.scanned_range} · 读取时间 ${formatTime(data.inspected_at)} · 只读，未写入任何参数`;
    body.innerHTML = `
        ${data.duplicate_esc_ids?.length ? `<div class="smw-warning">总线上有重复的 ESC_ID：${esc(data.duplicate_esc_ids.map(id => hex(id)).join('、'))}。请每次只接一颗电机。</div>` : ''}
        ${data.motors.length > 1 ? `<p class="smw-note">总线上有 ${data.motors.length} 颗电机应答。</p>` : ''}
        ${data.motors.map(inspectMotorBlock).join('')}`;
}

function openInspect() {
    document.getElementById('smwInspectModal').classList.remove('hidden');
    renderInspect();
    inspect();
}

function closeInspect() {
    document.getElementById('smwInspectModal').classList.add('hidden');
}

async function inspect() {
    wizard.inspectBusy = true;
    wizard.inspectProblem = null;
    renderInspect();
    try {
        const payload = await post('/api/single-motor/inspect', { channel: wizard.selection.channel, bitrate: 1000000 });
        if (payload.ok === false) {
            wizard.inspectProblem = payload.problem;
            addLog(`查看电机参数：${payload.problem.title}`, 'error', 'wizard');
        } else {
            wizard.inspect = payload;
            addLog(`查看电机参数：${wizard.selection.channel} 上读到 ${payload.motors.length} 颗电机`, 'info', 'wizard');
        }
    } catch (error) {
        wizard.inspectProblem = clientProblem(error);
        addLog(`查看电机参数失败: ${error.message}`, 'error', 'wizard');
    } finally {
        wizard.inspectBusy = false;
        renderInspect();
    }
}

function motorIdentity() {
    const data = wizard.data;
    if (!data) return '';
    return `
        <div class="smw-identity">
            <div><span>关节</span><strong>${esc(data.joint_name)}</strong></div>
            <div><span>型号（参数推断）</span><strong class="${data.model_check?.verdict === 'match' ? 'smw-good' : 'smw-bad'}">${esc(familyText(data.model_check?.families))}</strong></div>
            <div><span>当前 ID 状态</span><strong>${esc(idStateText(data))}</strong></div>
            <div><span>固件</span><strong>${esc(data.motor.firmware ?? '-')}</strong></div>
            <div><span>状态</span><strong>${esc(data.motor.status ?? '-')}</strong></div>
            <div><span>温度 MOS/线圈</span><strong>${esc(data.motor.t_mos ?? '-')} / ${esc(data.motor.t_rotor ?? '-')} °C</strong></div>
        </div>`;
}

function idStateText(data) {
    if (data.factory_default_ids) return '出厂默认（未配置）';
    if ((data.configured_as || []).length) return `已配置为 ${data.configured_as.join(' / ')}`;
    return '非默认 ID';
}

function configuredAsBlock(data) {
    const configured = data.configured_as || [];
    if (!configured.length) return '';
    if (configured.includes(data.joint_name)) {
        return `<p class="smw-note">这颗电机的 ID 已经是 ${esc(data.joint_name)}，本次会重新写入并复核，生成一条新记录。</p>`;
    }
    return `<div class="smw-warning"><b>这颗电机已经被配置成 ${esc(configured.join(' / '))}</b>，继续会改成 ${esc(data.joint_name)}。请确认这颗电机确实要装在 ${esc(data.joint_name)}。</div>`;
}

function renderReview() {
    const data = wizard.data;
    return `
        <div class="smw-card">
            <h3>2. 已识别到电机，请核对</h3>
            ${motorIdentity()}
            ${modelCheckBlock(data)}
            ${configuredAsBlock(data)}
            ${(data.joint_taken_by || []).length ? `<div class="smw-warning"><b>注意：${esc(data.joint_name)} 在 ${formatTime(data.joint_taken_by[0].created_at)} 已经配置过一颗电机。</b>请确认关节没有选错；如果是在更换这个关节的电机，可以继续。</div>` : ''}
            ${paramTable(data.param_rows)}
            <p class="muted">${data.needs_write ? '标黄的参数将被修改。' : '参数已经符合目标，仍会重新写入并校验一次，确保记录完整。'}</p>
            <div class="smw-actions">
                <button class="btn btn-secondary" data-action="restart" ${wizard.busy ? 'disabled' : ''}>选错了，返回</button>
                ${busyButton('写入并校验', 'write', 'btn-primary', modelNeedsConfirm(data.model_check) && !wizard.modelConfirmed)}
            </div>
        </div>`;
}

function renderSave() {
    return `
        <div class="smw-card">
            <h3>3. 保存到电机</h3>
            ${motorIdentity()}
            <div class="smw-ok">参数写入并回读校验通过。</div>
            <p class="muted">保存后参数断电也不会丢失。保存期间不要断电。</p>
            <div class="smw-actions">${busyButton('保存到电机', 'save', 'btn-warning')}</div>
        </div>`;
}

function renderPower() {
    return `
        <div class="smw-card">
            <h3>4. 断电重上电，确认参数已保存</h3>
            <div class="smw-ok">已保存到电机。</div>
            <ol class="smw-instructions">
                <li>关闭电机电源，等待 3 秒。</li>
                <li>重新打开电机电源（USB-CAN 不要拔）。</li>
                <li>等待 2 秒后勾选下面的确认，再点按钮。</li>
            </ol>
            <label class="smw-confirm"><input type="checkbox" data-check="powerCycled" ${wizard.powerCycled ? 'checked' : ''}> 我已经断电并重新上电</label>
            <div class="smw-actions">${busyButton('复核并保存记录', 'finish', 'btn-primary', !wizard.powerCycled)}</div>
        </div>`;
}

function modelVerdictText(check) {
    if (!check) return '-';
    if (check.verdict === 'match') return `参数匹配（${familyText(check.families)}）`;
    if (check.verdict === 'mismatch') return `参数不符，已人工确认（${familyText(check.families)}）`;
    return '参数无法判断，已人工确认';
}

function nextJointLabel() {
    const joints = selectedArm()?.joints || [];
    const index = joints.findIndex(joint => joint.joint === wizard.selection.joint);
    return index >= 0 && index < joints.length - 1 ? `配置下一颗电机（${esc(joints[index + 1].joint_name)}）` : '配置下一颗电机';
}

function renderDone() {
    const record = wizard.record || {};
    const verified = verifiedValues(record);
    return `
        <div class="smw-card smw-done">
            <div class="smw-pass">PASS</div>
            <h3>${esc(record.joint_name)} 配置完成，记录已保存</h3>
            <div class="smw-identity">
                <div><span>型号</span><strong>${esc(record.motor_type)}</strong></div>
                <div><span>型号核对</span><strong>${esc(modelVerdictText(record.model_check))}</strong></div>
                <div><span>产品</span><strong>${esc(record.product_line_label || productLabel(record.product_line))}</strong></div>
                <div><span>时间</span><strong>${formatTime(record.created_at)}</strong></div>
            </div>
            <div class="smw-subtitle">断电重上电后从电机读回的参数</div>
            <div class="smw-identity smw-verified">
                <div><span>ESC_ID</span><strong>${hex(verified.escId)}</strong></div>
                <div><span>MST_ID</span><strong>${hex(verified.mstId)}</strong></div>
                <div><span>控制模式</span><strong>${esc(verified.ctrlMode ?? '-')}</strong></div>
                <div><span>波特率</span><strong>${esc(verified.canBr)}</strong></div>
                <div><span>总线模式</span><strong>${esc(verified.canMode)}</strong></div>
                <div><span>TIMEOUT（只记录）</span><strong>${esc(record.timeout_recorded ?? '-')}</strong></div>
            </div>
            <div class="smw-actions">${busyButton(nextJointLabel(), 'next')}</div>
        </div>`;
}

function renderHelp() {
    const help = document.getElementById('smwHelp');
    const problem = wizard.problem;
    if (problem) {
        const retry = RETRY_ACTION[problem.code];
        const mismatches = problem.mismatches?.length
            ? `<ul class="smw-mismatch">${problem.mismatches.map(item => `<li>${esc(item.field)}：目标 ${esc(item.expected)}，读到 ${esc(item.actual ?? '无应答')}</li>`).join('')}</ul>`
            : '';
        help.innerHTML = `
            <div class="smw-problem">
                <div class="smw-problem-kicker">${PROBLEM_KICKER}</div>
                <h3>${esc(problem.title)}</h3>
                <p>${esc(problem.message)}</p>
                ${problem.found_esc_ids ? `<p>检测到的电机 ID：${problem.found_esc_ids.map(hex).join('、')}</p>` : ''}
                ${mismatches}
                <strong>${FIX_HEADING}</strong>
                <ol>${(problem.solutions || []).map(item => `<li>${esc(item)}</li>`).join('')}</ol>
                <div class="smw-actions">
                    ${retry ? `<button class="btn btn-primary" data-action="${retry}" ${wizard.busy ? 'disabled' : ''}>${RETRY}</button>` : ''}
                    <button class="btn btn-secondary" data-action="restart" ${wizard.busy ? 'disabled' : ''}>${restartLabel('这颗电机')}</button>
                </div>
                ${problem.detail ? `<details><summary>技术信息（发给工程师）</summary><code>${esc(problem.code)}: ${esc(problem.detail)}</code></details>` : ''}
            </div>`;
        return;
    }
    help.innerHTML = `
        <div class="smw-tips">
            <div class="smw-problem-kicker">这一步要注意</div>
            <ul>${(STEP_TIPS[wizard.step] || []).map(item => `<li>${esc(item)}</li>`).join('')}</ul>
        </div>`;
}

function renderRecords() {
    const container = document.getElementById('smwRecords');
    if (!wizard.records.length) {
        container.innerHTML = '<div class="muted">还没有记录</div>';
        return;
    }
    container.innerHTML = `
        <table class="smw-table compact">
            <thead><tr><th>时间</th><th>关节</th><th>型号</th><th>产品</th><th>ESC / MST</th><th>模式</th><th>波特率</th><th>TIMEOUT</th><th>结果</th><th></th></tr></thead>
            <tbody>
                ${wizard.records.slice(0, 12).map(record => {
                    const verified = verifiedValues(record);
                    return `
                    <tr>
                        <td>${formatTime(record.created_at)}</td>
                        <td>${esc(record.joint_name)}</td>
                        <td>${esc(record.motor_type || '-')}${record.model_check && record.model_check.verdict !== 'match' ? ' ⚠' : ''}</td>
                        <td>${esc(record.product_line_label || record.product_line || '-')}</td>
                        <td>${hex(verified.escId)} / ${hex(verified.mstId)}</td>
                        <td>${esc(verified.ctrlMode ?? '-')}</td>
                        <td>${esc(verified.canBr)}</td>
                        <td>${esc(record.timeout_recorded ?? '-')}</td>
                        <td><span class="smw-badge ${record.result === 'PASS' ? 'pass' : 'fail'}">${esc(record.result)}</span></td>
                        <td><button class="btn btn-ghost slim" data-withdraw="${esc(record.record_id)}" ${wizard.busy ? 'disabled' : ''}>撤回</button></td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>`;
}

let lastRenderedStep = null;

function render() {
    if (lastRenderedStep !== wizard.step) {
        document.getElementById('singleMotorWizard').scrollTop = 0;
        lastRenderedStep = wizard.step;
    }
    renderSteps();
    renderCanStatus();
    const main = document.getElementById('smwMain');
    const renderers = { select: renderSelect, review: renderReview, save: renderSave, power: renderPower, done: renderDone };
    main.innerHTML = (renderers[wizard.step] || renderSelect)();
    if (wizard.step === 'select') {
        main.querySelectorAll('[data-check]').forEach(input => {
            input.checked = Boolean(wizard.checks?.[input.dataset.check]);
        });
    }
    renderHelp();
}

function clientProblem(error) {
    const message = String(error?.message || error);
    if (message.includes('job not found')) {
        return {
            code: 'job_lost',
            title: '工作站重启过，当前进度丢失',
            message: '工作站程序重新启动后，正在进行的电机任务不再有效。',
            solutions: [`点「${restartLabel('这颗电机')}」重新识别。已经保存到电机的参数不会丢失。`],
            detail: message
        };
    }
    if (message.includes('Failed to fetch') || message.includes('NetworkError')) {
        return {
            code: 'server_unreachable',
            title: '连接不到工作站程序',
            message: '网页和工作站后台之间的连接断了。',
            solutions: ['确认工作站程序还在运行，刷新网页后重新开始。'],
            detail: message
        };
    }
    return { code: 'unknown_error', title: '发生未知错误', message: '请求失败。', solutions: [`点「${restartLabel('这颗电机')}」再试一次；仍失败请截图发给工程师。`], detail: message };
}

async function run(busyText, request, onSuccess) {
    wizard.busy = busyText;
    wizard.problem = null;
    render();
    try {
        const payload = await request();
        if (payload.ok === false) {
            wizard.problem = payload.problem;
            addLog(`单电机向导：${payload.problem.title}`, 'error', 'wizard');
            raiseIfBlocking(payload.problem);
        } else {
            onSuccess(payload);
        }
    } catch (error) {
        wizard.problem = clientProblem(error);
        addLog(`单电机向导：${error.message}`, 'error', 'wizard');
        raiseIfBlocking(wizard.problem);
    } finally {
        wizard.busy = '';
        render();
    }
}

// A blocking problem means the CAN port itself is unusable; nothing in the wizard
// can get past it, so raise a dialog instead of relying on the side panel.
function raiseIfBlocking(problem) {
    if (!problem?.blocking) return;
    const action = RETRY_ACTION[problem.code];
    const retry = action ? () => ACTIONS[action]?.() : null;
    showProblemModal(problem, retry);
}

function post(url, body) {
    return api(url, { method: 'POST', body: JSON.stringify(body || {}) });
}

async function identify() {
    await run('正在识别电机（约 10 秒）…', () => post('/api/single-motor/wizard/identify', wizard.selection), payload => {
        wizard.data = payload;
        wizard.modelConfirmed = false;
        wizard.step = 'review';
        addLog(`识别到电机（${idStateText(payload)}），目标 ${payload.joint_name}`, 'success', 'wizard');
    });
    await refreshInterfaces();
}

function confirmWrite() {
    const data = wizard.data;
    showModal(
        '确认写入参数',
        `将把这颗电机配置为 ${data.joint_name}（ESC_ID ${hex(data.param_rows[0].target)} / MST_ID ${hex(data.param_rows[1].target)}）。请再次确认总线上只有这一颗电机。`,
        () => run('正在写入并校验…', () => post(`/api/single-motor/wizard/${data.job_id}/write`), payload => {
            wizard.data = payload;
            wizard.step = 'save';
            addLog(`${payload.joint_name} 参数写入并校验通过`, 'success', 'wizard');
        })
    );
}

async function save() {
    await run('正在保存…', () => post(`/api/single-motor/wizard/${wizard.data.job_id}/save`), payload => {
        wizard.data = payload;
        wizard.step = 'power';
        wizard.powerCycled = false;
        addLog(`${payload.joint_name} 参数已保存到电机`, 'success', 'wizard');
    });
}

async function finish() {
    await run('正在复核…', () => post(`/api/single-motor/wizard/${wizard.data.job_id}/finish`), payload => {
        wizard.data = payload;
        wizard.record = payload.record;
        wizard.step = 'done';
        addLog(`${payload.joint_name} 复核通过，记录已保存`, 'success', 'wizard');
    });
    await refreshRecords();
}

function restart() {
    wizard.step = 'select';
    wizard.data = null;
    wizard.record = null;
    wizard.problem = null;
    wizard.powerCycled = false;
    wizard.modelConfirmed = false;
    wizard.checks = {};
    render();
}

function withdrawRecord(recordId) {
    const record = wizard.records.find(item => item.record_id === recordId);
    // A retested or bad motor leaves a record that is no longer the truth about that
    // joint. Withdrawing moves it aside; it is still a hardware measurement, and a
    // record an arm is using is refused with the way to free it.
    showModal(
        '撤回这条电机记录？',
        `${record?.joint_name || recordId} 的记录会移出列表，文件保留在 withdrawn_single_motor_records/ 备查。如果它已挂在某台机械臂上，会提示你先去取消挂载。`,
        () => run('正在撤回…', () => api(`/api/single-motor/records/${encodeURIComponent(recordId)}`, { method: 'DELETE' }), async () => {
            addLog(`单电机记录已撤回：${record?.joint_name || recordId}`, 'info', 'wizard');
            await refreshRecords();
        })
    );
}

async function refreshRecords() {
    try {
        const payload = await api('/api/single-motor/records?limit=50');
        wizard.records = payload.records || [];
    } catch (error) {
        addLog(`读取单电机记录失败: ${error.message}`, 'error', 'wizard');
    }
    renderRecords();
}

async function refreshInterfaces() {
    try {
        const payload = await api('/api/system/can-interfaces');
        wizard.interfaces = payload.interfaces || [];
        if (wizard.interfaces.length && !wizard.interfaces.some(item => item.name === wizard.selection.channel)) {
            wizard.selection.channel = payload.recommended_channel || wizard.interfaces[0].name;
        }
    } catch (error) {
        wizard.interfaces = [];
    }
    renderCanStatus();
}

function setAdvanced(open) {
    document.getElementById('singleMotorWizard').classList.toggle('hidden', open);
    document.getElementById('motorAdvancedTools').classList.toggle('hidden', !open);
    document.body.classList.toggle('motor-advanced', open);
}

const ACTIONS = {
    identify,
    write: confirmWrite,
    save,
    finish,
    restart,
    next: () => {
        const joints = selectedArm()?.joints || [];
        const index = joints.findIndex(joint => joint.joint === wizard.selection.joint);
        if (index >= 0 && index < joints.length - 1) {
            wizard.selection.joint = joints[index + 1].joint;
        }
        restart();
        refreshInterfaces();
    }
};

function handleClick(event) {
    const selectButton = event.target.closest('[data-select]');
    if (selectButton) {
        if (wizard.busy) return;
        wizard.selection[selectButton.dataset.select] = selectButton.dataset.value;
        if (selectButton.dataset.select === 'arm_side' && !selectedJoint()) {
            wizard.selection.joint = 'J1';
        }
        render();
        return;
    }
    const withdrawButton = event.target.closest('[data-withdraw]');
    if (withdrawButton && !withdrawButton.disabled) {
        withdrawRecord(withdrawButton.dataset.withdraw);
        return;
    }
    const actionButton = event.target.closest('[data-action]');
    if (!actionButton || actionButton.disabled) return;
    ACTIONS[actionButton.dataset.action]?.();
}

function handleChange(event) {
    const input = event.target.closest('[data-check]');
    if (!input) return;
    if (input.dataset.check === 'powerCycled') {
        wizard.powerCycled = input.checked;
    } else if (input.dataset.check === 'modelConfirmed') {
        wizard.modelConfirmed = input.checked;
    } else {
        wizard.checks = { ...(wizard.checks || {}), [input.dataset.check]: input.checked };
    }
    render();
}

export async function initSingleMotorWizard() {
    const root = document.getElementById('singleMotorWizard');
    if (!root) return;
    wizard.checks = {};
    root.addEventListener('click', handleClick);
    root.addEventListener('change', handleChange);
    document.getElementById('smwAdvancedBtn').addEventListener('click', () => setAdvanced(true));
    document.getElementById('smwBackToWizardBtn').addEventListener('click', () => setAdvanced(false));
    document.getElementById('smwInspectBtn').addEventListener('click', openInspect);
    document.getElementById('smwInspectCloseBtn').addEventListener('click', closeInspect);
    document.getElementById('smwInspectRefreshBtn').addEventListener('click', inspect);
    document.getElementById('smwInspectModal').addEventListener('click', event => {
        if (event.target.id === 'smwInspectModal') closeInspect();
    });
    render();
    try {
        wizard.options = await api('/api/single-motor/wizard/options');
        Object.assign(wizard.selection, wizard.options.defaults || {});
        delete wizard.selection.bitrate;
    } catch (error) {
        wizard.problem = clientProblem(error);
    }
    await refreshInterfaces();
    render();
    await refreshRecords();
}
