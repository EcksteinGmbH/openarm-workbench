import { api } from './api.js';
import {
    ARM_MATRIX_FIELDS,
    isArmAcceptance,
    isArmVerification,
    isSingleCommCheck,
    isSingleCommissioning,
    isSingleParamConfig,
    isSingleParameterTask,
} from './job-types.js';
import {
    currentPrimaryTab,
    preferredWorkbenchTab,
    renderExecuteTabs,
    switchExecuteTab,
    switchFactorySection,
    switchPrimaryTab,
    switchTestingSubtab,
} from './navigation.js';
import { addLog, renderLog } from './log.js';
import {
    currentFactoryArmCn,
    factoryEvidenceInterface,
    factorySerialPayloadBase,
    nativeZeroConfirmations,
    officialBaudratePayload,
    officialDemoConfirmations,
    officialMotorCheckPayload,
    officialZeroConfirmations,
} from './factory-helpers.js';
import { selectedDiagnosticJoint } from './diagnostic-helpers.js';
import { closeModal, showModal } from './modal.js';
import { buildConnectionPayload, buildOverrides } from './form-payloads.js';
import { bindEvents } from './event-bindings.js';
import { initSocket } from './socket-client.js';
import { kvRow, setButtonDisabled, updateActionStatus } from './ui-helpers.js';
import { state } from './store.js';
import { initSingleMotorWizard } from './single-motor-wizard.js?v=20260920-problem-modal';
import { initLinkWizard } from './link-wizard.js?v=20260920-problem-modal';
import { bindProblemModal } from './problem-modal.js?v=20260920-problem-modal';
import { initArmWizard } from './arm-wizard.js?v=20260920-arm-wizard';
import { initReportArchive, initDiskMaintenance } from './report-archive.js?v=20260921-undo';

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[character]));
}

function renderProfiles() {
    const profileSelect = document.getElementById('profileSelect');
    profileSelect.innerHTML = state.config.profiles.map(profile => `
        <option value="${profile.profile_id}">${profile.name}</option>
    `).join('');
    renderTargetJoints();
}

function currentProfile() {
    const profileId = document.getElementById('profileSelect').value;
    return state.config.profiles.find(profile => profile.profile_id === profileId);
}

function renderTargetJoints() {
    const targetJoint = document.getElementById('targetJoint');
    const profile = currentProfile();
    targetJoint.innerHTML = profile.joints.map(joint => `
        <option value="${joint.joint_name}">${joint.joint_name} · ${joint.motor_type}</option>
    `).join('');
    renderDiagnosticJointOptions();
    renderFactoryJointOptions();
    renderScopeAssumptions();
}

function renderDiagnosticJointOptions() {
    const select = document.getElementById('diagnosticJointSelect');
    const profile = currentProfile();
    if (!profile) {
        select.innerHTML = '';
        return;
    }
    const detectedIds = new Set((state.lineInventory?.inventory || []).map(item => Number(item.detected_esc_id)));
    select.innerHTML = profile.joints.map(joint => {
        const online = detectedIds.has(Number(joint.target_esc_id));
        return `<option value="${joint.joint_name}">${joint.joint_name} · ${joint.motor_type}${online ? ' · 在线' : ''}</option>`;
    }).join('');
}

function renderFactoryJointOptions() {
    const select = document.getElementById('factoryJointSelect');
    if (!select) {
        return;
    }
    const profile = currentProfile();
    if (!profile) {
        select.innerHTML = '';
        return;
    }
    select.innerHTML = profile.joints.map(joint => `
        <option value="${joint.joint_name}">${joint.joint_name} · ${joint.motor_type}</option>
    `).join('');
}

function formatTargetConfigLabel(key) {
    const labels = {
        joint_name: 'Joint',
        motor_type: 'OpenARM 官方型号',
        target_esc_id: '目标 ESC_ID',
        target_mst_id: '目标 MST_ID',
        target_ctrl_mode: '目标 CTRL_MODE',
        target_timeout: '目标 TIMEOUT',
        target_can_br: '目标 can_br',
        expected_ctrl_mode: '期望 CTRL_MODE',
        expected_bus: '期望总线',
        requires_zero: '需要零位',
        test_profile: '测试配置',
        required_online: '要求在线',
        allow_write: '允许写入'
    };
    return labels[key] || key;
}

function renderScopeAssumptions() {
    const jobType = document.getElementById('jobType').value;
    const profile = currentProfile();
    const assumptionText = document.getElementById('assumptionText');
    const scopeList = document.getElementById('scopeList');
    const targetJointField = document.getElementById('targetJointField');
    const manualIdField = document.getElementById('manualIdField');
    const expertOverridesCard = document.getElementById('expertOverridesCard');
    const expertMode = document.getElementById('expertMode').checked;

    if (isSingleCommissioning(jobType)) {
        assumptionText.textContent = '单机工装：同一时刻只连接一颗电机；识别成功后才允许写参数、保存 Flash、零位和测试。';
        targetJointField.classList.remove('hidden');
        manualIdField.classList.toggle('hidden', !expertMode);
    } else if (isSingleParamConfig(jobType)) {
        assumptionText.textContent = '单电机参数配置：以当前电机参数为基础，可修改模式、波特率和关键控制参数，并保存到 Flash。';
        targetJointField.classList.remove('hidden');
        manualIdField.classList.toggle('hidden', !expertMode);
    } else if (isSingleCommCheck(jobType)) {
        assumptionText.textContent = '单电机通信校验：只读取参数和状态，不写入参数，不发送动作控制帧。';
        targetJointField.classList.add('hidden');
        manualIdField.classList.toggle('hidden', !expertMode);
    } else if (isArmAcceptance(jobType)) {
        assumptionText.textContent = '整臂验收：机械臂已装配且 ID 已配置正确；执行总线盘点、参数一致性校验，并给出放行结论。';
        targetJointField.classList.add('hidden');
        manualIdField.classList.add('hidden');
    } else {
        assumptionText.textContent = '整臂复检：机械臂已装配且 ID 已配置正确；只做探测、读取、校验和报告。';
        targetJointField.classList.add('hidden');
        manualIdField.classList.add('hidden');
    }

    expertOverridesCard.classList.toggle('hidden', !(isSingleParamConfig(jobType) || (expertMode && isSingleCommissioning(jobType))));
    document.getElementById('paramEditorTitle').textContent = isSingleParamConfig(jobType) ? '参数编辑' : '专家模式覆盖';

    const profileLine = profile
        ? `当前模板: ${profile.name}${profile.arm_side ? ` · ${profile.arm_side}` : ''}${profile.expected_bus || profile.joints?.[0]?.expected_bus ? ` · 默认通道 ${profile.expected_bus || profile.joints?.[0]?.expected_bus}` : ''}`
        : '当前模板: -';

    const scopeLines = isSingleCommissioning(jobType)
        ? [
            '允许改 ESC_ID / MST_ID / CTRL_MODE / TIMEOUT / can_br',
            '保存前必须回读校验',
            '保存后可执行零位和 safe_mit_ping',
            profileLine
        ]
        : isSingleParamConfig(jobType)
            ? [
                '允许修改 CTRL_MODE / TIMEOUT / can_br / KT_Value / Gr / PMAX / VMAX / TMAX',
                '默认读取当前电机参数作为编辑基线',
                '保存后不做动作测试，直接生成配置结果与问题清单',
                profileLine
            ]
        : isSingleCommCheck(jobType)
            ? [
                '只读取 ESC_ID / MST_ID / can_br / CTRL_MODE / 状态',
                '不写参数，不保存 Flash',
                '适合刷写后复核和单关节掉线排查',
                profileLine
            ]
            : isArmAcceptance(jobType)
                ? [
                    '按 profile 执行整臂 CAN2.0 放行验收',
                    '检查缺失节点、重复 ID、参数不一致和异常状态',
                    '输出 PASS / HOLD 放行结论',
                    profileLine,
                    '官方顺序: 先 Step 1~3 建链与校验，再进入波特率、零位和 Demo'
                ]
            : [
            '按 profile 做整臂 CAN2.0 盘点与对账',
            '不写参数，不保存 Flash，不执行零位',
            '输出缺失节点、MST_ID 不匹配、异常状态与意外节点',
            profileLine,
            '官方顺序: 先 Step 1~3 建链与校验，再进入波特率、零位和 Demo'
        ];

    scopeList.innerHTML = scopeLines.map(line => `<li>${line}</li>`).join('');
    renderExecuteMode();
}

function singleCommissioningExpert() {
    const jobExpert = state.currentJob?.job?.expert_mode;
    if (typeof jobExpert === 'boolean') return jobExpert;
    return Boolean(document.getElementById('expertMode')?.checked);
}

function renderSteps() {
    const jobType = document.getElementById('jobType').value;
    const steps = isSingleCommissioning(jobType)
        ? (singleCommissioningExpert()
            ? ['连接', '识别', '选择 Joint', '写入参数', '回读校验', '保存 Flash', '零位(专家)', '复核/测试', '报告']
            : ['连接', '识别', '选择 Joint', '写入参数', '回读校验', '保存 Flash', '保存后复核', '报告'])
        : isSingleParamConfig(jobType)
            ? ['连接', '识别', '加载参数基线', '写入参数', '回读校验', '保存 Flash', '报告']
        : isSingleCommCheck(jobType)
            ? ['连接', '识别', '读取参数', '状态校验', '报告']
            : isArmAcceptance(jobType)
                ? ['连接', '选择 Profile', 'CAN2.0 扫描', '验收判定', '报告']
                : ['连接', '选择 Profile', 'CAN2.0 扫描', '逐 Joint 校验', '报告'];
    const currentStep = (state.currentJob?.job?.current_step || 'draft').toLowerCase();
    const activeKeywords = isSingleCommissioning(jobType)
        ? {
            '连接': ['device_connected'],
            '识别': ['identified'],
            '选择 Joint': ['profile_selected'],
            '写入参数': ['params_written'],
            '回读校验': ['params_verified'],
            '保存 Flash': ['params_saved'],
            '零位(专家)': ['zeroed'],
            '复核/测试': ['tested', 'passed'],
            '保存后复核': ['tested', 'passed'],
            '报告': ['passed', 'failed', 'cancelled']
        }
        : isSingleParamConfig(jobType)
            ? {
                '连接': ['device_connected'],
                '识别': ['identified'],
                '加载参数基线': ['profile_selected'],
                '写入参数': ['params_written'],
                '回读校验': ['params_verified'],
                '保存 Flash': ['params_saved'],
                '报告': ['reported', 'passed', 'failed']
            }
        : isSingleCommCheck(jobType)
            ? {
                '连接': ['device_connected'],
                '识别': ['identified'],
                '读取参数': ['params_read'],
                '状态校验': ['checked', 'passed'],
                '报告': ['passed', 'failed']
            }
            : isArmAcceptance(jobType)
                ? {
                    '连接': ['device_connected'],
                    '选择 Profile': ['profile_loaded', 'device_connected'],
                    'CAN2.0 扫描': ['bus_scanning'],
                    '验收判定': ['acceptance_checked', 'tested', 'reported', 'passed', 'failed'],
                    '报告': ['reported', 'passed', 'failed']
                }
            : {
                '连接': ['device_connected'],
                '选择 Profile': ['profile_loaded', 'device_connected'],
                'CAN2.0 扫描': ['bus_scanning'],
                '逐 Joint 校验': ['consistency_checked', 'tested', 'reported', 'passed', 'failed'],
                '报告': ['reported', 'passed', 'failed']
            };
    document.getElementById('stepList').innerHTML = steps.map(step => `
        <div class="step-item ${(activeKeywords[step] || []).some(keyword => currentStep.includes(keyword)) ? 'active' : ''}">
            ${step}
        </div>
    `).join('');
}

function renderExecuteMode() {
    const jobType = document.getElementById('jobType').value;
    const commissioningMode = isSingleCommissioning(jobType);
    const paramConfigMode = isSingleParamConfig(jobType);
    const commCheckMode = isSingleCommCheck(jobType);
    const armScanMode = isArmVerification(jobType);
    const testInfoTitle = document.getElementById('testInfoTitle');
    const testInfo = document.getElementById('testInfoList');
    const testActionTitle = document.getElementById('testActionTitle');
    const testButton = document.getElementById('testBtn');
    const writeBtn = document.getElementById('writeParamsBtn');
    const verifyBtn = document.getElementById('verifyParamsBtn');
    const saveBtn = document.getElementById('saveFlashBtn');
    const zeroBtn = document.getElementById('zeroBtn');
    const targetConfigCard = document.getElementById('targetConfigCard');
    const executeSummary = document.getElementById('executeSummary');

    renderExecuteTabs(jobType);

    writeBtn.textContent = '写入参数';
    verifyBtn.textContent = '回读校验';
    saveBtn.textContent = '保存 Flash';
    zeroBtn.textContent = '执行零位';

    if (armScanMode) {
        switchExecuteTab('testPanel');
        executeSummary.textContent = isArmAcceptance(jobType)
            ? '当前任务只保留整臂验收命令，流程外命令已隐藏。'
            : '当前任务只保留整臂扫描命令，参数写入和零位命令已隐藏。';
        if (isArmAcceptance(jobType)) {
            testInfoTitle.textContent = 'CAN2.0 整臂验收';
            testInfo.innerHTML = [
                '<li>遍历总线并校验 J1~J8 的 ESC_ID / MST_ID / can_br / CTRL_MODE</li>',
                '<li>识别缺失节点、重复 ID、异常状态与意外节点</li>',
                '<li>输出 PASS / HOLD 放行结论</li>'
            ].join('');
            testActionTitle.textContent = '执行整臂验收';
            testButton.textContent = '开始验收';
        } else {
            testInfoTitle.textContent = 'CAN2.0 通信扫描';
            testInfo.innerHTML = [
                '<li>遍历 CAN2.0 总线上的候选 ESC_ID</li>',
                '<li>按 OpenARM profile 校验 ESC_ID / MST_ID / 状态</li>',
                '<li>不执行参数写入、零位或动作控制</li>'
            ].join('');
            testActionTitle.textContent = '执行通信扫描';
            testButton.textContent = '开始扫描';
        }
        writeBtn.textContent = '整臂任务不写参数';
        verifyBtn.textContent = '整臂任务无需回读';
        saveBtn.textContent = '整臂任务不保存';
        zeroBtn.textContent = '整臂任务不零位';
        if (!state.currentJob?.motors?.commissioned_motor) {
            targetConfigCard.className = 'kv-list empty-state';
            targetConfigCard.textContent = '整臂复检只读取 profile 和扫描结果，不套用单电机目标参数。';
        }
    } else {
        if (!commissioningMode) {
            switchExecuteTab('testPanel');
        }
        if (commissioningMode && state.currentJob?.job?.status === 'zeroed') {
            executeSummary.textContent = '专家任务：零位已保存，可执行 safe_mit_ping 小幅动作测试。';
            testInfoTitle.textContent = 'safe_mit_ping';
            testInfo.innerHTML = [
                '<li>`q=+0.05 rad`，`kp=10`，`kd=0.2`</li>',
                '<li>持续 250 ms 后回到 `q=0`</li>',
                '<li>动作完成后自动失能</li>'
            ].join('');
            testActionTitle.textContent = '执行测试';
            testButton.textContent = '执行测试';
        } else if (commissioningMode) {
            executeSummary.textContent = singleCommissioningExpert()
                ? '专家任务：参数 / 保存 / (可选)零位 / 复核。零位仅限有文档化夹具基准时使用。'
                : '装配前单电机 ID 配置：参数 / 保存 / 保存后复核。不保存零位、不发送动作帧。';
            testInfoTitle.textContent = '保存后只读复核';
            testInfo.innerHTML = [
                '<li>建议先断电重上电，再回读 ESC_ID / MST_ID / CTRL_MODE / can_br</li>',
                '<li>检查状态无故障、未使能、温度未越限</li>',
                '<li>不使能、不发送动作帧；通过后生成报告</li>'
            ].join('');
            testActionTitle.textContent = '保存后复核';
            testButton.textContent = '复核并完成';
            if (!singleCommissioningExpert()) {
                zeroBtn.textContent = '装配前不零位';
            }
        } else if (paramConfigMode) {
            executeSummary.textContent = '当前任务聚焦参数配置，流程为 参数编辑 / 保存 / 完成归档。';
            testInfoTitle.textContent = '参数配置完成';
            testInfo.innerHTML = [
                '<li>保存 Flash 成功后即可完成任务</li>',
                '<li>不会执行零位和动作测试</li>',
                '<li>测试中心的问题监测会汇总参数不一致和保存失败问题</li>'
            ].join('');
            testActionTitle.textContent = '完成配置并生成报告';
            testButton.textContent = '完成配置';
            zeroBtn.textContent = '参数配置不零位';
        } else {
            executeSummary.textContent = '当前任务只保留通信校验命令，其余写入和动作命令已隐藏。';
            testInfoTitle.textContent = '单电机通信校验';
            testInfo.innerHTML = [
                '<li>读取 ESC_ID / MST_ID / can_br / CTRL_MODE / 状态</li>',
                '<li>检查是否在线、是否故障、温度是否越限</li>',
                '<li>不会发送动作控制帧</li>'
            ].join('');
            testActionTitle.textContent = '执行通信校验';
            testButton.textContent = '开始校验';
            writeBtn.textContent = '通信校验不写参数';
            verifyBtn.textContent = '通信校验无需回读';
            saveBtn.textContent = '通信校验不保存';
            zeroBtn.textContent = '通信校验不零位';
            targetConfigCard.className = 'kv-list empty-state';
            targetConfigCard.textContent = '通信校验任务不需要目标 Joint。';
        }
    }

    renderWorkflowCommand();
}

