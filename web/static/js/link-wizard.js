import { api } from './api.js';
import { addLog } from './log.js';
import { showProblemModal } from './problem-modal.js?v=20260921-words';
import { PROBLEM_KICKER, FIX_HEADING, RETRY, restartLabel } from './wizard-words.js?v=20260921-words';

// Beginner wizard for tab 01 (建联). Same shape as the single-motor wizard:
// one primary button per step, every failure explains cause and fix.
const STEPS = [
    { id: 'detect', label: '检测适配器' },
    { id: 'prepare', label: '配置 CAN 口' },
    { id: 'connect', label: '连接工作站' },
    { id: 'bus', label: '检查总线' },
    { id: 'done', label: '建联完成' }
];

const STEP_TIPS = {
    detect: [
        'USB-CAN 适配器插到电脑上，指示灯应该亮。',
        '达妙双路适配器需要刷 SocketCAN(gs_usb) 固件，否则 Linux 下看不到 can0。',
        '这一步只读取电脑上的接口，不会动电机。'
    ],
    prepare: [
        '出厂测试默认 CAN 2.0 / 1 Mbps。',
        'OpenArm 2.0 后续切 CAN FD 时才选 FD，并填数据段波特率。',
        '配置需要系统权限，失败时页面会给出终端命令。'
    ],
    connect: [
        '连接只是打开工作站到 CAN 口的通道，不会给电机发指令。',
        '同一个 CAN 口重复连接会复用已有连接。'
    ],
    bus: [
        '总线检查只读取 ID 和状态，电机不会转动。',
        '单电机调试时总线上应该只有一颗电机。',
        '整臂应该看到 8 个关节全部在线。'
    ],
    done: [
        '建联完成，可以去「02 单电机测试」或「03 整臂静态验收」。',
        '换适配器、重新插拔或重启 CAN 口后，请回到这里重新建联。'
    ]
};

const RETRY_ACTION = {
    adapter_missing: 'detect',
    can_interface_missing: 'detect',
    interface_prepare_failed: 'prepare',
    can_interface_down: 'prepare',
    can_bus_error: 'prepare',
    connect_failed: 'connect',
    bus_no_motor: 'bus'
};