function renderTransportForm() {
    const transport = document.getElementById('transportType').value;
    document.getElementById('serialConnectionForm').classList.toggle('hidden', transport !== 'serial_bridge');
    document.getElementById('socketcanConnectionForm').classList.toggle('hidden', transport !== 'socketcan');
}

function renderCapabilities() {
    const card = document.getElementById('capabilitiesCard');
    if (!state.capabilities) {
        card.className = 'capability-list empty-state';
        card.textContent = '连接后显示';
        return;
    }

    card.className = 'capability-list kv-list';
    card.innerHTML = Object.entries(state.capabilities).map(([key, value]) => `
        <div class="kv-row">
            <span class="kv-key">${key}</span>
            <span class="kv-value">${value ? 'YES' : 'NO'}</span>
        </div>
    `).join('');
}

function syncSystemCanForm(preferredName = null) {
    const select = document.getElementById('systemCanName');
    const mode = document.getElementById('systemCanMode');
    const bitrateInput = document.getElementById('systemCanBitrate');
    const dbitrateInput = document.getElementById('systemCanDbitrate');
    const dbitrateField = document.getElementById('systemCanDbitrateField');
    const interfaces = state.interfaceStatus?.interfaces || [];
    const currentName = preferredName || select.value;

    if (!interfaces.length) {
        select.innerHTML = '<option value="">无接口</option>';
        select.disabled = true;
        bitrateInput.value = 1000000;
        dbitrateInput.value = 5000000;
        dbitrateField.classList.toggle('hidden', mode.value !== 'canfd');
        ['canConfigureBtn', 'canUpBtn', 'canDownBtn'].forEach(id => {
            document.getElementById(id).disabled = true;
        });
        return;
    }

    select.disabled = false;
    ['canConfigureBtn', 'canUpBtn', 'canDownBtn'].forEach(id => {
        document.getElementById(id).disabled = false;
    });
    select.innerHTML = interfaces.map(item => `
        <option value="${item.name}">${item.name}</option>
    `).join('');

    const nextName = interfaces.some(item => item.name === currentName)
        ? currentName
        : (state.interfaceStatus?.recommended_channel || interfaces[0].name);
    select.value = nextName;

    const selected = interfaces.find(item => item.name === select.value) || interfaces[0];
    mode.value = selected.fd_enabled ? 'canfd' : 'can20';
    bitrateInput.value = selected.bitrate || 1000000;
    dbitrateInput.value = selected.dbitrate || 5000000;
    dbitrateField.classList.toggle('hidden', mode.value !== 'canfd');
}

function renderInterfaceStatus() {
    const summary = document.getElementById('interfaceSummary');
    const card = document.getElementById('interfaceCard');
    if (!state.interfaceStatus) {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '正在检测接口...';
        card.className = 'artifact-list empty-state';
        card.textContent = '尚未识别到 SocketCAN 接口';
        syncSystemCanForm();
        return;
    }

    const interfaces = state.interfaceStatus.interfaces || [];
    summary.className = 'summary-grid';
    summary.innerHTML = [
        ['接口数', interfaces.length],
        ['推荐通道', state.interfaceStatus.recommended_channel || '-'],
        ['gs_usb 设备', interfaces.filter(item => item.is_gs_usb).length],
        ['FD 接口', interfaces.filter(item => item.fd_enabled).length]
    ].map(([label, value]) => `
        <div class="summary-card">
            <div class="status-label">${label}</div>
            <div class="status-value">${value}</div>
        </div>
    `).join('');

    if (!interfaces.length) {
        card.className = 'artifact-list empty-state';
        card.textContent = '未发现 SocketCAN 接口。请确认 gsusb1002enc 已接入、驱动已加载且 can 设备已经出现。';
        syncSystemCanForm();
        return;
    }

    card.className = 'artifact-list';
    card.innerHTML = interfaces.map(item => `
        <div class="artifact-item ${item.is_gs_usb ? 'adapter-detected' : ''}">
            <strong>${item.name}</strong>
            <div>适配器: ${item.adapter_kind || item.product || item.interface_label || '-'}</div>
            <div>驱动: ${item.driver || '-'}</div>
            <div>状态: ${item.state || '-'}</div>
            <div>Bitrate: ${item.bitrate || '-'}</div>
            <div>DBitrate: ${item.dbitrate || '-'}</div>
            <div>FD: ${item.fd_enabled ? 'ON' : 'OFF'}</div>
            <div>Errors: RX ${item.statistics?.rx_errors ?? 0} / TX ${item.statistics?.tx_errors ?? 0}</div>
            <div>Dropped: ${item.statistics?.total_dropped ?? 0}</div>
            <div>Manufacturer: ${item.manufacturer || '-'}</div>
            <div>Product: ${item.product || '-'}</div>
            <div>Bus: ${item.bus_info || '-'}</div>
        </div>
    `).join('');
    syncSystemCanForm();
}

function renderVendorMaintenance() {
    const statusCard = document.getElementById('vendorToolStatus');
    const recordsCard = document.getElementById('vendorMaintenanceRecords');
    if (!statusCard || !recordsCard) {
        return;
    }

    const dmtool = state.vendorToolStatus?.dmtool;
    if (!dmtool) {
        statusCard.className = 'summary-grid empty-state';
        statusCard.textContent = '尚未检测 DMTool';
    } else {
        statusCard.className = 'summary-grid';
        statusCard.innerHTML = [
            ['文件', dmtool.exists ? 'FOUND' : 'MISSING'],
            ['权限', dmtool.executable ? 'EXECUTABLE' : 'NO EXEC'],
            ['模式', '人工维护记录'],
            ['自动校准', dmtool.automatic_calibration_supported ? 'YES' : 'NO']
        ].map(([label, value]) => `
            <div class="summary-card">
                <div class="status-label">${label}</div>
                <div class="status-value">${value}</div>
            </div>
        `).join('');
    }

    const records = state.vendorMaintenanceRecords || [];
    if (!records.length) {
        recordsCard.className = 'artifact-list empty-state';
        recordsCard.textContent = '尚无维护记录';
        return;
    }

    const stateLabel = {
        not_performed: '未执行',
        performed: '已执行',
        not_required: '不需要',
        failed: '失败',
        unknown: '未知'
    };
    recordsCard.className = 'artifact-list';
    recordsCard.innerHTML = records.slice(0, 5).map(record => `
        <div class="artifact-item">
            <strong>${escapeHtml(record.target_label || '-')}</strong>
            <div>阶段: ${escapeHtml(record.maintenance_stage || '-')}</div>
            <div>电机编码器: ${stateLabel[record.motor_encoder_calibration] || escapeHtml(record.motor_encoder_calibration || '-')}</div>
            <div>输出轴编码器: ${stateLabel[record.output_encoder_calibration] || escapeHtml(record.output_encoder_calibration || '-')}</div>
            <div>保存零点: ${stateLabel[record.zero_save] || escapeHtml(record.zero_save || '-')}</div>
            <div>操作员: ${escapeHtml(record.operator || '-')}</div>
            <div class="muted">${escapeHtml(record.recorded_at || '-')}</div>
        </div>
    `).join('');
}

function renderMeta() {
    document.getElementById('connectionPill').textContent = state.sessionId ? '已连接' : '未连接';
    document.getElementById('jobPill').textContent = state.currentJobId ? `任务 ${state.currentJobId}` : '未创建任务';
    document.getElementById('deviceState').textContent = state.sessionId ? 'connected' : 'disconnected';
    document.getElementById('jobState').textContent = state.currentJob?.job?.status || 'draft';
    document.getElementById('jobStep').textContent = state.currentJob?.job?.current_step || '-';
    renderConnectWorkflow();
    renderIdentifyWorkflow();
    updateAllButtonsState();
}

function renderLineInventory() {
    const summary = document.getElementById('lineInventorySummary');
    const list = document.getElementById('lineInventoryList');

    if (!state.lineInventory) {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '连接后可检测整条线路上的电机 ID';
        list.className = 'result-list compact-results empty-state';
        list.textContent = '尚未盘点';
        return;
    }

    const payload = state.lineInventory;
    summary.className = 'summary-grid';
    summary.innerHTML = [
        ['在线节点', payload.summary.total_detected],
        ['重复 ESC_ID', payload.summary.duplicate_esc_ids.length],
        ['已发现 ID', (payload.summary.detected_esc_ids || []).join(', ') || '-'],
        ['缺失 ID', (payload.summary.missing_ids || []).join(', ') || '-'],
        ['意外 ID', (payload.summary.unexpected_ids || []).join(', ') || '-']
    ].map(([label, value]) => `
        <div class="summary-card">
            <div class="status-label">${label}</div>
            <div class="status-value">${value}</div>
        </div>
    `).join('');

    if (!(payload.inventory || []).length) {
        list.className = 'result-list compact-results empty-state';
        list.textContent = '当前总线上未检测到电机 ID';
        return;
    }

    list.className = 'result-list compact-results';
    list.innerHTML = payload.inventory.map(item => `
        <div class="result-card ${item.matched_joint ? 'inventory-match' : 'inventory-unexpected'}">
            <strong>ESC_ID ${item.detected_esc_id ?? '-'}</strong>
            <div>MST_ID: ${item.detected_mst_id ?? '-'}</div>
            <div>匹配 Joint: ${item.matched_joint || '-'}</div>
            <div>OpenARM 官方型号: ${item.matched_motor_type || '-'}</div>
            <div>状态: ${item.status?.status || 'UNKNOWN'}</div>
        </div>
    `).join('');
    renderDiagnosticJointOptions();
}

function renderJointDiagnostic() {
    const summary = document.getElementById('jointDiagnosticSummary');
    const detail = document.getElementById('jointDiagnosticDetail');

    if (!state.jointDiagnostic) {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '盘点后可按关节执行只读诊断或安全动态测试';
        detail.className = 'result-list compact-results empty-state';
        detail.textContent = '尚未执行单关节测试';
        return;
    }

    const payload = state.jointDiagnostic;
    summary.className = 'summary-grid';
    summary.innerHTML = [
        ['关节', payload.joint_name || '-'],
        ['测试类型', payload.test_type || '-'],
        ['在线', payload.present ? 'YES' : 'NO'],
        ['结论', payload.passed ? 'PASS' : 'CHECK'],
        ['问题数', (payload.issues || []).length],
    ].map(([label, value]) => `
        <div class="summary-card">
            <div class="status-label">${label}</div>
            <div class="status-value">${value}</div>
        </div>
    `).join('');

    const sections = [];
    if (payload.params) {
        sections.push(`
            <div class="result-card">
                <strong>参数快照</strong>
                <div>ESC/MST: ${payload.params.ESC_ID ?? '-'} / ${payload.params.MST_ID ?? '-'}</div>
                <div>CTRL_MODE: ${payload.params.CTRL_MODE ?? '-'}</div>
                <div>TIMEOUT: ${payload.params.TIMEOUT ?? '-'}</div>
                <div>can_br: ${payload.params.can_br ?? '-'}</div>
                <div>Issues: ${(payload.issues || []).join(', ') || '-'}</div>
            </div>
        `);
    }
    if (payload.param_results?.length) {
        sections.push(...payload.param_results.map(item => `
            <div class="result-card ${item.ok ? 'inventory-match' : 'inventory-unexpected'}">
                <strong>${item.field}</strong>
                <div>结果: ${item.ok ? 'OK' : 'FAIL'}</div>
                <div>数值: ${item.value ?? '-'}</div>
                <div>耗时: ${item.elapsed_ms} ms</div>
                <div>错误: ${item.error || '-'}</div>
            </div>
        `));
    }
    if (payload.after_enable || payload.after_disable) {
        sections.push(`
            <div class="result-card">
                <strong>链路结果</strong>
                <div>Enable 后: ${payload.after_enable?.status || '-'}</div>
                <div>Disable 后: ${payload.after_disable?.status || '-'}</div>
                <div>Issues: ${(payload.issues || []).join(', ') || '-'}</div>
            </div>
        `);
    }
    if (payload.measurements) {
        sections.push(`
            <div class="result-card">
                <strong>微动结果</strong>
                <div>起点: ${payload.measurements.start_q ?? payload.measurements.start?.position ?? '-'}</div>
                <div>目标: ${payload.measurements.target_q ?? '-'}</div>
                <div>峰值偏移: ${payload.measurements.peak_delta ?? '-'}</div>
                <div>最终偏移: ${payload.measurements.final_delta ?? '-'}</div>
                <div>驻留: ${payload.measurements.dwell_ms ?? '-'} ms</div>
                <div>Issues: ${(payload.issues || []).join(', ') || '-'}</div>
            </div>
        `);
    }

    detail.className = 'result-list compact-results';
    detail.innerHTML = sections.join('');
}

function renderScanResults() {
    const container = document.getElementById('scanResults');
    const summary = document.getElementById('scanSummary');
    const matrix = document.getElementById('scanMatrix');
    const checklist = document.getElementById('shipmentChecklist');
    if (!state.scanResults) {
        container.className = 'result-list empty-state';
        container.textContent = '尚未扫描';
        summary.className = 'summary-grid empty-state';
        summary.textContent = '尚未生成扫描摘要';
        matrix.className = 'result-list empty-state';
        matrix.textContent = '整臂扫描后显示参数一致性矩阵';
        checklist.className = 'result-list empty-state';
        checklist.textContent = '整臂扫描后显示出厂前检查清单';
        return;
    }

    const candidates = state.scanResults.candidates || [];
    const summaryPayload = state.scanResults.summary;
    if (summaryPayload) {
        summary.className = 'summary-grid';
        const items = state.scanResults.scan_mode === 'can2_scan_inventory_and_profile_match'
            || state.scanResults.scan_mode === 'can2_acceptance_preview'
            ? [
                ['应有关节', summaryPayload.total_expected],
                ['在线关节', summaryPayload.total_present],
                ['通过关节', summaryPayload.total_comm_ok],
                ['缺失', summaryPayload.total_missing],
                ['不一致', summaryPayload.total_mismatches],
                ['意外节点', summaryPayload.total_unexpected],
                ...(summaryPayload.command_test_total !== undefined ? [
                    ['命令测试模式', summaryPayload.command_check_mode === 'safe_readonly' ? '只读安全模式' : '已启用'],
                    ['命令测试通过', `${summaryPayload.command_test_passed}/${summaryPayload.command_test_total}`],
                    ['命令测试失败', summaryPayload.command_test_failed]
                ] : []),
                ...(summaryPayload.stability ? [
                    ['复扫次数', summaryPayload.stability.repeat_count],
                    ['稳定关节', summaryPayload.stability.stable_joint_count],
                    ['波动关节', summaryPayload.stability.flaky_joint_count]
                ] : []),
                ...(summaryPayload.release_decision ? [['放行结论', summaryPayload.release_decision]] : [])
            ]
            : [
                ['发现对象', summaryPayload.detected],
                ['冲突对象', summaryPayload.conflicts],
                ['扫描结论', summaryPayload.passed ? 'PASS' : 'CHECK']
            ];
        summary.innerHTML = items.map(([label, value]) => `
            <div class="summary-card">
                <div class="status-label">${label}</div>
                <div class="status-value">${value}</div>
            </div>
        `).join('');
    } else {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '尚未生成扫描摘要';
    }

    if (!candidates.length) {
        container.className = 'result-list empty-state';
        container.textContent = '未发现候选对象';
        matrix.className = 'result-list empty-state';
        matrix.textContent = '当前没有可展示的参数一致性矩阵';
        checklist.className = 'result-list empty-state';
        checklist.textContent = '当前没有可展示的出厂前检查清单';
        return;
    }

    container.className = state.scanResults.scan_mode === 'can2_scan_inventory_and_profile_match' || state.scanResults.scan_mode === 'can2_acceptance_preview' ? 'result-list matrix-grid' : 'result-list';
    container.innerHTML = candidates.map(item => {
        if (item.joint_name) {
            return `
                <div class="result-card matrix-card ${item.comm_ok ? 'pass' : 'fail'}">
                    <strong>${item.joint_name}</strong>
                    <div>OpenARM 官方型号: ${item.expected?.motor_type ?? '-'}</div>
                    <div>Present: ${item.present ? 'YES' : 'NO'}</div>
                    <div>Comm OK: ${item.comm_ok ? 'YES' : 'NO'}</div>
                    <div>Expected ESC/MST: ${item.expected?.target_esc_id ?? '-'} / ${item.expected?.target_mst_id ?? '-'}</div>
                    <div>Actual ESC/MST: ${item.params?.ESC_ID ?? '-'} / ${item.params?.MST_ID ?? '-'}</div>
                    <div>can_br: ${item.params?.can_br ?? '-'}</div>
                    <div>Status: ${item.status?.status || 'UNKNOWN'}</div>
                    <div>Issues: ${(item.issues || []).length ? item.issues.join(', ') : '-'}</div>
                    <div>命令测试: ${item.command_check ? (item.command_check.passed ? 'PASS' : 'FAIL') : '已禁用(安全模式)'}</div>
                    <div>稳定性: ${item.stability?.stable ? '稳定' : item.stability ? '波动' : '-'}</div>
                    <div>波动字段: ${(item.stability?.parameter_changed_fields || []).join(', ') || '-'}</div>
                    <div class="button-row compact-button-row">
                        ${item.present ? `<button class="btn btn-secondary slim" data-arm-config-joint="${item.joint_name}" data-arm-config-id="${item.params?.ESC_ID ?? item.expected?.target_esc_id}">改ID/配置</button>` : ''}
                        ${item.present ? `<button class="btn btn-secondary slim" data-arm-param-joint="${item.joint_name}" data-arm-param-id="${item.params?.ESC_ID ?? item.expected?.target_esc_id}">参数配置</button>` : ''}
                    </div>
                </div>
            `;
        }
        return `
            <div class="result-card">
                <strong>候选电机</strong>
                <div>Current ID: ${item.current_id}</div>
                <div>ESC_ID: ${item.detected_esc_id ?? '-'}</div>
                <div>MST_ID: ${item.detected_mst_id ?? '-'}</div>
                <div>Status: ${item.status?.status || 'UNKNOWN'}</div>
                <div>CTRL_MODE: ${item.params?.CTRL_MODE ?? '-'}</div>
            </div>
        `;
    }).join('');

    const armMatrixMode = state.scanResults.scan_mode === 'can2_scan_inventory_and_profile_match' || state.scanResults.scan_mode === 'can2_acceptance_preview';
    if (!armMatrixMode) {
        matrix.className = 'result-list hidden';
        matrix.textContent = '';
        checklist.className = 'result-list hidden';
        checklist.textContent = '';
        return;
    }
    matrix.className = 'result-list';
    const matrixHeaders = ARM_MATRIX_FIELDS.map(field => `<th>${field}</th>`).join('');
    const matrixRows = candidates.filter(item => item.joint_name).map(item => {
        const fieldMap = {};
        (item.consistency_matrix || []).forEach(row => {
            fieldMap[row.field] = row;
        });
        const renderCell = field => {
            const row = fieldMap[field];
            if (!row) {
                return '<td class="matrix-cell-neutral">-</td>';
            }
            const value = `${row.actual ?? '-'} / ${row.expected ?? '-'}`;
            const css = row.matches === true ? 'matrix-cell-pass' : row.matches === false ? 'matrix-cell-fail' : 'matrix-cell-neutral';
            return `<td class="${css}">${value}</td>`;
        };
        return `
            <tr>
                <td>${item.joint_name}</td>
                <td>${item.expected?.motor_type ?? '-'}</td>
                ${ARM_MATRIX_FIELDS.map(renderCell).join('')}
                <td>${item.stability?.stable ? '稳定' : item.stability ? '波动' : '-'}</td>
            </tr>
        `;
    }).join('');
    matrix.innerHTML = `
        <div class="matrix-table-wrap">
        <table class="matrix-table">
            <thead>
                <tr>
                    <th>Joint</th>
                    <th>型号</th>
                    ${matrixHeaders}
                    <th>稳定性</th>
                </tr>
            </thead>
            <tbody>${matrixRows}</tbody>
        </table>
        </div>
    `;

    const shipmentChecklist = state.scanResults.summary?.shipment_checklist;
    if (!shipmentChecklist) {
        checklist.className = 'result-list empty-state';
        checklist.textContent = '当前扫描没有生成出厂前检查清单';
    } else {
        const automated = shipmentChecklist.automated || [];
        const manual = shipmentChecklist.manual || [];
        checklist.className = 'result-list';
        checklist.innerHTML = [
            ...automated.map(item => `
                <div class="result-card checklist-card ${item.status}">
                    <strong>自动检查 · ${item.label}</strong>
                    <div>状态: ${item.status.toUpperCase()}</div>
                    <div class="muted">${item.detail}</div>
                </div>
            `),
            ...manual.map(item => `
                <div class="result-card checklist-card ${item.status}">
                    <strong>${item.status === 'customer_scope' ? '客户侧' : '人工复核'} · ${item.label}</strong>
                    <div>状态: ${item.status}</div>
                    <div class="muted">${item.detail}</div>
                </div>
            `)
        ].join('');
    }

    container.querySelectorAll('[data-arm-config-joint]').forEach(button => {
        button.addEventListener('click', () => {
            handleAction(() => launchJointWorkflow(button.dataset.armConfigJoint, Number(button.dataset.armConfigId), 'single_commissioning'));
        });
    });
    container.querySelectorAll('[data-arm-param-joint]').forEach(button => {
        button.addEventListener('click', () => {
            handleAction(() => launchJointWorkflow(button.dataset.armParamJoint, Number(button.dataset.armParamId), 'single_param_config'));
        });
    });
}

function renderArmRuntimeCheck(payload) {
    const container = document.getElementById('armRuntimeCheck');
    if (!container) {
        return;
    }
    if (!payload) {
        container.className = 'result-list empty-state';
        container.textContent = '状态复核或安全使能检查后显示运行结果';
        return;
    }
    const summary = payload.summary || {};
    const headerItems = [
        ['Profile', payload.profile_id],
        ['在线', `${summary.total_present ?? 0}/${summary.total_expected ?? 0}`],
        ['通过', summary.passed ?? 0],
        ['失败', summary.failed ?? 0],
        ['控制保活', payload.control_keepalive_sent ? '零力矩' : '未发送'],
        ['动作命令', payload.motion_command_sent ? '已发送' : '未发送'],
    ];
    const rows = (payload.results || []).map(item => {
        const status = item.status || item.after_disable || item.after_enable || item.pre_status || {};
        const issues = (item.issues || []).join(', ') || '-';
        const metadataNotes = (item.metadata_notes || []).join(', ') || '-';
        const timeoutLine = payload.timeout_standardization || payload.target_timeout !== undefined
            ? `TIMEOUT: ${item.before ?? '-'} -> ${item.after_write ?? '-'} -> ${item.after_save ?? '-'}（目标 ${item.target_timeout ?? '-'}）`
            : `TIMEOUT: ${item.timeout ?? '-'}`;
        return `
            <div class="result-card ${item.passed ? 'pass' : 'fail'}">
                <strong>${item.joint_name}</strong>
                <div>ESC/MST: ${item.esc_id}/${item.mst_id}</div>
                <div>状态: ${status.status || '-'}</div>
                <div>${timeoutLine}</div>
                <div>Enable: ${item.enable_ok === undefined ? '-' : item.enable_ok}</div>
                <div>Disable: ${item.disable_ok === undefined ? '-' : item.disable_ok}</div>
                <div>Issues: ${issues}</div>
                <div>元数据备注: ${metadataNotes}</div>
            </div>
        `;
    }).join('');
    container.className = 'result-list compact-results';
    container.innerHTML = `
        <div class="summary-grid">
            ${headerItems.map(([label, value]) => `
                <div class="summary-card">
                    <div class="status-label">${label}</div>
                    <div class="status-value">${value}</div>
                </div>
            `).join('')}
        </div>
        ${rows}
    `;
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderArmRuntimeBusy(message) {
    const container = document.getElementById('armRuntimeCheck');
    if (!container) {
        return;
    }
    container.className = 'result-list empty-state';
    container.textContent = message;
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function launchJointWorkflow(jointName, currentEscId, targetJobType) {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    document.getElementById('jobType').value = targetJobType;
    document.getElementById('expertMode').checked = true;
    document.getElementById('manualCurrentId').value = currentEscId;
    document.getElementById('targetJoint').value = jointName;
    renderScopeAssumptions();
    renderSteps();
    renderExecuteMode();

    const profileId = document.getElementById('profileSelect').value;
    await api('/api/device/scan', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            job_type: targetJobType,
            profile_id: profileId,
            current_id: currentEscId,
            expert_mode: true
        })
    });

    const payload = await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({
            job_type: targetJobType,
            device_session_id: state.sessionId,
            profile_id: profileId,
            target_joint: jointName,
            expert_mode: true
        })
    });
    state.currentJobId = payload.job_id;
    await api(`/api/jobs/${state.currentJobId}/apply-profile`, {
        method: 'POST',
        body: JSON.stringify({
            target_joint: jointName,
            profile_id: profileId,
            overrides: buildOverrides()
        })
    });
    addLog(`已从整臂扫描切换到 ${jointName} 的${targetJobType === 'single_param_config' ? '参数配置' : '单电机配置'}流程`, 'success', 'arm_to_single');
    await refreshCurrentJob();
    switchPrimaryTab('motorWorkbenchTab');
}

function renderComparison() {
    const comparisonCard = document.getElementById('comparisonCard');
    const targetConfigCard = document.getElementById('targetConfigCard');
    const target = state.currentJob?.motors?.commissioned_motor?.target;
    const current = state.currentJob?.motors?.commissioned_motor?.current;
    const checked = state.currentJob?.motors?.checked_motor;
    const jobType = document.getElementById('jobType').value;

    if (isArmVerification(jobType)) {
        comparisonCard.className = 'comparison-card empty-state';
        comparisonCard.textContent = '整臂任务请查看左侧扫描结果与摘要卡片。';
        targetConfigCard.className = 'kv-list empty-state';
        targetConfigCard.textContent = '整臂任务不使用单电机目标参数。';
        return;
    }

    if (isSingleCommCheck(jobType) && checked) {
        comparisonCard.className = 'comparison-card kv-list';
        comparisonCard.innerHTML = [
            ['ESC_ID', checked.params?.ESC_ID ?? checked.candidate?.detected_esc_id ?? '-'],
            ['MST_ID', checked.params?.MST_ID ?? checked.candidate?.detected_mst_id ?? '-'],
            ['CTRL_MODE', checked.params?.CTRL_MODE ?? '-'],
            ['can_br', checked.params?.can_br ?? '-'],
            ['Status', checked.status?.status ?? '-'],
            ['Issues', (checked.issues || []).join(', ') || '-']
        ].map(([label, value]) => kvRow(label, value)).join('');
        targetConfigCard.className = 'kv-list empty-state';
        targetConfigCard.textContent = '通信校验任务不需要目标 Joint';
        return;
    }

    if (!target || !current) {
        comparisonCard.className = 'comparison-card empty-state';
        comparisonCard.textContent = '创建任务后显示';
        targetConfigCard.className = 'kv-list empty-state';
        targetConfigCard.textContent = '尚未选择 Joint';
        return;
    }

    comparisonCard.className = 'comparison-card kv-list';
    comparisonCard.innerHTML = [
        ['OpenARM 官方型号', target.motor_type],
        ['当前 ESC_ID', current.params?.ESC_ID ?? current.candidate?.detected_esc_id ?? '-'],
        ['当前 MST_ID', current.params?.MST_ID ?? current.candidate?.detected_mst_id ?? '-'],
        ['当前 CTRL_MODE', current.params?.CTRL_MODE ?? '-'],
        ['目标 Joint', target.joint_name],
        ['目标 ESC_ID', target.target_esc_id],
        ['目标 MST_ID', target.target_mst_id],
        ['目标 CTRL_MODE', target.target_ctrl_mode],
        [target.timeout_write_policy ? '记录 TIMEOUT（单电机只读）' : '目标 TIMEOUT', target.target_timeout ?? '-'],
        ['目标 can_br', target.target_can_br],
        ['目标 KT_Value', target.target_kt_value ?? '-'],
        ['目标 Gr', target.target_gr ?? '-'],
        ['目标 PMAX', target.target_pmax ?? '-'],
        ['目标 VMAX', target.target_vmax ?? '-'],
        ['目标 TMAX', target.target_tmax ?? '-']
    ].map(([label, value]) => kvRow(label, value)).join('');

    targetConfigCard.className = 'kv-list';
    targetConfigCard.innerHTML = Object.entries(target).map(([key, value]) => kvRow(formatTargetConfigLabel(key), value)).join('');
    hydrateExpertOverrideInputs(target);
}

function hydrateExpertOverrideInputs(target) {
    document.getElementById('overrideEscId').value = target.target_esc_id;
    document.getElementById('overrideMstId').value = target.target_mst_id;
    document.getElementById('overrideCtrlMode').value = target.target_ctrl_mode;
    document.getElementById('overrideTimeout').value = target.target_timeout;
    document.getElementById('overrideCanBr').value = target.target_can_br;
    document.getElementById('overrideKtValue').value = target.target_kt_value ?? '';
    document.getElementById('overrideGr').value = target.target_gr ?? '';
    document.getElementById('overridePmax').value = target.target_pmax ?? '';
    document.getElementById('overrideVmax').value = target.target_vmax ?? '';
    document.getElementById('overrideTmax').value = target.target_tmax ?? '';
}

function parseNumericInput(id, floatMode = false) {
    const raw = document.getElementById(id).value;
    if (raw === '' || raw === null || raw === undefined) {
        return null;
    }
    return floatMode ? Number.parseFloat(raw) : Number(raw);
}

function collectTargetConfig() {
    const target = { ...(state.currentJob?.motors?.commissioned_motor?.target || {}) };
    const jobType = document.getElementById('jobType').value;
    const expertMode = document.getElementById('expertMode').checked;
    const canEdit = isSingleParamConfig(jobType) || (expertMode && isSingleCommissioning(jobType));
    if (!canEdit) {
        return target;
    }

    target.target_esc_id = parseNumericInput('overrideEscId');
    target.target_mst_id = parseNumericInput('overrideMstId');
    target.target_ctrl_mode = document.getElementById('overrideCtrlMode').value;
    target.target_timeout = parseNumericInput('overrideTimeout');
    target.target_can_br = parseNumericInput('overrideCanBr');
    target.target_kt_value = parseNumericInput('overrideKtValue', true);
    target.target_gr = parseNumericInput('overrideGr', true);
    target.target_pmax = parseNumericInput('overridePmax', true);
    target.target_vmax = parseNumericInput('overrideVmax', true);
    target.target_tmax = parseNumericInput('overrideTmax', true);
    if (!isSingleParamConfig(jobType)) {
        delete target.target_kt_value;
        delete target.target_gr;
        delete target.target_pmax;
        delete target.target_vmax;
        delete target.target_tmax;
    }
    return target;
}

function workflowActionDescriptor() {
    const jobType = document.getElementById('jobType').value;
    const allowed = state.currentJob?.allowed_actions || [];

    if (!state.sessionId) {
        return {
            id: 'connect',
            title: '先连接设备',
            detail: '当前还没有建立设备会话，请先在连接页完成设备连接。',
            buttonText: '前往连接',
            tone: 'blocked',
            tab: 'connectTab',
            subtab: null
        };
    }

    if (!state.currentJobId || !state.currentJob) {
        return {
            id: 'create_job',
            title: '先创建任务',
            detail: '请先在左侧任务卡选择任务类型、Transport 和 Profile，然后创建任务。',
            buttonText: '前往任务配置',
            tone: 'blocked',
            tab: preferredWorkbenchTab(jobType),
            subtab: null
        };
    }

    if (allowed.includes('write_params')) {
        return {
            id: 'write_params',
            title: isSingleParamConfig(jobType) ? '步骤 1：写入配置参数' : '步骤 1：写入参数',
            detail: isSingleParamConfig(jobType)
                ? '将编辑后的 CTRL_MODE、TIMEOUT、can_br 与关键电机参数写入当前电机。'
                : '将目标 ESC_ID、MST_ID、CTRL_MODE 和 can_br 写入当前电机；TIMEOUT 仅记录不写入。',
            buttonText: isSingleParamConfig(jobType) ? '写入配置参数' : '写入参数',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'paramPanel'
        };
    }
    if (allowed.includes('verify_params')) {
        return {
            id: 'verify_params',
            title: '步骤 2：回读校验',
            detail: '读取电机参数并与目标配置逐项比对，确认写入已经生效。',
            buttonText: '回读校验',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'savePanel'
        };
    }
    if (allowed.includes('save_flash')) {
        return {
            id: 'save_flash',
            title: '步骤 3：保存到 Flash',
            detail: isSingleParamConfig(jobType)
                ? '完成回读后，将新参数固化到电机 Flash，并准备生成配置结果。'
                : '完成回读后，将参数固化到电机 Flash，断电后仍然保留。',
            buttonText: '保存 Flash',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'savePanel'
        };
    }
    if (isSingleParamConfig(jobType) && allowed.includes('test')) {
        return {
            id: 'test',
            title: '步骤 4：完成参数配置',
            detail: '当前参数已经保存成功，可以结束本次配置任务并生成报告与问题清单。',
            buttonText: '完成配置',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'testPanel'
        };
    }
    if (isSingleCommissioning(jobType) && allowed.includes('test') && state.currentJob?.job?.status === 'params_saved') {
        return {
            id: 'test',
            title: '步骤 4：保存后只读复核',
            detail: allowed.includes('zero')
                ? '建议断电重上电后回读参数并完成任务；专家任务如有夹具基准，也可先执行零位再做动作测试。'
                : '建议断电重上电后回读参数与状态，确认 Flash 已生效并生成报告；不零位、不发送动作帧。',
            buttonText: '复核并完成',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'testPanel'
        };
    }
    if (allowed.includes('zero')) {
        return {
            id: 'zero',
            title: '步骤 4：执行零位（专家）',
            detail: '仅限有文档化夹具机械基准时使用；装配前电机不应保存整臂零点。',
            buttonText: '执行零位',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'zeroPanel'
        };
    }
    if (allowed.includes('test')) {
        return {
            id: 'test',
            title: '步骤 5：执行动作测试',
            detail: '进行安全小幅 MIT 测试，确认电机可控且状态正常。',
            buttonText: '执行测试',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'testPanel'
        };
    }
    if (allowed.includes('run_comm_check')) {
        return {
            id: 'run_comm_check',
            title: '执行通信校验',
            detail: '读取该电机的通信参数和状态，不发送动作控制帧。',
            buttonText: '开始校验',
            tone: 'ready',
            tab: 'motorWorkbenchTab',
            subtab: 'testPanel'
        };
    }
    if (allowed.includes('run_arm_acceptance')) {
        return {
            id: 'run_arm_acceptance',
            title: '执行整臂验收',
            detail: '遍历总线、核对 J1~J8 配置，并给出 PASS / HOLD 放行结论。',
            buttonText: '开始验收',
            tone: 'ready',
            tab: 'staticAcceptanceTab',
            subtab: 'testPanel'
        };
    }
    if (allowed.includes('run_arm_scan')) {
        return {
            id: 'run_arm_scan',
            title: '执行整臂扫描',
            detail: '按 profile 扫描整条机械臂上的电机，检查缺失、错配和异常节点。',
            buttonText: '开始扫描',
            tone: 'ready',
            tab: 'staticAcceptanceTab',
            subtab: 'testPanel'
        };
    }

    if (state.currentJob?.job?.status === 'passed') {
        return {
            id: 'report',
            title: '流程已完成',
            detail: '当前任务已经通过，可以切到报告页查看结果和工件。',
            buttonText: '查看报告',
            tone: 'done',
            tab: 'reportTab',
            subtab: null
        };
    }

    if (state.currentJob?.job?.status === 'failed') {
        return {
            id: 'failed',
            title: '流程已中断',
            detail: state.currentJob?.job?.failure_reason || '当前任务失败，请查看右侧事件和报告页定位原因。',
            buttonText: '查看报告',
            tone: 'blocked',
            tab: 'reportTab',
            subtab: null
        };
    }

    return {
        id: 'waiting',
        title: isArmAcceptance(jobType) ? '等待进入验收阶段' : '等待下一步条件满足',
        detail: '当前还没有可执行的主流程命令，请先完成前置步骤或刷新任务状态。',
        buttonText: '保持等待',
        tone: 'blocked',
        tab: preferredWorkbenchTab(jobType),
        subtab: visibleExecuteSubtabs(jobType)[0]
    };
}