const link = {
    step: 'detect',
    selection: { channel: 'can0', mode: 'can20', bitrate: 1000000, dbitrate: 5000000 },
    interfaces: [],
    prepared: null,
    connected: null,
    bus: null,
    problem: null,
    busy: ''
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

function formatTime(iso) {
    if (!iso) return '-';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('zh-CN', { hour12: false });
}

function selectedInterface() {
    return link.interfaces.find(item => item.name === link.selection.channel);
}

function renderSteps() {
    const activeIndex = STEPS.findIndex(step => step.id === link.step);
    document.getElementById('lwSteps').innerHTML = STEPS.map((step, index) => {
        const state = index < activeIndex ? 'done' : index === activeIndex ? (link.problem ? 'error' : 'active') : '';
        return `<li class="smw-step ${state}"><span>${index < activeIndex ? '✓' : index + 1}</span>${step.label}</li>`;
    }).join('');
}

function busyButton(label, action, extraClass = 'btn-primary', disabled = false) {
    const isBusy = Boolean(link.busy);
    return `<button class="btn ${extraClass} smw-big-btn" data-link-action="${action}" ${isBusy || disabled ? 'disabled' : ''}>${isBusy ? esc(link.busy) : label}</button>`;
}

function interfaceTable() {
    if (!link.interfaces.length) return '';
    return `
        <table class="smw-table">
            <thead><tr><th>CAN 口</th><th>驱动</th><th>模式 / 波特率</th><th>状态</th></tr></thead>
            <tbody>
                ${link.interfaces.map(item => `
                    <tr class="${item.name === link.selection.channel ? 'changed' : ''}">
                        <td>${esc(item.name)}</td>
                        <td>${esc(item.driver || '-')}</td>
                        <td>${esc(item.mode_text)} · ${esc(item.bitrate_text)}</td>
                        <td class="${item.healthy ? 'smw-good' : 'smw-bad'}">${esc(item.health_text)}</td>
                    </tr>`).join('')}
            </tbody>
        </table>`;
}

function renderDetect() {
    return `
        <div class="smw-card">
            <h3>1. 检测 USB-CAN 适配器</h3>
            <p class="muted">先确认电脑能看到适配器。这一步只读取系统信息，不会给电机发任何指令。</p>
            ${link.interfaces.length ? interfaceTable() : '<p class="muted">还没有检测。点下面的按钮开始。</p>'}
            <div class="smw-actions">${busyButton(link.interfaces.length ? '重新检测' : '检测适配器', 'detect')}</div>
        </div>`;
}

function renderPrepare() {
    const iface = selectedInterface();
    return `
        <div class="smw-card">
            <h3>2. 配置并启动 CAN 口</h3>
            ${interfaceTable()}
            <div class="smw-field">
                <span>使用哪个口</span>
                <div class="smw-segment">
                    ${link.interfaces.map(item => `<button data-link-select="channel" data-value="${esc(item.name)}" class="${link.selection.channel === item.name ? 'on' : ''}">${esc(item.name)}</button>`).join('')}
                </div>
            </div>
            <div class="smw-field">
                <span>通信模式</span>
                <div class="smw-segment">
                    <button data-link-select="mode" data-value="can20" class="${link.selection.mode === 'can20' ? 'on' : ''}">CAN 2.0 · 1 Mbps</button>
                    <button data-link-select="mode" data-value="canfd" class="${link.selection.mode === 'canfd' ? 'on' : ''}">CAN FD · 1M/5M</button>
                </div>
            </div>
            <p class="smw-note">出厂测试用 CAN 2.0 / 1 Mbps。${link.selection.mode === 'canfd' ? '已选 CAN FD：仲裁段 1 Mbps，数据段 5 Mbps，只在电机确实按 FD 配置时使用。' : ''}</p>
            ${iface && iface.healthy ? `<div class="smw-ok">${esc(iface.name)} 当前已经是 ${esc(iface.mode_text)} · ${esc(iface.bitrate_text)}，仍可重新配置一次。</div>` : ''}
            <div class="smw-actions">
                <button class="btn btn-secondary" data-link-action="back-detect" ${link.busy ? 'disabled' : ''}>返回上一步</button>
                ${busyButton('配置并启动', 'prepare')}
            </div>
        </div>`;
}

function renderConnect() {
    const iface = link.prepared || selectedInterface();
    return `
        <div class="smw-card">
            <h3>3. 连接工作站</h3>
            <div class="smw-ok">${esc(link.selection.channel)} 已启动：${esc(iface?.mode_text || '-')} · ${esc(iface?.bitrate_text || '-')} · ${esc(iface?.health_text || '-')}</div>
            <p class="muted">连接只是打开工作站到这个 CAN 口的通道，不会使能电机，也不会发送运动指令。</p>
            <div class="smw-actions">
                <button class="btn btn-secondary" data-link-action="back-prepare" ${link.busy ? 'disabled' : ''}>返回上一步</button>
                ${busyButton('连接工作站', 'connect')}
            </div>
        </div>`;
}

function busTable() {
    const motors = link.bus?.motors || [];
    return `
        <table class="smw-table">
            <thead><tr><th>ESC_ID</th><th>MST_ID</th><th>对应关节</th><th>状态</th><th>温度 MOS/线圈</th></tr></thead>
            <tbody>
                ${motors.map(item => `
                    <tr class="${item.has_error ? 'changed' : ''}">
                        <td>${hex(item.esc_id)}</td>
                        <td>${hex(item.mst_id)}</td>
                        <td>${item.matched_joints?.length ? esc(item.matched_joints.join(' / ')) : (item.factory_default_ids ? '出厂默认（未配置）' : '不匹配任何关节')}</td>
                        <td class="${item.has_error ? 'smw-bad' : 'smw-good'}">${esc(item.status || '-')}</td>
                        <td>${esc(item.t_mos ?? '-')} / ${esc(item.t_rotor ?? '-')} °C</td>
                    </tr>`).join('')}
            </tbody>
        </table>`;
}

function renderBus() {
    return `
        <div class="smw-card">
            <h3>4. 检查总线上有哪些电机</h3>
            <div class="smw-ok">工作站已连接 ${esc(link.selection.channel)}。</div>
            <p class="muted">扫描 ID 0x01–0x20，只读取 ID 和状态，电机不会转动。</p>
            <div class="smw-actions">
                <button class="btn btn-secondary" data-link-action="skip-bus" ${link.busy ? 'disabled' : ''}>跳过，直接完成</button>
                ${busyButton('检查总线', 'bus')}
            </div>
        </div>`;
}

function renderDone() {
    const bus = link.bus;
    return `
        <div class="smw-card">
            <h3>建联完成</h3>
            <div class="smw-ok">${esc(link.selection.channel)} 已连接（${esc(link.prepared?.mode_text || '-')} · ${esc(link.prepared?.bitrate_text || '-')}），时间 ${esc(formatTime(link.connected?.connected_at))}。</div>
            ${bus ? `
                <p class="muted">总线检查：找到 ${bus.motors.length} 颗电机，检查时间 ${esc(formatTime(bus.checked_at))}。</p>
                ${bus.duplicate_esc_ids?.length ? `<div class="smw-warning">发现重复 ESC_ID：${esc(bus.duplicate_esc_ids.map(hex).join('、'))}。同一条总线上的 ID 必须唯一。</div>` : ''}
                ${bus.faulted_esc_ids?.length ? `<div class="smw-warning">以下电机有故障状态：${esc(bus.faulted_esc_ids.map(hex).join('、'))}。请先排查电源和接线，不要进行测试。</div>` : ''}
                ${busTable()}` : '<p class="muted">未做总线检查。需要时可以回到上一步再检查。</p>'}
            <p class="smw-note">接下来：单颗电机配置去「02 单电机测试」；整臂通信盘点去「03 整臂静态验收」。</p>
            <div class="smw-actions">
                <button class="btn btn-secondary" data-link-action="restart" ${link.busy ? 'disabled' : ''}>重新建联</button>
                <button class="btn btn-secondary" data-link-action="disconnect" ${link.busy ? 'disabled' : ''}>断开连接</button>
                ${busyButton('重新检查总线', 'bus', 'btn-primary')}
            </div>
        </div>`;
}

function renderProblem() {
    const problem = link.problem;
    const retry = RETRY_ACTION[problem.code];
    return `
        <div class="smw-card smw-problem">
            <div class="smw-problem-kicker">${PROBLEM_KICKER}</div>
            <h3>${esc(problem.title)}</h3>
            <p>${esc(problem.message)}</p>
            <strong>${FIX_HEADING}</strong>
            <ol>${(problem.solutions || []).map(item => `<li>${esc(item)}</li>`).join('')}</ol>
            ${problem.detail ? `<code>${esc(problem.detail)}</code>` : ''}
            <div class="smw-actions">
                <button class="btn btn-secondary" data-link-action="restart" ${link.busy ? 'disabled' : ''}>${restartLabel('这条链路')}</button>
                ${retry ? busyButton(RETRY, retry) : ''}
            </div>
        </div>`;
}

function renderHelp() {
    const tips = STEP_TIPS[link.step] || [];
    document.getElementById('lwHelp').innerHTML = `
        <div class="smw-help-card">
            <h4>这一步要做什么</h4>
            <ul>${tips.map(tip => `<li>${esc(tip)}</li>`).join('')}</ul>
        </div>
        <div class="smw-help-card">
            <h4>全程安全</h4>
            <ul>
                <li>建联只读取接口和电机状态，不写参数、不使能、不转动。</li>
                <li>出错时页面会写清原因和处理办法，按提示做完再点重试。</li>
            </ul>
        </div>`;
}

function renderStatusLine() {
    const container = document.getElementById('lwStatus');
    if (link.connected) {
        container.className = 'smw-can-status good';
        container.textContent = `已连接 ${link.connected.channel} · ${link.prepared?.bitrate_text || ''}`;
        return;
    }
    const iface = selectedInterface();
    if (!link.interfaces.length) {
        container.className = 'smw-can-status bad';
        container.textContent = '未检测到 USB-CAN 适配器';
        return;
    }
    container.className = `smw-can-status ${iface?.healthy ? 'warn' : 'bad'}`;
    container.textContent = iface ? `${iface.name} ${iface.health_text}（尚未连接）` : '请选择 CAN 口';
}

function render() {
    renderSteps();
    renderStatusLine();
    const renderers = { detect: renderDetect, prepare: renderPrepare, connect: renderConnect, bus: renderBus, done: renderDone };
    document.getElementById('lwMain').innerHTML = link.problem ? renderProblem() : (renderers[link.step] || renderDetect)();
    renderHelp();
}

function clientProblem(error) {
    const message = String(error?.message || error);
    if (message.includes('Failed to fetch') || message.includes('NetworkError')) {
        return {
            code: 'server_unreachable',
            title: '连接不到工作站程序',
            message: '网页和工作站后台之间的连接断了。',
            solutions: ['确认工作站程序还在运行，刷新网页后重新开始。'],
            detail: message
        };
    }
    return { code: 'unknown_error', title: '发生未知错误', message: '请求失败。', solutions: [`点「${restartLabel('这条链路')}」再试一次；仍失败请截图发给工程师。`], detail: message };
}

async function run(busyText, request, onSuccess) {
    link.busy = busyText;
    link.problem = null;
    render();
    try {
        const payload = await request();
        if (payload.ok === false) {
            link.problem = payload.problem;
            addLog(`建联向导：${payload.problem.title}`, 'error', 'link');
            raiseIfBlocking(payload.problem);
        } else {
            onSuccess(payload);
        }
    } catch (error) {
        link.problem = clientProblem(error);
        addLog(`建联向导：${error.message}`, 'error', 'link');
        raiseIfBlocking(link.problem);
    } finally {
        link.busy = '';
        render();
    }
}

// A blocking problem means the CAN port itself is unusable; the operator has to
// leave the page and fix hardware or permissions, so say so in a dialog rather than
// only in the side panel they may not look at.
function raiseIfBlocking(problem) {
    if (!problem?.blocking) return;
    const action = RETRY_ACTION[problem.code];
    const retry = action ? () => ACTIONS[action]?.() : null;
    showProblemModal(problem, retry);
}

function post(url, body) {
    return api(url, { method: 'POST', body: JSON.stringify(body || {}) });
}

function detect() {
    return run('正在检测…', () => post('/api/link/wizard/detect'), payload => {
        link.interfaces = payload.interfaces || [];
        if (!link.interfaces.some(item => item.name === link.selection.channel)) {
            link.selection.channel = payload.recommended_channel || link.interfaces[0].name;
        }
        link.step = 'prepare';
        addLog(`建联向导：检测到 ${link.interfaces.length} 个 CAN 口`, 'info', 'link');
    });
}

function prepare() {
    const body = { channel: link.selection.channel, mode: link.selection.mode, bitrate: link.selection.mode === 'canfd' ? 1000000 : link.selection.bitrate };
    if (link.selection.mode === 'canfd') body.dbitrate = link.selection.dbitrate;
    return run('正在配置…', () => post('/api/link/wizard/prepare', body), payload => {
        link.prepared = payload.interface;
        link.interfaces = link.interfaces.map(item => (item.name === payload.interface.name ? payload.interface : item));
        link.step = 'connect';
        addLog(`建联向导：${payload.interface.name} 已配置为 ${payload.interface.mode_text} ${payload.interface.bitrate_text}`, 'info', 'link');
    });
}

function connect() {
    return run('正在连接…', () => post('/api/link/wizard/connect', { channel: link.selection.channel, bitrate: link.selection.mode === 'canfd' ? 1000000 : link.selection.bitrate }), payload => {
        link.connected = payload;
        link.prepared = payload.interface || link.prepared;
        link.step = 'bus';
        addLog(`建联向导：已连接 ${payload.channel}`, 'info', 'link');
    });
}

function busCheck() {
    return run('正在检查总线…', () => post('/api/link/wizard/bus-check', { channel: link.selection.channel, bitrate: link.selection.mode === 'canfd' ? 1000000 : link.selection.bitrate }), payload => {
        link.bus = payload;
        link.step = 'done';
        addLog(`建联向导：总线上找到 ${payload.motors.length} 颗电机`, 'info', 'link');
    });
}

function disconnect() {
    return run('正在断开…', () => post('/api/link/wizard/disconnect', { channel: link.selection.channel }), () => {
        link.connected = null;
        link.bus = null;
        link.step = 'prepare';
        addLog('建联向导：已断开连接', 'info', 'link');
    });
}

function restart() {
    link.problem = null;
    link.connected = null;
    link.bus = null;
    link.prepared = null;
    link.step = 'detect';
    render();
}

const ACTIONS = {
    detect,
    prepare,
    connect,
    bus: busCheck,
    disconnect,
    restart,
    'back-detect': () => { link.step = 'detect'; render(); },
    'back-prepare': () => { link.step = 'prepare'; render(); },
    'skip-bus': () => { link.step = 'done'; render(); }
};

function handleClick(event) {
    const selectButton = event.target.closest('[data-link-select]');
    if (selectButton) {
        if (link.busy) return;
        link.selection[selectButton.dataset.linkSelect] = selectButton.dataset.value;
        render();
        return;
    }
    const actionButton = event.target.closest('[data-link-action]');
    if (!actionButton || actionButton.disabled) return;
    ACTIONS[actionButton.dataset.linkAction]?.();
}

export async function initLinkWizard() {
    const root = document.getElementById('linkWizard');
    if (!root) return;
    root.addEventListener('click', handleClick);
    document.getElementById('lwAdvancedBtn').addEventListener('click', () => setAdvanced(true));
    document.getElementById('lwBackBtn').addEventListener('click', () => setAdvanced(false));
    render();
    await detect();
}

function setAdvanced(open) {
    document.getElementById('linkWizard').classList.toggle('hidden', open);
    document.getElementById('linkAdvancedTools').classList.toggle('hidden', !open);
    // The task rail and live monitor belong to the engineer tools, not the wizard.
    document.body.classList.toggle('link-advanced', open);
}