function renderWorkflowCommand() {
    const descriptor = workflowActionDescriptor();
    const title = document.getElementById('workflowActionTitle');
    const detail = document.getElementById('workflowActionDetail');
    const stateNode = document.getElementById('workflowActionState');
    const button = document.getElementById('workflowActionBtn');

    title.textContent = descriptor.title;
    detail.textContent = descriptor.detail;
    stateNode.textContent = descriptor.tone === 'ready' ? '可执行' : descriptor.tone === 'done' ? '已完成' : '待处理';
    stateNode.className = `action-status ${descriptor.tone}`;
    button.textContent = descriptor.buttonText;
    button.disabled = descriptor.id === 'waiting';

    if (descriptor.subtab) {
        switchExecuteTab(descriptor.subtab);
    }
}

function setWorkflowCard(prefix, descriptor) {
    document.getElementById(`${prefix}WorkflowActionTitle`).textContent = descriptor.title;
    document.getElementById(`${prefix}WorkflowActionDetail`).textContent = descriptor.detail;
    const stateNode = document.getElementById(`${prefix}WorkflowActionState`);
    stateNode.textContent = descriptor.tone === 'ready' ? '可执行' : descriptor.tone === 'done' ? '已完成' : '待处理';
    stateNode.className = `action-status ${descriptor.tone}`;
    const button = document.getElementById(`${prefix}WorkflowActionBtn`);
    button.textContent = descriptor.buttonText;
    button.disabled = Boolean(descriptor.disabled);
}

function selectedSocketcanInterface() {
    const interfaces = state.interfaceStatus?.interfaces || [];
    const channel = document.getElementById('socketcanChannel').value.trim();
    const systemCanName = document.getElementById('systemCanName').value;
    return interfaces.find(item => item.name === channel)
        || interfaces.find(item => item.name === systemCanName)
        || interfaces[0]
        || null;
}

function connectWorkflowDescriptor() {
    const transport = document.getElementById('transportType').value;

    if (transport === 'serial_bridge') {
        if (state.sessionId) {
            return {
                id: 'go_identify',
                title: '串口设备已连接',
                detail: '连接已经建立，可以前往对应工站进行单电机配置、参数诊断或整臂扫描。',
                buttonText: '前往工站',
                tone: 'done'
            };
        }
        return {
            id: 'connect_device',
            title: '连接串口设备',
            detail: '检查串口号和波特率后建立设备连接。',
            buttonText: '连接设备',
            tone: 'ready'
        };
    }

    const interfaces = state.interfaceStatus?.interfaces || [];
    const iface = selectedSocketcanInterface();

    if (!interfaces.length) {
        return {
            id: 'refresh_interfaces',
            title: '检测 USB-CAN 接口',
            detail: '先刷新接口，确认 gs_usb 适配器已经生成 can0 / can1。',
            buttonText: '刷新接口',
            tone: 'ready'
        };
    }

    if (!iface?.bitrate) {
        return {
            id: 'configure_can',
            title: '配置 CAN 通道',
            detail: `先为 ${iface?.name || '当前接口'} 设置 CAN 模式和 bitrate，再建立连接。`,
            buttonText: '配置通道',
            tone: 'ready'
        };
    }

    if (!state.sessionId && iface.state !== 'UP') {
        return {
            id: 'up_can',
            title: '拉起 CAN 通道',
            detail: `${iface.name} 当前处于 ${iface.state || 'DOWN'}，先启动总线接口。`,
            buttonText: `启动 ${iface.name}`,
            tone: 'ready'
        };
    }

    if (!state.sessionId) {
        return {
            id: 'connect_device',
            title: '连接 SocketCAN 设备',
            detail: `${iface.name} 已就绪，可以建立设备会话。`,
            buttonText: '连接设备',
            tone: 'ready'
        };
    }

    return {
        id: 'go_identify',
        title: '设备已连接',
        detail: '连接已经完成，下一步可以去电机工站或机械臂工站执行盘点、扫描与配置。',
        buttonText: '前往工站',
        tone: 'done'
    };
}

function identifyWorkflowDescriptor() {
    const jobType = document.getElementById('jobType').value;
    const allowed = state.currentJob?.allowed_actions || [];

    if (!state.sessionId) {
        return {
            id: 'go_connect',
            title: '请先连接设备',
            detail: '当前还没有设备会话，先在连接页建立串口或 SocketCAN 连接。',
            buttonText: '前往连接',
            tone: 'blocked'
        };
    }

    if (!state.currentJobId || !state.currentJob) {
        return {
            id: 'go_task',
            title: '请先创建任务',
            detail: '先在左侧任务卡选择任务类型、Profile 和目标 Joint，再回来开始测试。',
            buttonText: '前往任务配置',
            tone: 'blocked'
        };
    }

    if (!state.scanResults) {
        return {
            id: 'scan_device',
            title: isArmAcceptance(jobType)
                ? '开始验收预扫描'
                : isArmVerification(jobType)
                    ? '开始整臂扫描'
                    : '开始单电机识别',
            detail: isArmVerification(jobType)
                ? '按当前任务类型执行总线扫描、参数读取和结果预览。'
                : '先识别当前电机，再进入执行页进行后续操作。',
            buttonText: isArmAcceptance(jobType) ? '开始验收预扫' : '开始扫描',
            tone: 'ready'
        };
    }

    if (isArmAcceptance(jobType) && allowed.includes('run_arm_acceptance')) {
        return {
            id: 'run_arm_acceptance',
            title: '执行整臂验收',
            detail: '预扫描已经完成，现在执行正式验收并生成 PASS / HOLD 放行结论。',
            buttonText: '开始验收',
            tone: 'ready'
        };
    }

    if (isArmVerification(jobType) && allowed.includes('run_arm_scan')) {
        return {
            id: 'run_arm_scan',
            title: '执行整臂扫描',
            detail: '预扫描已经完成，现在执行正式扫描并写入报告与问题清单。',
            buttonText: '开始正式扫描',
            tone: 'ready'
        };
    }

    return {
        id: 'go_execute',
        title: '测试准备已完成',
        detail: isArmAcceptance(jobType)
            ? '预扫描结果已经生成，可继续在机械臂工站内发起整臂验收。'
            : isArmVerification(jobType)
                ? '扫描结果已经生成，可继续在机械臂工站内查看结果、问题监测和交付流程。'
                : '当前电机已识别，继续在电机工站内按步骤写参、保存、零位和测试。',
        buttonText: '继续当前工站',
        tone: 'done'
    };
}

function renderConnectWorkflow() {
    setWorkflowCard('connect', connectWorkflowDescriptor());
}

function renderIdentifyWorkflow() {
    setWorkflowCard('identify', identifyWorkflowDescriptor());
}

function openTestingArea(area = 'scan') {
    if (area === 'joint') {
        switchPrimaryTab('motorWorkbenchTab');
        return;
    }
    switchPrimaryTab(area === 'factory' ? 'officialDynamicTab' : 'staticAcceptanceTab');
    if (area === 'issues') {
        switchTestingSubtab('issueWorkbenchPanel');
        return;
    }
    if (area === 'factory') {
        switchTestingSubtab('factoryWorkbenchPanel');
        return;
    }
    switchTestingSubtab('scanWorkbenchPanel');
}

function renderActionStates() {
    const allowed = state.currentJob?.allowed_actions || [];
    const jobType = document.getElementById('jobType').value;
    const status = state.currentJob?.job?.status || 'draft';
    const currentStep = state.currentJob?.job?.current_step || 'draft';

    const controls = [
        {
            button: 'writeParamsBtn',
            state: 'writeParamsState',
            allowedAction: 'write_params',
            relevant: isSingleParameterTask(jobType),
            doneStatuses: ['params_written', 'params_verified', 'params_saved', 'zeroed', 'tested', 'passed'],
            readyText: '当前步骤可执行',
            waitingText: isSingleParamConfig(jobType) ? '等待进入参数写入阶段' : '等待进入参数写入阶段'
        },
        {
            button: 'verifyParamsBtn',
            state: 'verifyParamsState',
            allowedAction: 'verify_params',
            relevant: isSingleParameterTask(jobType),
            doneStatuses: ['params_verified', 'params_saved', 'zeroed', 'tested', 'passed'],
            readyText: '当前步骤可执行',
            waitingText: '等待参数写入完成'
        },
        {
            button: 'saveFlashBtn',
            state: 'saveFlashState',
            allowedAction: 'save_flash',
            relevant: isSingleParameterTask(jobType),
            doneStatuses: ['params_saved', 'zeroed', 'tested', 'passed'],
            readyText: '当前步骤可执行',
            waitingText: '等待回读校验通过'
        },
        {
            button: 'zeroBtn',
            state: 'zeroState',
            allowedAction: 'zero',
            relevant: isSingleCommissioning(jobType) && singleCommissioningExpert(),
            doneStatuses: ['zeroed'],
            readyText: '当前步骤可执行',
            waitingText: '等待参数保存完成'
        },
        {
            button: 'testBtn',
            state: 'testState',
            allowedAction: isSingleCommCheck(jobType)
                ? 'run_comm_check'
                : isArmAcceptance(jobType)
                    ? 'run_arm_acceptance'
                    : isArmVerification(jobType)
                        ? 'run_arm_scan'
                        : 'test',
            relevant: true,
            doneStatuses: ['tested', 'passed', 'reported'],
            readyText: '当前步骤可执行',
            waitingText: isArmAcceptance(jobType)
                ? '等待进入整臂验收阶段'
                : isArmVerification(jobType)
                    ? '等待进入整臂扫描阶段'
                    : isSingleCommCheck(jobType)
                        ? '等待进入通信校验阶段'
                        : isSingleParamConfig(jobType) || isSingleCommissioning(jobType)
                            ? '等待参数保存完成'
                        : '等待进入测试阶段'
        }
    ];

    controls.forEach(item => {
        const button = document.getElementById(item.button);
        if (!item.relevant) {
            button.classList.add('hidden');
            updateActionStatus(item.state, '当前任务不包含此命令', 'blocked');
            return;
        }
        const isAllowed = allowed.includes(item.allowedAction);
        const isDone = item.doneStatuses.includes(status) || item.doneStatuses.includes(currentStep);
        button.classList.toggle('hidden', !isAllowed);
        button.disabled = false;
        if (isAllowed) {
            updateActionStatus(item.state, item.readyText, 'ready');
        } else if (isDone) {
            updateActionStatus(item.state, '本阶段已完成', 'done');
        } else {
            updateActionStatus(item.state, item.waitingText, 'blocked');
        }
    });

    renderWorkflowCommand();
    updateAllButtonsState();
}

function updateAllButtonsState() {
    const allowed = state.currentJob?.allowed_actions || [];
    const hasSession = Boolean(state.sessionId);
    const hasJob = Boolean(state.currentJobId && state.currentJob);
    const jobType = document.getElementById('jobType')?.value || '';
    const requiresSession = '需要先连接设备';
    const requiresJob = hasSession ? '需要先创建任务' : requiresSession;
    const stepBlocked = '当前任务步骤不允许此操作';
    const actionBlocked = (action) => {
        if (!hasJob) return requiresJob;
        return allowed.includes(action) ? '' : stepBlocked;
    };
    const scanAllowed = allowed.includes('run_arm_scan') || allowed.includes('run_arm_acceptance');
    const testAllowed = (
        allowed.includes('test')
        || allowed.includes('run_comm_check')
        || allowed.includes('run_arm_scan')
        || allowed.includes('run_arm_acceptance')
        || (isSingleParamConfig(jobType) && allowed.includes('test'))
    );

    setButtonDisabled('connectBtn', hasSession, hasSession ? '设备已连接，如需切换请先断开连接' : '');
    setButtonDisabled('disconnectBtn', !hasSession, requiresSession);
    setButtonDisabled('createJobBtn', !hasSession, requiresSession);
    setButtonDisabled('connectWorkflowActionBtn', false);

    setButtonDisabled('scanBtn', !hasSession || !hasJob || !scanAllowed, !hasJob ? requiresJob : stepBlocked);
    setButtonDisabled('lineInventoryBtn', !hasSession, requiresSession);
    setButtonDisabled('armStatusCheckBtn', !hasSession, requiresSession);
    setButtonDisabled('armTimeoutStandardizeBtn', !hasSession, requiresSession);
    setButtonDisabled('armSafeEnableCheckBtn', !hasSession, requiresSession);
    setButtonDisabled('identifyWorkflowActionBtn', !hasSession || !hasJob, requiresJob);

    setButtonDisabled('writeParamsBtn', !hasJob || !allowed.includes('write_params'), actionBlocked('write_params'));
    setButtonDisabled('verifyParamsBtn', !hasJob || !allowed.includes('verify_params'), actionBlocked('verify_params'));
    setButtonDisabled('saveFlashBtn', !hasJob || !allowed.includes('save_flash'), actionBlocked('save_flash'));
    setButtonDisabled('zeroBtn', !hasJob || !allowed.includes('zero'), actionBlocked('zero'));
    setButtonDisabled('testBtn', !hasJob || !testAllowed, !hasJob ? requiresJob : stepBlocked);

    setButtonDisabled('probeJointBtn', !hasSession, requiresSession);
    setButtonDisabled('jointLinkTestBtn', !hasSession, requiresSession);
    setButtonDisabled('jointMicroTestBtn', !hasSession, requiresSession);
    setButtonDisabled('runNativeZeroCalibrationBtn', !hasSession, requiresSession);
}

function confirmWriteParams() {
    showModal(
        '确认写入电机参数',
        '该操作会修改电机 ESC_ID、Receiver ID、运行模式、波特率或限位等参数。后端会先失能电机，写入后必须回读校验；请确认当前只连接目标电机或目标关节明确。',
        () => handleAction(writeParams)
    );
}

function confirmSaveFlash() {
    showModal(
        '确认保存到 Flash',
        '该操作会把已写入参数固化到电机 Flash，断电后仍生效。保存前必须已完成回读校验；请避免频繁重复写入，并准备断电重上电复核。',
        () => handleAction(saveFlash)
    );
}

function confirmZeroMotor() {
    showModal(
        '确认设置单电机零点',
        '该操作会把当前机械位置写为该电机零点。请确认电机已失能、机械基准已对齐、夹具无遮挡；整臂 OpenARM 零位请使用整臂测试里的零位校准流程。',
        () => handleAction(zeroMotor)
    );
}

async function executeWorkflowPrimaryAction() {
    const descriptor = workflowActionDescriptor();

    if (descriptor.tab && descriptor.tab !== currentPrimaryTab()) {
        switchPrimaryTab(descriptor.tab);
    }

    if (descriptor.subtab) {
        switchExecuteTab(descriptor.subtab);
    }

    if (descriptor.id === 'write_params') {
        confirmWriteParams();
        return;
    }
    if (descriptor.id === 'verify_params') {
        await verifyParams();
        return;
    }
    if (descriptor.id === 'save_flash') {
        confirmSaveFlash();
        return;
    }
    if (descriptor.id === 'zero') {
        confirmZeroMotor();
        return;
    }
    if (descriptor.id === 'test' || descriptor.id === 'run_comm_check' || descriptor.id === 'run_arm_scan' || descriptor.id === 'run_arm_acceptance') {
        const jobType = document.getElementById('jobType').value;
        const scanOnly = isArmVerification(jobType);
        const commCheckOnly = isSingleCommCheck(jobType);
        const paramConfigOnly = isSingleParamConfig(jobType);
        const readbackOnly = isSingleCommissioning(jobType) && state.currentJob?.job?.status === 'params_saved';
        showModal(
            isArmAcceptance(jobType) ? '确认执行整臂 CAN2.0 验收'
                : scanOnly ? '确认执行 CAN2.0 通信扫描'
                : commCheckOnly ? '确认执行通信校验'
                : paramConfigOnly ? '确认完成参数配置'
                : readbackOnly ? '确认执行保存后复核'
                : '确认执行 safe_mit_ping',
            isArmAcceptance(jobType)
                ? '将进行整臂总线盘点、参数一致性校验，并给出 PASS / HOLD 放行结论。'
                : scanOnly ? '将只进行总线扫描、参数读取和 ID 对账，不会发送动作控制帧。'
                : commCheckOnly ? '将只进行参数读取和状态校验，不会发送动作控制帧。'
                : paramConfigOnly ? '将结束参数配置任务，生成报告与问题清单，不会发送动作控制帧。'
                : readbackOnly ? '将只回读参数和状态并生成报告，不会使能或发送动作控制帧。建议先断电重上电再执行，以确认 Flash 已生效。'
                : '请确认机械无遮挡且可以安全完成小幅动作测试。',
            () => handleAction(runTest)
        );
        return;
    }

    if (descriptor.id === 'report' || descriptor.id === 'failed') {
        switchPrimaryTab('reportTab');
    }
}

async function executeConnectWorkflowPrimaryAction() {
    const descriptor = connectWorkflowDescriptor();
    if (descriptor.id === 'refresh_interfaces') {
        await refreshInterfaces();
        return;
    }
    if (descriptor.id === 'configure_can') {
        await configureSystemCan();
        return;
    }
    if (descriptor.id === 'up_can') {
        await bringSystemCanUp();
        return;
    }
    if (descriptor.id === 'connect_device') {
        await connectDevice();
        return;
    }
    if (descriptor.id === 'go_identify') {
        switchPrimaryTab(preferredWorkbenchTab());
    }
}

async function executeIdentifyWorkflowPrimaryAction() {
    const descriptor = identifyWorkflowDescriptor();
    if (descriptor.id === 'go_connect') {
        switchPrimaryTab('connectTab');
        return;
    }
    if (descriptor.id === 'go_task') {
        switchPrimaryTab(preferredWorkbenchTab());
        return;
    }
    if (descriptor.id === 'scan_device') {
        await scanDevice();
        return;
    }
    if (descriptor.id === 'run_arm_scan' || descriptor.id === 'run_arm_acceptance') {
        const jobType = document.getElementById('jobType').value;
        showModal(
            descriptor.id === 'run_arm_acceptance' ? '确认执行整臂 CAN2.0 验收' : '确认执行整臂 CAN2.0 正式扫描',
            descriptor.id === 'run_arm_acceptance'
                ? '将进行整臂总线盘点、参数一致性校验，并给出 PASS / HOLD 放行结论。'
                : '将进行整臂正式扫描、参数对账和问题清单生成，不会发送动作控制帧。',
            () => handleAction(runTest)
        );
        return;
    }
    if (descriptor.id === 'go_execute') {
        switchPrimaryTab(preferredWorkbenchTab());
    }
}

function renderReport(payload) {
    const summary = document.getElementById('reportSummary');
    const artifacts = document.getElementById('artifactList');
    if (!state.currentJob) {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '尚无报告';
        artifacts.className = 'artifact-list empty-state';
        artifacts.textContent = '任务完成后显示';
        return;
    }

    summary.className = 'summary-grid';
    const job = state.currentJob.job;
    const summaryItems = [
        ['Job ID', job.job_id],
        ['Type', job.job_type],
        ['Status', job.status],
        ['Profile', job.profile_id || '-'],
        ['Joint', job.target_joint || '-'],
        ['OpenARM 官方型号', state.currentJob?.motors?.commissioned_motor?.target?.motor_type || '-'],
        ['放行结论', state.currentJob?.summary?.release_decision || '-'],
        ['Failure', job.failure_reason || '-']
    ];
    summary.innerHTML = summaryItems.map(([label, value]) => `
        <div class="summary-card">
            <div class="status-label">${label}</div>
            <div class="status-value">${value}</div>
        </div>
    `).join('');

    if (payload?.files?.length) {
        artifacts.className = 'artifact-list';
        artifacts.innerHTML = [
            `<div class="artifact-item"><strong>artifact_dir</strong><div>${payload.artifact_dir}</div></div>`,
            ...payload.files.map(file => `<div class="artifact-item">${file}</div>`)
        ].join('');
    }
}

function renderFactoryOverview() {
    const summary = document.getElementById('factorySummary');
    const armList = document.getElementById('factoryArmList');
    const motorList = document.getElementById('factoryMotorList');
    const zeroList = document.getElementById('factoryZeroRecordList');
    const demoList = document.getElementById('factoryDemoRecordList');
    const zeroWorkflowSummary = document.getElementById('zeroWorkflowSummary');
    const demoWorkflowSummary = document.getElementById('demoWorkflowSummary');
    const bundle = document.getElementById('factoryBundleResult');
    const reportResult = document.getElementById('factoryReportResult');
    const archiveReportResult = document.getElementById('archiveFactoryReportResult');
    const evidenceResult = document.getElementById('factoryEvidenceResult');

    if (!state.factoryOverview) {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '尚未加载出厂追溯信息';
        armList.className = 'result-list compact-results empty-state';
        armList.textContent = '暂无整机档案';
        motorList.className = 'result-list compact-results empty-state';
        motorList.textContent = '暂无电机档案';
        zeroList.className = 'result-list compact-results empty-state';
        zeroList.textContent = '暂无零位校准记录';
        demoList.className = 'result-list compact-results empty-state';
        demoList.textContent = '暂无 Demo 验证记录';
        zeroWorkflowSummary.className = 'comparison-card empty-state';
        zeroWorkflowSummary.textContent = '尚未启动零位校准流程';
        demoWorkflowSummary.className = 'comparison-card empty-state';
        demoWorkflowSummary.textContent = '尚未启动 Demo / Follower 验证流程';
    } else {
        summary.className = 'summary-grid';
        summary.innerHTML = [
            ['整机档案', state.factoryOverview.summary.arm_count],
            ['电机档案', state.factoryOverview.summary.motor_count],
            ['零位记录', state.factoryOverview.summary.zero_calibration_count || 0],
            ['Demo 记录', state.factoryOverview.summary.demo_validation_count || 0],
            ['当前任务', state.currentJobId || '-'],
            ['当前 CN', document.getElementById('factoryArmCn').value || '-'],
            ['当前 SN', document.getElementById('factoryMotorSn').value || '-']
        ].map(([label, value]) => `
            <div class="summary-card">
                <div class="status-label">${label}</div>
                <div class="status-value">${value}</div>
            </div>
        `).join('');

        const arms = state.factoryOverview.arms || [];
        if (!arms.length) {
            armList.className = 'result-list compact-results empty-state';
            armList.textContent = '暂无整机档案';
        } else {
            armList.className = 'result-list compact-results';
            armList.innerHTML = arms.map(item => `
                <div class="result-card">
                    <strong>${item.arm_cn}</strong>
                    <div>机型: ${item.arm_type || '-'}</div>
                    <div>Joint 绑定: ${Object.keys(item.joint_bindings || {}).length}</div>
                    <div>QC: ${item.qc_status || '-'}</div>
                </div>
            `).join('');
        }

        const motors = state.factoryOverview.motors || [];
        if (!motors.length) {
            motorList.className = 'result-list compact-results empty-state';
            motorList.textContent = '暂无电机档案';
        } else {
            motorList.className = 'result-list compact-results';
            motorList.innerHTML = motors.map(item => `
                <div class="result-card">
                    <strong>${item.motor_sn}</strong>
                    <div>型号: ${item.motor_type || '-'}</div>
                    <div>关节: ${item.installed_joint || '-'}</div>
                    <div>ESC/MST: ${item.esc_id ?? '-'} / ${item.mst_id ?? '-'}</div>
                </div>
            `).join('');
        }

        const recentZeroRecords = arms.flatMap(item => (item.zero_calibration_records || []).map(record => ({ ...record, arm_cn: item.arm_cn }))).slice(0, 12);
        if (!recentZeroRecords.length) {
            zeroList.className = 'result-list compact-results empty-state';
            zeroList.textContent = '暂无零位校准记录';
        } else {
            zeroList.className = 'result-list compact-results';
            zeroList.innerHTML = recentZeroRecords.map(item => `
                <div class="result-card">
                    <strong>${item.arm_cn}</strong>
                    <div>范围: ${item.calibration_scope || '-'}</div>
                    <div>结论: ${item.status || '-'}</div>
                    <div>姿态: ${item.zero_pose_name || '-'}</div>
                    <div>操作人: ${item.operator || '-'}</div>
                </div>
            `).join('');
        }

        const recentDemoRecords = arms.flatMap(item => (item.demo_validation_records || []).map(record => ({ ...record, arm_cn: item.arm_cn }))).slice(0, 12);
        if (!recentDemoRecords.length) {
            demoList.className = 'result-list compact-results empty-state';
            demoList.textContent = '暂无 Demo 验证记录';
        } else {
            demoList.className = 'result-list compact-results';
            demoList.innerHTML = recentDemoRecords.map(item => `
                <div class="result-card">
                    <strong>${item.arm_cn}</strong>
                    <div>验证: ${item.demo_name || '-'}</div>
                    <div>范围: ${item.validation_scope || '-'}</div>
                    <div>结论: ${item.status || '-'}</div>
                    <div>操作人: ${item.operator || '-'}</div>
                </div>
            `).join('');
        }

        const activeArm = currentFactoryArmRecord();
        renderFactoryWorkflowCard(
            zeroWorkflowSummary,
            activeArm?.active_zero_workflow,
            '尚未启动零位校准流程'
        );
        renderFactoryWorkflowCard(
            demoWorkflowSummary,
            activeArm?.active_demo_workflow,
            '尚未启动 Demo / Follower 验证流程'
        );
    }

    if (!state.factoryBundle) {
        bundle.className = 'artifact-list empty-state';
        bundle.textContent = '尚未生成交付包';
    } else {
        bundle.className = 'artifact-list';
        bundle.innerHTML = `
            <div class="artifact-item"><strong>arm_cn</strong><div>${state.factoryBundle.arm_cn}</div></div>
            <div class="artifact-item"><strong>bundle_dir</strong><div>${state.factoryBundle.bundle_dir}</div></div>
            <div class="artifact-item"><strong>archive_path</strong><div>${state.factoryBundle.archive_path}</div></div>
        `;
    }

    const renderFactoryReportResult = (container) => {
        if (!container) {
            return;
        }
        if (!state.factoryReportResult) {
            container.className = 'artifact-list empty-state';
            container.textContent = '尚未生成正式出厂报告';
            return;
        }
        const ref = state.factoryReportResult.report_ref;
        const missing = state.factoryReportResult.missing_required_data || [];
        const actions = state.factoryReportResult.recommended_actions || [];
        const decision = ref.release_decision || '-';
        const missingHtml = missing.length
            ? missing.map(item => `
                <div class="artifact-item">
                    <strong>${escapeHtml(item.code || 'missing_required_data')}</strong>
                    <div>Scope: ${escapeHtml(item.scope || '-')}</div>
                    <div>${escapeHtml(item.detail || '-')}</div>
                    <div class="muted">${escapeHtml(item.recommended_action || '-')}</div>
                </div>
            `).join('')
            : '<div class="artifact-item"><strong>缺测项</strong><div>无，active report standard 数据完整。</div></div>';
        const actionHtml = actions.length
            ? actions.map(action => `<div class="artifact-item"><strong>建议动作</strong><div>${escapeHtml(action)}</div></div>`).join('')
            : '<div class="artifact-item"><strong>建议动作</strong><div>无。</div></div>';
        container.className = 'artifact-list';
        container.innerHTML = `
            <div class="artifact-item"><strong>${escapeHtml(ref.title)}</strong><div>${escapeHtml(ref.report_type)}</div></div>
            <div class="artifact-item"><strong>最终结论</strong><div>${escapeHtml(decision)}</div></div>
            <div class="artifact-item"><strong>数据规则</strong><div>严格同 CN / 同侧 Profile / 已链接证据取数；缺测即提示补全或从标准移除。</div></div>
            ${missingHtml}
            ${actionHtml}
            <div class="artifact-item"><strong>PDF</strong><div>${escapeHtml(ref.pdf_path || '-')}</div></div>
            <div class="artifact-item"><strong>HTML</strong><div>${escapeHtml(ref.html_path)}</div></div>
            <div class="artifact-item"><strong>JSON</strong><div>${escapeHtml(ref.json_path)}</div></div>
        `;
    };
    renderFactoryReportResult(reportResult);
    renderFactoryReportResult(archiveReportResult);

    if (evidenceResult) {
        renderFactoryEvidenceResult(evidenceResult);
    }

    renderFactoryWorkflow();
    renderOfficialCommandResults();
}

function renderFactoryEvidenceResult(container) {
    const cards = [];
    if (state.canHealthResult) {
        cards.push(`
            <div class="artifact-item">
                <strong>CAN 健康快照: ${state.canHealthResult.status}</strong>
                <div>${state.canHealthResult.interface} · ${state.canHealthResult.evidence_ref?.json_path || '-'}</div>
            </div>
        `);
    }
    if (state.candumpResult) {
        cards.push(`
            <div class="artifact-item">
                <strong>candump: ${state.candumpResult.status}</strong>
                <div>${state.candumpResult.interface} · ${state.candumpResult.evidence_ref?.log_path || state.candumpResult.evidence_ref?.json_path || '-'}</div>
            </div>
        `);
    }
    if (state.releaseGateResult) {
        cards.push(`
            <div class="artifact-item">
                <strong>出厂 Gate: ${state.releaseGateResult.release_decision}</strong>
                <div>阻断: ${(state.releaseGateResult.blocking_items || []).join(' / ') || '-'}</div>
                <div>提醒: ${(state.releaseGateResult.warning_items || []).join(' / ') || '-'}</div>
            </div>
        `);
    }
    if (!cards.length) {
        container.className = 'artifact-list empty-state';
        container.textContent = '尚未采集证据或执行 Gate';
        return;
    }
    container.className = 'artifact-list';
    container.innerHTML = cards.join('');
}

function renderCommandRunResult(containerId, payload, emptyText) {
    const container = document.getElementById(containerId);
    if (!payload?.command_run) {
        container.className = 'comparison-card empty-state';
        container.textContent = emptyText;
        return;
    }
    const run = payload.command_run;
    const zeroSummary = run.zero_summary;
    container.className = 'comparison-card kv-list';
    const rows = [
        kvRow('状态', run.status || '-'),
        kvRow('执行模式', run.execute ? '真实执行' : '仅生成命令'),
        kvRow('命令', (run.command || []).join(' ')),
        kvRow('命令可用', run.available ? 'YES' : 'NO'),
        kvRow('安全确认', (run.missing_confirmations || []).length ? `缺少 ${(run.missing_confirmations || []).map(item => item.label).join(' / ')}` : '已满足'),
        kvRow('退出码', run.returncode ?? '-'),
    ];
    if (zeroSummary) {
        rows.push(kvRow('写零确认', zeroSummary.zero_written ? 'YES' : 'NO'));
        rows.push(kvRow('恢复初始姿态', zeroSummary.restore_completed ? 'YES' : 'NO'));
        rows.push(kvRow('零位阻塞项', (zeroSummary.blocking_items || []).join(' / ') || '-'));
        rows.push(kvRow('零位警告项', (zeroSummary.warning_items || []).join(' / ') || '-'));
    }
    rows.push(kvRow('stderr', run.stderr || '-'));
    container.innerHTML = rows.join('');
}

function renderOfficialCommandResults() {
    renderCommandRunResult('officialZeroCommandResult', state.officialZeroCommandResult, '尚未生成官方零位命令');
    renderCommandRunResult('officialDemoCommandResult', state.officialDemoCommandResult, '尚未生成官方 Demo 命令');
    renderCommandRunResult('officialMotorCheckResult', state.officialMotorCheckResult, '尚未生成官方 motor-check 命令');
    renderCommandRunResult('officialBaudrateResult', state.officialBaudrateResult, '尚未生成官方波特率命令');
    renderNativeZeroCalibrationResult();
}

function renderNativeZeroCalibrationResult() {
    const container = document.getElementById('nativeZeroCalibrationResult');
    if (!container) {
        return;
    }
    const payload = state.nativeZeroCalibrationResult;
    if (!payload) {
        container.className = 'comparison-card empty-state';
        container.textContent = '尚未执行工站内置零位校准';
        return;
    }
    const passedCount = (payload.joint_results || []).filter(item => item.passed).length;
    const totalCount = (payload.joint_results || []).length;
    const failed = (payload.joint_results || []).filter(item => !item.passed).map(item => item.joint_name).join(', ') || '-';
    container.className = 'comparison-card kv-list';
    container.innerHTML = [
        kvRow('状态', payload.status || '-'),
        kvRow('结论', payload.calibrated ? 'PASS' : 'FAIL / BLOCKED'),
        kvRow('Profile', payload.profile_id || '-'),
        kvRow('Arm Side', payload.arm_side || '-'),
        kvRow('零位姿态', payload.zero_pose_name || '-'),
        kvRow('通过关节', `${passedCount}/${totalCount}`),
        kvRow('失败关节', failed),
        kvRow('记录', payload.record_entry?.record_id || '-'),
    ].join('');
}

function currentFactoryArmRecord() {
    const arms = state.factoryOverview?.arms || [];
    const currentCn = document.getElementById('factoryArmCn').value.trim();
    return arms.find(item => item.arm_cn === currentCn) || arms[0] || null;
}

function currentFactoryMotorRecord() {
    const motors = state.factoryOverview?.motors || [];
    const currentSn = document.getElementById('factoryMotorSn').value.trim();
    return motors.find(item => item.motor_sn === currentSn) || null;
}

function factoryWorkflowDescriptor() {
    const armCn = document.getElementById('factoryArmCn').value.trim();
    const arm = currentFactoryArmRecord();
    const activeZero = arm?.active_zero_workflow;
    const activeDemo = arm?.active_demo_workflow;
    const zeroDone = Boolean(arm?.zero_calibration_records?.length);
    const demoDone = Boolean(arm?.demo_validation_records?.length);

    if (!armCn || !arm || arm.arm_cn !== armCn) {
        return {
            id: 'bind_arm',
            title: '步骤 1：建立整机 CN',
            detail: '先录入并保存当前机械臂的 CN、机型和 BOM Profile，作为后续全部追溯记录的主索引。',
            buttonText: '保存 CN',
            tone: 'ready'
        };
    }

    if (state.currentJobId && arm && !(arm.linked_jobs || []).some(item => item.job_id === state.currentJobId)) {
        return {
            id: 'attach_job_to_arm',
            title: '步骤 2：挂接当前测试任务到整机档案',
            detail: '把当前任务和全部电机反馈数据挂到整机 CN，报告只按整臂序列号追溯。',
            buttonText: '挂当前任务',
            tone: 'ready'
        };
    }

    if (activeZero?.status === 'active') {
        return {
            id: 'zero_step',
            title: '步骤 5：推进官方动态零位流程',
            detail: `当前零位流程正在执行：${activeZero.steps?.[activeZero.current_step_index || 0]?.label || '继续下一步'}。`,
            buttonText: '完成当前零位步骤',
            tone: 'ready'
        };
    }
    if (activeZero?.status === 'awaiting_finalize') {
        return {
            id: 'zero_finalize',
            title: '步骤 5：归档官方动态零位结果',
            detail: '官方动态零位流程步骤已全部完成，确认结论后归档为正式零位校准记录。',
            buttonText: '完成零位归档',
            tone: 'ready'
        };
    }
    if (!zeroDone) {
        return {
            id: 'zero_start',
            title: '步骤 5：启动官方动态零位流程',
            detail: '按官方 Step 4 进行动态零位校准。机械臂会自动移动，需先完成 ID、SocketCAN、motor-check 和安全确认。',
            buttonText: '启动官方零位流程',
            tone: 'ready'
        };
    }

    if (activeDemo?.status === 'active') {
        return {
            id: 'demo_step',
            title: '步骤 6：推进官方 Step 5 Demo',
            detail: `当前 Demo 流程正在执行：${activeDemo.steps?.[activeDemo.current_step_index || 0]?.label || '继续下一步'}。`,
            buttonText: '完成当前 Demo 步骤',
            tone: 'ready'
        };
    }
    if (activeDemo?.status === 'awaiting_finalize') {
        return {
            id: 'demo_finalize',
            title: '步骤 6：归档官方 Step 5 Demo 结果',
            detail: '官方 Demo 流程步骤已全部完成，确认结论后归档为正式 Demo 验证记录。',
            buttonText: '完成 Demo 归档',
            tone: 'ready'
        };
    }
    if (!demoDone) {
        return {
            id: 'demo_start',
            title: '步骤 6：启动官方 Step 5 Demo',
            detail: '官方 Demo 会使能并执行位置/力矩/夹爪与状态监测。只有官方动态零位完成后才能执行。',
            buttonText: '启动官方 Demo 流程',
            tone: 'ready'
        };
    }

    return {
        id: 'build_bundle',
        title: '步骤 7：导出交付包',
        detail: '当前 CN 的追溯、官方动态零位和官方 Demo 记录已经齐备，可以导出官方流程交付包。',
        buttonText: '导出交付包',
        tone: 'done'
    };
}

function renderFactoryWorkflow() {
    const descriptor = factoryWorkflowDescriptor();
    document.getElementById('factoryWorkflowActionTitle').textContent = descriptor.title;
    document.getElementById('factoryWorkflowActionDetail').textContent = descriptor.detail;
    const stateNode = document.getElementById('factoryWorkflowActionState');
    stateNode.textContent = descriptor.tone === 'ready' ? '可执行' : descriptor.tone === 'done' ? '已就绪' : '待处理';
    stateNode.className = `action-status ${descriptor.tone}`;
    const button = document.getElementById('factoryWorkflowActionBtn');
    button.textContent = descriptor.buttonText;
    button.disabled = false;
}

async function executeFactoryWorkflowPrimaryAction() {
    const descriptor = factoryWorkflowDescriptor();
    if (descriptor.id === 'bind_arm') {
        await bindArmIdentity();
        return;
    }
    if (descriptor.id === 'bind_motor') {
        await bindMotorIdentity();
        return;
    }
    if (descriptor.id === 'assign_joint') {
        await assignFactoryJointMotor();
        return;
    }
    if (descriptor.id === 'attach_job_to_arm') {
        await attachCurrentJobToArm();
        return;
    }
    if (descriptor.id === 'zero_start') {
        await startZeroWorkflow();
        return;
    }
    if (descriptor.id === 'zero_step') {
        await completeZeroWorkflowStep();
        return;
    }
    if (descriptor.id === 'zero_finalize') {
        await finalizeZeroWorkflow();
        return;
    }
    if (descriptor.id === 'demo_start') {
        await startDemoWorkflow();
        return;
    }
    if (descriptor.id === 'demo_step') {
        await completeDemoWorkflowStep();
        return;
    }
    if (descriptor.id === 'demo_finalize') {
        await finalizeDemoWorkflow();
        return;
    }
    if (descriptor.id === 'build_bundle') {
        await buildFactoryBundle();
    }
}

function renderFactoryWorkflowCard(container, workflow, emptyText) {
    if (!workflow) {
        container.className = 'comparison-card empty-state';
        container.textContent = emptyText;
        return;
    }
    const steps = workflow.steps || [];
    const currentStep = steps[Math.min(workflow.current_step_index || 0, Math.max(steps.length - 1, 0))];
    container.className = 'comparison-card kv-list';
    container.innerHTML = [
        kvRow('流程 ID', workflow.workflow_id || '-'),
        kvRow('状态', workflow.status || '-'),
        kvRow('当前步骤', currentStep?.label || (workflow.status === 'awaiting_finalize' ? '等待归档' : '-')),
        kvRow('操作人', workflow.operator || '-'),
        kvRow('关联任务', workflow.linked_job?.job_id || '-'),
        kvRow('说明', workflow.notes || '-'),
    ].join('') + `
        <div class="workflow-step-list">
            ${steps.map(step => `
                <div class="workflow-step-item ${step.status}">
                    <strong>${step.label}</strong>
                    <div>${step.instruction}</div>
                    <div class="muted">状态: ${step.status}</div>
                </div>
            `).join('')}
        </div>
    `;
}

async function startZeroWorkflow() {
    const payload = await api('/api/factory/zero-workflows/start', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            operator: document.getElementById('factoryZeroOperator').value.trim() || null,
            linked_job_id: state.currentJobId || null,
            notes: document.getElementById('factoryZeroNotes').value.trim() || null,
            calibration_scope: document.getElementById('factoryZeroScope').value,
            zero_pose_name: document.getElementById('factoryZeroPoseName').value.trim() || 'openarm_home',
        })
    });
    addLog(`零位流程已启动: ${payload.workflow.workflow_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function completeZeroWorkflowStep() {
    const payload = await api('/api/factory/zero-workflows/advance', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            action: 'complete_step',
            notes: document.getElementById('factoryZeroNotes').value.trim() || null,
        })
    });
    addLog(`零位流程步骤已完成: ${payload.workflow.workflow_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function finalizeZeroWorkflow() {
    const payload = await api('/api/factory/zero-workflows/advance', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            action: 'finalize',
            final_status: document.getElementById('factoryZeroStatus').value,
            notes: document.getElementById('factoryZeroNotes').value.trim() || null,
        })
    });
    addLog(`零位流程已归档: ${payload.record_entry.record_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function failZeroWorkflow() {
    const payload = await api('/api/factory/zero-workflows/advance', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            action: 'mark_failed',
            notes: document.getElementById('factoryZeroNotes').value.trim() || 'Zero calibration workflow failed',
        })
    });
    addLog(`零位流程已标记失败: ${payload.workflow.workflow_id}`, 'warning', 'factory');
    await refreshFactoryOverview();
}

async function startDemoWorkflow() {
    const payload = await api('/api/factory/demo-workflows/start', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            operator: document.getElementById('factoryDemoOperator').value.trim() || null,
            linked_job_id: state.currentJobId || null,
            notes: document.getElementById('factoryDemoNotes').value.trim() || null,
            demo_name: document.getElementById('factoryDemoName').value.trim() || 'official_demo',
            validation_scope: document.getElementById('factoryDemoScope').value,
            command: document.getElementById('factoryDemoCommand').value.trim() || null,
        })
    });
    addLog(`Demo 流程已启动: ${payload.workflow.workflow_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function completeDemoWorkflowStep() {
    const payload = await api('/api/factory/demo-workflows/advance', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            action: 'complete_step',
            notes: document.getElementById('factoryDemoNotes').value.trim() || null,
        })
    });
    addLog(`Demo 流程步骤已完成: ${payload.workflow.workflow_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function finalizeDemoWorkflow() {
    const payload = await api('/api/factory/demo-workflows/advance', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            action: 'finalize',
            final_status: document.getElementById('factoryDemoStatus').value,
            notes: document.getElementById('factoryDemoNotes').value.trim() || null,
        })
    });
    addLog(`Demo 流程已归档: ${payload.record_entry.record_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function failDemoWorkflow() {
    const payload = await api('/api/factory/demo-workflows/advance', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            action: 'mark_failed',
            notes: document.getElementById('factoryDemoNotes').value.trim() || 'Demo validation workflow failed',
        })
    });
    addLog(`Demo 流程已标记失败: ${payload.workflow.workflow_id}`, 'warning', 'factory');
    await refreshFactoryOverview();
}

async function recordZeroCalibration() {
    const payload = await api('/api/factory/zero-calibration', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            calibration_scope: document.getElementById('factoryZeroScope').value,
            status: document.getElementById('factoryZeroStatus').value,
            zero_pose_name: document.getElementById('factoryZeroPoseName').value.trim() || 'openarm_home',
            operator: document.getElementById('factoryZeroOperator').value.trim() || null,
            linked_job_id: state.currentJobId || null,
            notes: document.getElementById('factoryZeroNotes').value.trim() || null,
        })
    });
    addLog(`零位校准记录已保存: ${payload.entry.record_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function recordDemoValidation() {
    const payload = await api('/api/factory/demo-validation', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            demo_name: document.getElementById('factoryDemoName').value.trim() || 'official_demo',
            validation_scope: document.getElementById('factoryDemoScope').value,
            status: document.getElementById('factoryDemoStatus').value,
            operator: document.getElementById('factoryDemoOperator').value.trim() || null,
            command: document.getElementById('factoryDemoCommand').value.trim() || null,
            linked_job_id: state.currentJobId || null,
            notes: document.getElementById('factoryDemoNotes').value.trim() || null,
        })
    });
    addLog(`Demo 验证记录已保存: ${payload.entry.record_id}`, 'success', 'factory');
    await refreshFactoryOverview();
}

function updateLiveStatus(data) {
    if (state.currentJobId && data.job_id && data.job_id !== state.currentJobId) {
        return;
    }
    document.getElementById('livePosition').textContent = Number(data.position || 0).toFixed(2);
    document.getElementById('liveVelocity').textContent = Number(data.velocity || 0).toFixed(2);
    document.getElementById('liveTorque').textContent = Number(data.torque || 0).toFixed(2);
    document.getElementById('liveMos').textContent = Number(data.t_mos || 0).toFixed(1);
    document.getElementById('liveRotor').textContent = Number(data.t_rotor || 0).toFixed(1);
    document.getElementById('liveStatusText').textContent = data.motor_status || 'UNKNOWN';
}

function updateCanHealthStatus(payload) {
    const interfaces = payload?.interfaces || [];
    const preferredName = document.getElementById('socketcanChannel')?.value?.trim() || payload?.recommended_channel;
    const iface = interfaces.find(item => item.name === preferredName) || interfaces[0];
    const stats = iface?.statistics || {};
    const rxErrors = Number(stats.rx_errors || 0);
    const txErrors = Number(stats.tx_errors || 0);
    const dropped = Number(stats.total_dropped ?? ((stats.rx_dropped || 0) + (stats.tx_dropped || 0)));
    const packets = Number(stats.total_packets ?? ((stats.rx_packets || 0) + (stats.tx_packets || 0)));
    const errorRate = Number(stats.error_rate || 0);
    const dropRate = Number(stats.drop_rate || 0);
    document.getElementById('liveCanErrors').textContent = `${rxErrors} / ${txErrors}`;
    document.getElementById('liveCanDropped').textContent = String(dropped);
    document.getElementById('liveCanPackets').textContent = String(packets);
    document.getElementById('liveCanHealth').textContent = !iface
        ? '-'
        : (rxErrors || txErrors || dropped || errorRate > 0.001 || dropRate > 0.001) ? 'CHECK' : 'OK';
}

async function loadConfig() {
    const payload = await api('/api/config');
    state.config = payload;

    document.getElementById('jobType').innerHTML = payload.job_types.map(item => `
        <option value="${item.id}">${item.label}</option>
    `).join('');
    document.getElementById('transportType').innerHTML = payload.transports.map(item => `
        <option value="${item.id}">${item.label}</option>
    `).join('');

    renderProfiles();
    renderTransportForm();
    renderScopeAssumptions();
    renderSteps();
}

async function refreshVendorToolStatus() {
    const payload = await api('/api/vendor/dmtool/status');
    state.vendorToolStatus = payload.dmtool ? payload : { dmtool: payload };
    renderVendorMaintenance();
}

async function launchDmTool() {
    const payload = await api('/api/vendor/dmtool/launch', { method: 'POST' });
    state.vendorToolStatus = { dmtool: { ...(state.vendorToolStatus?.dmtool || {}), exists: true, executable: true } };
    renderVendorMaintenance();
    addLog(`已打开达妙上位机，PID ${payload.dmtool.pid}，日志 ${payload.dmtool.log_path}`, 'success', 'vendor');
}

async function refreshVendorMaintenanceRecords() {
    const payload = await api('/api/vendor/maintenance-records');
    state.vendorMaintenanceRecords = payload.records || [];
    renderVendorMaintenance();
}

async function saveVendorMaintenanceRecord() {
    const target = document.getElementById('vendorMaintTarget').value.trim();
    if (!target) {
        throw new Error('请填写维护对象，例如 R-J4 或 Loose motor');
    }
    const payload = await api('/api/vendor/maintenance-records', {
        method: 'POST',
        body: JSON.stringify({
            target_label: target,
            maintenance_stage: document.getElementById('vendorMaintStage').value,
            motor_encoder_calibration: document.getElementById('vendorMotorEncoder').value,
            output_encoder_calibration: document.getElementById('vendorOutputEncoder').value,
            zero_save: document.getElementById('vendorZeroSave').value,
            operator: document.getElementById('vendorMaintOperator').value.trim() || null,
            notes: document.getElementById('vendorMaintNotes').value.trim() || null,
            linked_job_id: state.currentJobId || null
        })
    });
    state.vendorMaintenanceRecords = payload.records || [payload.entry];
    renderVendorMaintenance();
    addLog(`已保存厂家维护记录：${target}`, 'success', 'vendor');
}

async function refreshInterfaces() {
    const payload = await api('/api/system/can-interfaces');
    state.interfaceStatus = payload;
    renderInterfaceStatus();

    if (payload.recommended_channel) {
        document.getElementById('transportType').value = 'socketcan';
        renderTransportForm();
        document.getElementById('socketcanChannel').value = payload.recommended_channel;
    }
}

async function refreshFactoryOverview() {
    const payload = await api('/api/factory/overview');
    state.factoryOverview = payload;
    renderFactoryOverview();
}

async function configureSystemCan() {
    const mode = document.getElementById('systemCanMode').value;
    const payload = await api('/api/system/can-interfaces/configure', {
        method: 'POST',
        body: JSON.stringify({
            name: document.getElementById('systemCanName').value,
            mode,
            bitrate: Number(document.getElementById('systemCanBitrate').value),
            dbitrate: mode === 'canfd' ? Number(document.getElementById('systemCanDbitrate').value) : null,
            fd_enabled: mode === 'canfd',
            tool: 'ip_link'
        })
    });
    state.interfaceStatus = {
        interfaces: payload.interfaces,
        recommended_channel: payload.recommended_channel
    };
    renderInterfaceStatus();
    addLog(`接口 ${payload.interface.name} 已配置为 ${mode === 'canfd' ? 'CAN FD' : 'CAN 2.0'}`, 'success', 'system_can');
}

async function bringSystemCanUp() {
    const payload = await api('/api/system/can-interfaces/up', {
        method: 'POST',
        body: JSON.stringify({ name: document.getElementById('systemCanName').value })
    });
    addLog(`接口 ${payload.interface.name} 已拉起`, 'success', 'system_can');
    await refreshInterfaces();
}

async function bringSystemCanDown() {
    const payload = await api('/api/system/can-interfaces/down', {
        method: 'POST',
        body: JSON.stringify({ name: document.getElementById('systemCanName').value })
    });
    addLog(`接口 ${payload.interface.name} 已关闭`, 'info', 'system_can');
    await refreshInterfaces();
}

async function connectDevice() {
    const payload = await api('/api/device/connect', {
        method: 'POST',
        body: JSON.stringify(buildConnectionPayload())
    });
    state.sessionId = payload.device_session_id;
    state.capabilities = payload.capabilities;
    renderCapabilities();
    renderMeta();
    renderLineInventory();
    await refreshInterfaces();
    addLog('设备连接成功', 'success', 'connect');
    openTestingArea('scan');
}

async function disconnectDevice() {
    if (!state.sessionId) {
        return;
    }
    await api('/api/device/disconnect', {
        method: 'POST',
        body: JSON.stringify({ device_session_id: state.sessionId })
    });
    state.sessionId = null;
    state.capabilities = null;
    state.lineInventory = null;
    state.jointDiagnostic = null;
    renderCapabilities();
    renderMeta();
    renderLineInventory();
    renderJointDiagnostic();
    addLog('设备已断开', 'info', 'connect');
}

async function scanLineInventory() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const payload = await api('/api/device/line-inventory', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            profile_id: document.getElementById('profileSelect').value
        })
    });
    state.lineInventory = payload;
    renderLineInventory();
    openTestingArea('scan');
    addLog(`总线 ID 盘点完成，发现 ${payload.summary.total_detected} 个节点`, 'success', 'inventory');
}

function syncFactoryMotorFromSelection() {
    const jointName = document.getElementById('factoryJointSelect').value;
    if (!jointName) {
        return;
    }
    const profile = currentProfile();
    const joint = (profile?.joints || []).find(item => item.joint_name === jointName);
    if (!joint) {
        return;
    }
    if (!document.getElementById('factoryMotorType').value) {
        document.getElementById('factoryMotorType').value = joint.motor_type || '';
    }
    document.getElementById('factoryEscId').value = joint.target_esc_id ?? '';
    document.getElementById('factoryMstId').value = joint.target_mst_id ?? '';
}

function renderFactorySerialValidation(payload = null) {
    const container = document.getElementById('factorySerialValidation');
    if (!container) {
        return;
    }
    if (!payload) {
        container.className = 'comparison-card empty-state';
        container.textContent = '编号规则：整机 CN=OA{F/L}{YYMMDD}{NN}；整机 PDF 仅输出 CN';
        return;
    }
    const validation = payload.validation || payload;
    container.className = `comparison-card kv-list ${validation.valid ? '' : 'blocked'}`;
    container.innerHTML = [
        kvRow('类型', validation.type || '-'),
        kvRow('值', validation.value || payload.arm_cn || payload.motor_sn || '-'),
        kvRow('结论', validation.valid ? 'OK' : '格式错误'),
        kvRow('说明', validation.message || '-'),
    ].join('');
}

async function generateFactoryArmCn() {
    const payload = await api('/api/factory/serials/arm-cn', {
        method: 'POST',
        body: JSON.stringify(factorySerialPayloadBase())
    });
    document.getElementById('factoryArmCn').value = payload.arm_cn;
    renderFactorySerialValidation(payload);
    renderFactoryWorkflow();
    addLog(`已生成机械臂 CN: ${payload.arm_cn}`, 'success', 'serial');
}

async function generateFactoryMotorSn() {
    const motorType = document.getElementById('factoryMotorType').value.trim();
    if (!motorType) {
        throw new Error('请先选择关节或填写电机型号');
    }
    const payload = await api('/api/factory/serials/motor-sn', {
        method: 'POST',
        body: JSON.stringify({
            ...factorySerialPayloadBase(),
            motor_type: motorType,
            can_id: Number(document.getElementById('factoryEscId').value || 1)
        })
    });
    document.getElementById('factoryMotorSn').value = payload.motor_sn;
    renderFactorySerialValidation(payload);
    renderFactoryWorkflow();
    addLog(`已生成内部电机追溯号: ${payload.motor_sn}`, 'success', 'serial');
}

async function validateFactorySerial(type, value) {
    if (!value) {
        renderFactorySerialValidation();
        return;
    }
    const payload = await api('/api/factory/serials/validate', {
        method: 'POST',
        body: JSON.stringify({ type, value })
    });
    renderFactorySerialValidation(payload);
}

async function bindArmIdentity() {
    const payload = await api('/api/factory/arms', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            arm_type: document.getElementById('factoryArmType').value.trim(),
            bom_profile: document.getElementById('factoryBomProfile').value.trim() || 'openarm_v1',
            left_arm_installed: true,
            right_arm_installed: true
        })
    });
    addLog(`整机 CN 已保存: ${payload.arm_cn}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function bindMotorIdentity() {
    const payload = await api('/api/factory/motors', {
        method: 'POST',
        body: JSON.stringify({
            motor_sn: document.getElementById('factoryMotorSn').value.trim(),
            motor_type: document.getElementById('factoryMotorType').value.trim(),
            installed_joint: document.getElementById('factoryJointSelect').value,
            arm_cn: document.getElementById('factoryArmCn').value.trim() || null,
            esc_id: Number(document.getElementById('factoryEscId').value || 0) || null,
            mst_id: Number(document.getElementById('factoryMstId').value || 0) || null
        })
    });
    addLog(`内部电机追溯号已保存: ${payload.motor_sn}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function assignFactoryJointMotor() {
    const payload = await api('/api/factory/assign-joint', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            joint_name: document.getElementById('factoryJointSelect').value,
            motor_sn: document.getElementById('factoryMotorSn').value.trim(),
            esc_id: Number(document.getElementById('factoryEscId').value || 0) || null,
            mst_id: Number(document.getElementById('factoryMstId').value || 0) || null,
            motor_type: document.getElementById('factoryMotorType').value.trim() || null
        })
    });
    addLog(`关节绑定完成: ${payload.arm.arm_cn} / ${document.getElementById('factoryJointSelect').value}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function attachCurrentJobToMotor() {
    if (!state.currentJobId) {
        throw new Error('请先创建并执行任务');
    }
    const payload = await api('/api/factory/attach-job-to-motor', {
        method: 'POST',
        body: JSON.stringify({
            motor_sn: document.getElementById('factoryMotorSn').value.trim(),
            job_id: state.currentJobId
        })
    });
    addLog(`当前任务已挂到内部电机追溯号: ${payload.motor_sn}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function attachCurrentJobToArm() {
    if (!state.currentJobId) {
        throw new Error('请先创建并执行任务');
    }
    const payload = await api('/api/factory/attach-job-to-arm', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim(),
            job_id: state.currentJobId
        })
    });
    addLog(`当前任务已挂到整机 CN: ${payload.arm_cn}`, 'success', 'factory');
    await refreshFactoryOverview();
}

async function buildFactoryBundle() {
    const payload = await api('/api/factory/build-bundle', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: document.getElementById('factoryArmCn').value.trim()
        })
    });
    state.factoryBundle = payload;
    renderFactoryOverview();
    addLog(`基础交付包已生成: ${payload.arm_cn}`, 'success', 'factory');
}

async function captureFactoryCanHealth() {
    const payload = await api('/api/factory/can-health', {
        method: 'POST',
        body: JSON.stringify({
            interface: factoryEvidenceInterface(),
            arm_cn: currentFactoryArmCn(),
            job_id: state.currentJobId,
            notes: 'Factory CAN health snapshot',
        })
    });
    state.canHealthResult = payload;
    renderFactoryOverview();
    await refreshFactoryOverview();
    addLog(`CAN 健康快照完成: ${payload.status}`, payload.status === 'passed' ? 'success' : 'warning', 'can_health');
}

async function captureFactoryCandump() {
    const payload = await api('/api/factory/candump-evidence', {
        method: 'POST',
        body: JSON.stringify({
            interface: factoryEvidenceInterface(),
            duration_s: Number(document.getElementById('factoryCandumpDuration').value || 2),
            arm_cn: currentFactoryArmCn(),
            job_id: state.currentJobId,
            label: 'factory_can_trace',
            notes: 'Factory raw CAN trace',
        })
    });
    state.candumpResult = payload;
    renderFactoryOverview();
    await refreshFactoryOverview();
    addLog(`candump 证据采集完成: ${payload.status}`, payload.status === 'captured' ? 'success' : 'warning', 'candump');
}

async function runFactoryReleaseGate() {
    const payload = await api(`/api/factory/release-gate/${encodeURIComponent(currentFactoryArmCn())}`);
    state.releaseGateResult = payload;
    renderFactoryOverview();
    addLog(`出厂 Gate: ${payload.release_decision}`, payload.release_ready ? 'success' : 'warning', 'release_gate');
}

async function generateMotorParameterReport() {
    const motorSn = document.getElementById('factoryMotorSn').value.trim();
    if (!motorSn) {
        throw new Error('请先在机械臂工站登记或填写内部电机追溯号');
    }
    const payload = await api('/api/factory/reports/motor-parameter', {
        method: 'POST',
        body: JSON.stringify({
            motor_sn: motorSn,
            job_id: state.currentJobId,
            notes: 'Generated from motor workstation',
        })
    });
    state.factoryReportResult = payload;
    renderFactoryOverview();
    addLog(`电机参数报告已生成: ${motorSn}`, 'success', 'motor_report');
}

async function generateArmReport(reportType) {
    const armCn = currentFactoryArmCn();
    const endpointMap = {
        zero: '/api/factory/reports/zero-calibration',
        safety: '/api/factory/reports/safety-test',
        factory: '/api/factory/reports/formal-factory-acceptance',
    };
    const payload = await api(endpointMap[reportType], {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: armCn,
            job_id: state.currentJobId,
            profile_id: document.getElementById('profileSelect')?.value || null,
        })
    });
    state.factoryReportResult = payload;
    renderFactoryOverview();
    const label = reportType === 'zero' ? '零位校准报告' : reportType === 'safety' ? '安全测试报告' : '整机出厂报告';
    const decision = payload.report_ref?.release_decision || '-';
    const missingCount = (payload.missing_required_data || []).length;
    const tone = decision === 'PASS' && missingCount === 0 ? 'success' : 'warning';
    const suffix = missingCount ? `，缺测项 ${missingCount} 个，请查看建议动作` : `，结论 ${decision}`;
    addLog(`${label}已生成: ${armCn}${suffix}`, tone, 'factory_report');
}

async function refreshOfficialCommands() {
    state.officialCommands = await api('/api/factory/official-commands');
}

function syncOfficialCommandFromJoint() {
    const jointName = selectedDiagnosticJoint();
    const profile = currentProfile();
    const joint = (profile?.joints || []).find(item => item.joint_name === jointName);
    if (!joint) {
        throw new Error('没有找到当前关节模板');
    }
    document.getElementById('officialCheckCanid').value = joint.target_esc_id;
    document.getElementById('officialCheckRecvid').value = joint.target_mst_id;
    document.getElementById('officialBaudrateCanid').value = joint.target_esc_id;
    const bus = joint.expected_bus || document.getElementById('socketcanChannel').value.trim() || 'can0';
    document.getElementById('officialCheckSocketcan').value = bus;
    document.getElementById('officialBaudrateSocketcan').value = bus;
    addLog(`已同步 ${jointName} 的官方命令参数`, 'info', 'official_command');
}

async function planOfficialMotorCheck() {
    const payload = await api('/api/openarm/motor-check', {
        method: 'POST',
        body: JSON.stringify(officialMotorCheckPayload(false))
    });
    state.officialMotorCheckResult = payload;
    renderOfficialCommandResults();
    addLog('官方 motor-check 命令已生成', 'info', 'official_motor_check');
}

async function runOfficialMotorCheck() {
    const payload = await api('/api/openarm/motor-check', {
        method: 'POST',
        body: JSON.stringify(officialMotorCheckPayload(true))
    });
    state.officialMotorCheckResult = payload;
    renderOfficialCommandResults();
    await refreshFactoryOverview();
    addLog(`官方 motor-check 执行状态: ${payload.command_run.status}`, payload.command_run.status === 'passed' ? 'success' : 'warning', 'official_motor_check');
}

async function planOfficialBaudrateChange() {
    const payload = await api('/api/openarm/change-baudrate', {
        method: 'POST',
        body: JSON.stringify(officialBaudratePayload(false))
    });
    state.officialBaudrateResult = payload;
    renderOfficialCommandResults();
    addLog('官方波特率变更命令已生成', 'info', 'official_baudrate');
}

async function runOfficialBaudrateChange() {
    const payload = await api('/api/openarm/change-baudrate', {
        method: 'POST',
        body: JSON.stringify(officialBaudratePayload(true))
    });
    state.officialBaudrateResult = payload;
    renderOfficialCommandResults();
    await refreshFactoryOverview();
    addLog(`官方波特率变更执行状态: ${payload.command_run.status}`, payload.command_run.status === 'passed' ? 'success' : 'warning', 'official_baudrate');
}

async function planOfficialZeroCommand() {
    const zeroOptions = officialZeroCommandOptions();
    const payload = await api('/api/factory/zero-workflows/run-official', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: currentFactoryArmCn(),
            ...zeroOptions,
            execute: false,
            confirmations: {},
        })
    });
    state.officialZeroCommandResult = payload;
    renderOfficialCommandResults();
    await refreshFactoryOverview();
    addLog('官方动态零位命令已生成，请核对 canport 与 arm_side', 'info', 'official_zero');
}

function numberInputValue(id) {
    const element = document.getElementById(id);
    if (!element) {
        return null;
    }
    const raw = element.value.trim();
    if (!raw) {
        return null;
    }
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
}

function officialZeroCommandOptions() {
    return {
        canport: document.getElementById('officialZeroCanport').value.trim() || 'can0',
        arm_side: document.getElementById('officialZeroArmSide').value,
        max_bump_deg: numberInputValue('officialZeroMaxBumpDeg'),
        max_bump_time_s: numberInputValue('officialZeroMaxBumpTime'),
        bump_step_deg: numberInputValue('officialZeroBumpStepDeg'),
        bump_dt_s: numberInputValue('officialZeroBumpDt'),
        restore_initial_pose: document.getElementById('officialZeroRestoreInitialPose')?.value === 'true',
        restore_max_deg: numberInputValue('officialZeroRestoreMaxDeg'),
        skip_gripper_limit_search: document.getElementById('officialZeroSkipGripper')?.value !== 'false',
    };
}

async function runOfficialZeroCommand() {
    const zeroOptions = officialZeroCommandOptions();
    const payload = await api('/api/factory/zero-workflows/run-official', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: currentFactoryArmCn(),
            ...zeroOptions,
            execute: true,
            confirmations: officialZeroConfirmations(),
        })
    });
    state.officialZeroCommandResult = payload;
    renderOfficialCommandResults();
    await refreshFactoryOverview();
    addLog(`官方动态零位命令执行状态: ${payload.command_run.status}`, payload.command_run.status === 'passed' ? 'success' : 'warning', 'official_zero');
}

async function runNativeZeroCalibration() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const armCn = currentFactoryArmCn();
    const payload = await api('/api/device/arm-zero-calibration', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            profile_id: document.getElementById('profileSelect').value,
            arm_cn: armCn,
            operator: document.getElementById('factoryZeroOperator').value.trim() || null,
            notes: document.getElementById('factoryZeroNotes').value.trim() || null,
            zero_pose_name: document.getElementById('factoryZeroPoseName').value.trim() || 'openarm_home',
            confirmations: nativeZeroConfirmations(),
            save_flash: true,
        })
    });
    state.nativeZeroCalibrationResult = payload;
    renderNativeZeroCalibrationResult();
    await refreshFactoryOverview();
    addLog(`工站辅助静态零位完成: ${payload.status}`, payload.calibrated ? 'success' : 'warning', 'native_zero');
}

async function planOfficialDemoCommand() {
    const command = officialDemoCommandValue();
    if (!command) {
        throw new Error('请先填写官方 Demo / Follower 命令');
    }
    const payload = await api('/api/factory/demo-workflows/run-official', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: currentFactoryArmCn(),
            command,
            execute: false,
            confirmations: {},
        })
    });
    state.officialDemoCommandResult = payload;
    renderOfficialCommandResults();
    await refreshFactoryOverview();
    addLog('官方 Demo 命令已生成，请核对命令与验证范围', 'info', 'official_demo');
}

function officialDemoCommandValue() {
    const raw = document.getElementById('factoryDemoCommand').value.trim();
    if (raw === 'openarm-can-demo') {
        const canport = document.getElementById('officialZeroCanport').value.trim() || 'can0';
        const armSide = document.getElementById('officialZeroArmSide').value;
        const armCn = currentFactoryArmCn();
        if (!/^OA[FL]\d{8}$/i.test(armCn || '')) {
            throw new Error('请先填写并保存有效整臂 CN：OAF... 表示 Follower，OAL... 表示 Leader，Demo 需要据此确定夹爪方向');
        }
        const gripperOpenTarget = /^OAF/i.test(armCn) ? '-1.0472' : '1.0472';
        return `openarm-can-demo --canport ${canport} --arm-side ${armSide} --enable-hold-ms 1500 --phase-hold-s 3.0 --gripper-open-target ${gripperOpenTarget} --gripper-close-target 0.0`;
    }
    return raw;
}

async function runOfficialDemoCommand() {
    const command = officialDemoCommandValue();
    if (!command) {
        throw new Error('请先填写官方 Demo / Follower 命令');
    }
    const payload = await api('/api/factory/demo-workflows/run-official', {
        method: 'POST',
        body: JSON.stringify({
            arm_cn: currentFactoryArmCn(),
            command,
            execute: true,
            confirmations: officialDemoConfirmations(),
        })
    });
    state.officialDemoCommandResult = payload;
    renderOfficialCommandResults();
    await refreshFactoryOverview();
    addLog(`官方 Demo 命令执行状态: ${payload.command_run.status}`, payload.command_run.status === 'passed' ? 'success' : 'warning', 'official_demo');
}

async function probeJoint() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const payload = await api('/api/device/probe-joint', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            joint_name: selectedDiagnosticJoint(),
            profile_id: document.getElementById('profileSelect').value,
            timeout_per_param: 0.4
        })
    });
    state.jointDiagnostic = { ...payload, test_type: '参数诊断' };
    renderJointDiagnostic();
    openTestingArea('joint');
    addLog(`单关节参数诊断完成: ${payload.joint_name}`, payload.passed ? 'success' : 'warning', 'probe_joint');
}

async function runJointLinkTest() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const payload = await api('/api/device/joint-link-test', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            joint_name: selectedDiagnosticJoint(),
            profile_id: document.getElementById('profileSelect').value,
            allow_enable: false,
            job_id: state.currentJobId,
        })
    });
    state.jointDiagnostic = { ...payload, test_type: '链路测试' };
    renderJointDiagnostic();
    openTestingArea('joint');
    addLog(`单关节链路测试完成: ${payload.joint_name}`, payload.passed ? 'success' : 'warning', 'link_test');
}

async function runArmStatusCheck() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    openTestingArea('scan');
    renderArmRuntimeBusy('正在执行整臂状态复核...');
    const payload = await api('/api/device/arm-status-check', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            profile_id: document.getElementById('profileSelect').value,
        })
    });
    renderArmRuntimeCheck(payload);
    addLog(`整臂状态复核完成，在线 ${payload.summary.total_present}/${payload.summary.total_expected}`, payload.ok ? 'success' : 'warning', 'arm_status_check');
}

async function runArmTimeoutStandardization() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    openTestingArea('scan');
    renderArmRuntimeBusy('正在按 Profile 执行整臂 TIMEOUT 标准化...');
    const payload = await api('/api/device/arm-timeout-standardization', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            profile_id: document.getElementById('profileSelect').value,
            save_flash: true,
            confirmed: true,
        })
    });
    state.armTimeoutStandardizationResult = payload;
    renderArmRuntimeCheck(payload);
    const timeoutValues = Object.values(payload.timeout_targets || {});
    const timeoutSummary = timeoutValues.length && timeoutValues.every((value) => value === timeoutValues[0])
        ? `J1-J8=${timeoutValues[0]}`
        : '按当前 Profile 分级值';
    addLog(`TIMEOUT 标准化完成（${timeoutSummary}），通过 ${payload.summary.passed}/${payload.summary.total_expected}，保存 Flash ${payload.save_flash ? '已执行' : '未执行'}`, payload.ok ? 'success' : 'warning', 'arm_timeout_standardization');
}

async function runArmSafeEnableCheck() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    openTestingArea('scan');
    renderArmRuntimeBusy('正在执行工程短时使能检查...');
    const payload = await api('/api/device/arm-safe-enable-check', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            profile_id: document.getElementById('profileSelect').value,
            hold_ms: 300,
        })
    });
    renderArmRuntimeCheck(payload);
    addLog(`工程短时使能检查完成，通过 ${payload.summary.passed}/${payload.summary.total_expected}，自动失能 ${payload.summary.all_disabled_after_check ? '通过' : '异常'}`, payload.ok ? 'success' : 'warning', 'arm_enable_check');
}

async function runJointMicroResponseTest() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const payload = await api('/api/device/joint-micro-response-test', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            joint_name: selectedDiagnosticJoint(),
            profile_id: document.getElementById('profileSelect').value,
            q_offset: 0.02,
            kp: 6.0,
            kd: 0.12,
            dwell_ms: 120,
            job_id: state.currentJobId,
        })
    });
    state.jointDiagnostic = { ...payload, test_type: '极小幅响应测试' };
    renderJointDiagnostic();
    openTestingArea('joint');
    addLog(`单关节极小幅响应测试完成: ${payload.joint_name}`, payload.passed ? 'success' : 'warning', 'micro_test');
}

async function scanDevice() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const payload = await api('/api/device/scan', {
        method: 'POST',
        body: JSON.stringify({
            device_session_id: state.sessionId,
            job_type: document.getElementById('jobType').value,
            profile_id: document.getElementById('profileSelect').value,
            current_id: document.getElementById('expertMode').checked ? Number(document.getElementById('manualCurrentId').value || 0) : null,
            expert_mode: document.getElementById('expertMode').checked,
            repeat_count: Number(document.getElementById('scanRepeatCount').value || 1),
            repeat_delay_ms: 120
        })
    });
    state.scanResults = payload;
    renderScanResults();
    openTestingArea('scan');
    if (payload.scan_mode === 'can2_scan_inventory_and_profile_match') {
        addLog(
            `扫描完成，在线 ${payload.summary.total_present}/${payload.summary.total_expected}，不一致 ${payload.summary.total_mismatches}，意外节点 ${payload.summary.total_unexpected}，波动关节 ${payload.summary.stability?.flaky_joint_count ?? 0}`,
            payload.summary.passed ? 'success' : 'info',
            'scan'
        );
    } else if (payload.scan_mode === 'can2_acceptance_preview') {
        addLog(
            `验收预扫描完成，结论 ${payload.summary.release_decision}，缺失 ${payload.summary.total_missing}，不一致 ${payload.summary.total_mismatches}`,
            payload.summary.release_ready ? 'success' : 'warning',
            'acceptance'
        );
    } else if (payload.summary) {
        addLog(`扫描完成，发现 ${payload.summary.detected} 个对象，冲突 ${payload.summary.conflicts} 个`, payload.summary.passed ? 'success' : 'info', 'scan');
    } else {
        addLog(`扫描完成，发现 ${payload.candidates.length} 个对象`, 'success', 'scan');
    }
}

async function createJob() {
    if (!state.sessionId) {
        throw new Error('请先连接设备');
    }
    const jobType = document.getElementById('jobType').value;
    const profileId = document.getElementById('profileSelect').value;
    const targetJoint = document.getElementById('targetJoint').value;

    const payload = await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({
            job_type: jobType,
            device_session_id: state.sessionId,
            profile_id: profileId,
            target_joint: targetJoint,
            expert_mode: document.getElementById('expertMode').checked
        })
    });

    state.currentJobId = payload.job_id;
    addLog(`任务已创建: ${payload.job_id}`, 'success', 'job');

    if (isSingleParameterTask(jobType)) {
        await api(`/api/jobs/${state.currentJobId}/apply-profile`, {
            method: 'POST',
            body: JSON.stringify({
                target_joint: targetJoint,
                profile_id: profileId,
                overrides: buildOverrides()
            })
        });
    }

    await refreshCurrentJob();
    switchPrimaryTab(preferredWorkbenchTab(jobType));
}

async function refreshCurrentJob() {
    if (!state.currentJobId) {
        state.issuePayload = null;
        renderComparison();
        renderActionStates();
        renderMeta();
        renderReport();
        renderLineInventory();
        renderIssues();
        return;
    }
    const payload = await api(`/api/jobs/${state.currentJobId}`);
    state.currentJob = payload;
    await refreshIssues();
    renderMeta();
    renderSteps();
    renderExecuteMode();
    renderComparison();
    renderActionStates();
    renderReport();
}

async function writeParams() {
    await api(`/api/jobs/${state.currentJobId}/write-params`, {
        method: 'POST',
        body: JSON.stringify({ target_config: collectTargetConfig() })
    });
    addLog('参数写入完成，电机已保持失能；请先执行回读校验，通过后再保存 Flash 或继续后续步骤。', 'success', 'write');
    await refreshCurrentJob();
}

async function verifyParams() {
    const payload = await api(`/api/jobs/${state.currentJobId}/verify-params`, { method: 'POST' });
    addLog(payload.verified ? '回读校验通过' : '回读校验失败', payload.verified ? 'success' : 'error', 'verify');
    await refreshCurrentJob();
}

async function saveFlash() {
    await api(`/api/jobs/${state.currentJobId}/save-flash`, { method: 'POST' });
    addLog('参数已保存到 Flash', 'success', 'save');
    await refreshCurrentJob();
}

async function zeroMotor() {
    await api(`/api/jobs/${state.currentJobId}/zero`, {
        method: 'POST',
        body: JSON.stringify({ confirmed: true })
    });
    addLog('零位流程执行完成', 'success', 'zero');
    await refreshCurrentJob();
}

async function runTest() {
    const jobType = document.getElementById('jobType').value;
    const repeatCount = Number(document.getElementById('scanRepeatCount').value || 1);
    const endpoint = isSingleCommCheck(jobType)
        ? `/api/jobs/${state.currentJobId}/run-comm-check`
        : isArmAcceptance(jobType)
            ? `/api/jobs/${state.currentJobId}/run-arm-acceptance`
        : isArmVerification(jobType)
            ? `/api/jobs/${state.currentJobId}/run-arm-scan`
            : `/api/jobs/${state.currentJobId}/test`;
    const payload = await api(endpoint, {
        method: 'POST',
        body: JSON.stringify({ confirmed: true, repeat_count: repeatCount, repeat_delay_ms: 120 })
    });
    if (isArmVerification(jobType)) {
        state.scanResults = {
            candidates: payload.metrics.joints || [],
            summary: payload.metrics.summary,
            scan_mode: isArmAcceptance(jobType) ? 'can2_acceptance_preview' : 'can2_scan_inventory_and_profile_match'
        };
        renderScanResults();
    }
        addLog(
        isArmAcceptance(jobType)
            ? `整臂验收执行完成，结论 ${payload.metrics.summary?.release_decision || (payload.tested ? 'PASS' : 'HOLD')}`
            : isArmVerification(jobType)
                ? '通信扫描执行完成'
                : isSingleCommCheck(jobType)
                    ? '通信校验执行完成'
                    : isSingleParamConfig(jobType)
                        ? '参数配置任务已完成'
                    : '测试流程执行完成',
        payload.tested ? 'success' : 'warning',
        'test'
    );
    await refreshCurrentJob();
    const reportPayload = await api(`/api/jobs/${state.currentJobId}/report`);
    renderReport(reportPayload);
    switchPrimaryTab('reportTab');
}

async function refreshReport() {
    if (!state.currentJobId) {
        return;
    }
    const payload = await api(`/api/jobs/${state.currentJobId}/report`);
    renderReport(payload);
    addLog('报告已刷新', 'info', 'report');
}

function renderIssues() {
    const summary = document.getElementById('issuesSummary');
    const list = document.getElementById('issuesList');
    const detail = document.getElementById('issueDetailCard');
    const playbooks = document.getElementById('issuePlaybooks');
    if (!state.currentJobId || !state.issuePayload) {
        summary.className = 'summary-grid empty-state';
        summary.textContent = '创建并执行任务后显示问题摘要';
        list.className = 'result-list empty-state';
        list.textContent = '暂无问题明细';
        detail.className = 'comparison-card empty-state';
        detail.textContent = '点击左侧问题卡片查看详情';
        playbooks.className = 'artifact-list empty-state';
        playbooks.textContent = '当前还没有专项诊断建议';
        return;
    }

    const issues = state.issuePayload.issues || [];
    const selectedSeverity = document.getElementById('issueSeverityFilter').value;
    const filtered = selectedSeverity === 'all'
        ? issues
        : issues.filter(item => item.severity === selectedSeverity);
    summary.className = 'summary-grid';
    summary.innerHTML = [
        ['总问题数', state.issuePayload.summary.total],
        ['Critical', state.issuePayload.summary.critical],
        ['Warning', state.issuePayload.summary.warning],
        ['Info', state.issuePayload.summary.info],
        ['阻断项', state.issuePayload.summary.has_blocking ? 'YES' : 'NO']
    ].map(([label, value]) => `
        <div class="summary-card">
            <div class="status-label">${label}</div>
            <div class="status-value">${value}</div>
        </div>
    `).join('');

    if (!filtered.length) {
        list.className = 'result-list empty-state';
        list.textContent = '当前过滤条件下没有问题。';
        detail.className = 'comparison-card empty-state';
        detail.textContent = '当前没有可查看的问题详情。';
    } else {
        if (state.selectedIssueIndex >= filtered.length) {
            state.selectedIssueIndex = 0;
        }
        list.className = 'result-list';
        list.innerHTML = filtered.map((item, index) => `
            <button class="issue-card ${item.severity} ${index === state.selectedIssueIndex ? 'active' : ''}" data-issue-index="${index}">
                <div class="issue-card-head">
                    <strong>${item.title}</strong>
                    <span class="issue-badge ${item.severity}">${item.severity.toUpperCase()}</span>
                </div>
                <div>${item.scope}</div>
                <div class="muted">${item.message}</div>
            </button>
        `).join('');

        list.querySelectorAll('[data-issue-index]').forEach(button => {
            button.addEventListener('click', () => {
                state.selectedIssueIndex = Number(button.dataset.issueIndex);
                renderIssues();
            });
        });

        const selected = filtered[state.selectedIssueIndex];
        detail.className = 'comparison-card kv-list';
        detail.innerHTML = [
            ['标题', selected.title],
            ['级别', selected.severity],
            ['范围', selected.scope],
            ['说明', selected.message],
            ['Detected', selected.detected_value ?? '-'],
            ['Expected', selected.expected_value ?? '-'],
            ['建议', selected.recommended_action]
        ].map(([label, value]) => kvRow(label, value)).join('');
    }

    const playbookItems = state.issuePayload.playbooks || [];
    if (!playbookItems.length) {
        playbooks.className = 'artifact-list empty-state';
        playbooks.textContent = '当前还没有专项诊断建议';
        return;
    }
    playbooks.className = 'artifact-list';
    playbooks.innerHTML = playbookItems.map(item => `
        <div class="artifact-item playbook-card">
            <strong>${item.title}</strong>
            <div>适用范围: ${(item.applies_to || []).join(', ')}</div>
            <div class="muted">适用迹象: ${(item.when_to_use || []).join('；')}</div>
            <div class="muted">建议测试: ${(item.recommended_tests || []).join('；')}</div>
            <div><strong>处理建议:</strong> ${item.service_recommendation || '-'}</div>
        </div>
    `).join('');
}

async function refreshIssues() {
    if (!state.currentJobId) {
        state.issuePayload = null;
        renderIssues();
        return;
    }
    state.issuePayload = await api(`/api/jobs/${state.currentJobId}/issues`);
    renderIssues();
    openTestingArea('issues');
}

async function handleAction(fn) {
    try {
        await fn();
    } catch (error) {
        addLog(error.message, 'error', 'api');
    } finally {
        updateAllButtonsState();
    }
}

export async function startApp() {
    bindEvents({
        attachCurrentJobToArm,
        attachCurrentJobToMotor,
        assignFactoryJointMotor,
        bindArmIdentity,
        bindMotorIdentity,
        bringSystemCanDown,
        bringSystemCanUp,
        buildFactoryBundle,
        captureFactoryCanHealth,
        captureFactoryCandump,
        completeDemoWorkflowStep,
        completeZeroWorkflowStep,
        configureSystemCan,
        confirmSaveFlash,
        confirmWriteParams,
        confirmZeroMotor,
        connectDevice,
        createJob,
        disconnectDevice,
        executeConnectWorkflowPrimaryAction,
        executeFactoryWorkflowPrimaryAction,
        executeIdentifyWorkflowPrimaryAction,
        executeWorkflowPrimaryAction,
        failDemoWorkflow,
        failZeroWorkflow,
        finalizeDemoWorkflow,
        finalizeZeroWorkflow,
        generateArmReport,
        generateFactoryArmCn,
        generateFactoryMotorSn,
        generateMotorParameterReport,
        handleAction,
        lineInventoryAction: scanLineInventory,
        launchDmTool,
        planOfficialBaudrateChange,
        planOfficialDemoCommand,
        planOfficialMotorCheck,
        planOfficialZeroCommand,
        probeJoint,
        recordDemoValidation,
        recordZeroCalibration,
        refreshFactoryOverview,
        refreshInterfaces,
        refreshIssues,
        refreshReport,
        refreshVendorMaintenanceRecords,
        refreshVendorToolStatus,
        renderFactoryWorkflow,
        renderIssues,
        renderScopeAssumptions,
        renderSteps,
        renderTargetJoints,
        renderTransportForm,
        runArmSafeEnableCheck,
        runArmStatusCheck,
        runArmTimeoutStandardization,
        runFactoryReleaseGate,
        runJointLinkTest,
        runJointMicroResponseTest,
        runNativeZeroCalibration,
        runOfficialBaudrateChange,
        runOfficialDemoCommand,
        runOfficialMotorCheck,
        runOfficialZeroCommand,
        runTest,
        saveVendorMaintenanceRecord,
        saveFlashAction: saveFlash,
        scanDevice,
        startDemoWorkflow,
        startZeroWorkflow,
        syncFactoryMotorFromSelection,
        syncOfficialCommandFromJoint,
        syncSystemCanForm,
        validateFactorySerial,
        verifyParams,
        writeParamsAction: writeParams,
    });
    initSocket({
        addLog,
        refreshCurrentJob,
        renderInterfaceStatus,
        updateCanHealthStatus,
        updateLiveStatus,
    });
    renderLog();
    // Keep body[data-primary-flow] in sync from first paint: the wizard layout
    // (hidden task rail) depends on it, and nothing else sets it until a tab click.
    switchPrimaryTab(currentPrimaryTab());
    bindProblemModal();
    initSingleMotorWizard();
    initLinkWizard();
    initArmWizard();
    initReportArchive(refreshReport);
    initDiskMaintenance();
    try {
        await loadConfig();
        renderMeta();
        renderCapabilities();
        renderInterfaceStatus();
        renderComparison();
        renderReport();
        renderLineInventory();
        renderJointDiagnostic();
        renderExecuteMode();
        renderIssues();
        renderFactoryOverview();
        renderVendorMaintenance();
        await refreshInterfaces();
        await refreshFactoryOverview();
        await refreshOfficialCommands();
        await refreshVendorToolStatus();
        await refreshVendorMaintenanceRecords();
        addLog('工作站已加载，请先连接设备。', 'info', 'boot');
    } catch (error) {
        addLog(`配置加载失败: ${error.message}`, 'error', 'boot');
    }
}
