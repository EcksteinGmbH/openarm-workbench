import {
    isArmAcceptance,
    isArmVerification,
    isSingleCommCheck,
    isSingleParamConfig,
} from './job-types.js';
import { renderLog } from './log.js';
import { closeModal, showModal } from './modal.js';
import {
    switchExecuteTab,
    switchFactorySection,
    switchPrimaryTab,
    switchTestingSubtab,
} from './navigation.js';
import { state } from './store.js';

export function bindEvents(actions) {
    const {
        attachCurrentJobToArm,
        attachCurrentJobToMotor,
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
        lineInventoryAction,
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
        saveFlashAction,
        scanDevice,
        syncFactoryMotorFromSelection,
        syncOfficialCommandFromJoint,
        syncSystemCanForm,
        validateFactorySerial,
        verifyParams,
        writeParamsAction,
    } = actions;

    document.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', () => switchPrimaryTab(button.dataset.tab));
    });
    document.querySelectorAll('.subtab-button').forEach(button => {
        button.addEventListener('click', () => switchExecuteTab(button.dataset.subtab));
    });
    document.querySelectorAll('.testing-subtab-button').forEach(button => {
        button.addEventListener('click', () => switchTestingSubtab(button.dataset.testSubtab));
    });
    document.querySelectorAll('.factory-section-button').forEach(button => {
        button.addEventListener('click', () => switchFactorySection(button.dataset.factorySection));
    });

    document.getElementById('transportType').addEventListener('change', renderTransportForm);
    document.getElementById('jobType').addEventListener('change', () => {
        renderScopeAssumptions();
        renderSteps();
    });
    document.getElementById('profileSelect').addEventListener('change', renderTargetJoints);
    document.getElementById('factoryJointSelect').addEventListener('change', () => {
        syncFactoryMotorFromSelection();
        renderFactoryWorkflow();
    });
    document.getElementById('expertMode').addEventListener('change', renderScopeAssumptions);
    document.getElementById('issueSeverityFilter').addEventListener('change', () => {
        state.selectedIssueIndex = 0;
        renderIssues();
    });

    document.getElementById('connectBtn').addEventListener('click', () => handleAction(connectDevice));
    document.getElementById('connectWorkflowActionBtn').addEventListener('click', () => handleAction(executeConnectWorkflowPrimaryAction));
    document.getElementById('disconnectBtn').addEventListener('click', () => handleAction(disconnectDevice));
    document.getElementById('refreshInterfacesBtn').addEventListener('click', () => handleAction(refreshInterfaces));
    document.getElementById('systemCanName').addEventListener('change', () => syncSystemCanForm(document.getElementById('systemCanName').value));
    document.getElementById('systemCanMode').addEventListener('change', () => {
        document.getElementById('systemCanDbitrateField').classList.toggle('hidden', document.getElementById('systemCanMode').value !== 'canfd');
    });
    document.getElementById('canConfigureBtn').addEventListener('click', () => handleAction(configureSystemCan));
    document.getElementById('canUpBtn').addEventListener('click', () => handleAction(bringSystemCanUp));
    document.getElementById('canDownBtn').addEventListener('click', () => handleAction(bringSystemCanDown));
    document.getElementById('scanBtn').addEventListener('click', () => handleAction(scanDevice));
    document.getElementById('identifyWorkflowActionBtn').addEventListener('click', () => handleAction(executeIdentifyWorkflowPrimaryAction));
    document.getElementById('lineInventoryBtn').addEventListener('click', () => handleAction(lineInventoryAction));
    document.getElementById('armStatusCheckBtn').addEventListener('click', () => handleAction(runArmStatusCheck));
    document.getElementById('armTimeoutStandardizeBtn').addEventListener('click', () => {
        showModal(
            '确认按 Profile 写入整臂 TIMEOUT',
            '将按所选左右臂 Profile 逐关节执行 disable -> write TIMEOUT -> readback -> save Flash -> readback，不发送运动命令。请确认当前处于整臂验收阶段、急停/断电可用，并且当前 Profile 与接线一致。',
            () => handleAction(runArmTimeoutStandardization)
        );
    });
    document.getElementById('armSafeEnableCheckBtn').addEventListener('click', () => {
        showModal(
            '确认执行工程短时使能',
            '这是工程调试项，不属于 Leader 基础出厂必测。将逐关节短时 enable，并发送零力矩 MIT 保活帧，随后自动 disable。请确认空间安全、急停可用、当前 Profile 与接线一致。',
            () => handleAction(runArmSafeEnableCheck)
        );
    });
    document.getElementById('goArmWorkbenchBtn').addEventListener('click', () => switchPrimaryTab('staticAcceptanceTab'));
    document.getElementById('probeJointBtn').addEventListener('click', () => handleAction(probeJoint));
    document.getElementById('generateMotorReportBtn').addEventListener('click', () => handleAction(generateMotorParameterReport));
    document.getElementById('refreshVendorToolBtn').addEventListener('click', () => handleAction(refreshVendorToolStatus));
    document.getElementById('launchDmToolBtn').addEventListener('click', () => {
        showModal(
            '确认打开达妙上位机',
            '本按钮只打开厂家上位机，不会自动执行编码器校准、保存零点或写参数。请确认不会和当前工作站测试同时控制同一电机。',
            () => handleAction(launchDmTool)
        );
    });
    document.getElementById('saveVendorMaintenanceBtn').addEventListener('click', () => handleAction(saveVendorMaintenanceRecord));
    document.getElementById('syncOfficialCommandFromJointBtn').addEventListener('click', () => handleAction(syncOfficialCommandFromJoint));
    document.getElementById('planOfficialMotorCheckBtn').addEventListener('click', () => handleAction(planOfficialMotorCheck));
    document.getElementById('runOfficialMotorCheckBtn').addEventListener('click', () => {
        showModal(
            '确认执行官方 motor-check',
            '该命令用于 OpenARM 官方逐电机通信复核。请确认目标 CAN ID / Receiver ID 正确、接口已 UP、预期不发生机械动作。',
            () => handleAction(runOfficialMotorCheck)
        );
    });
    document.getElementById('planOfficialBaudrateBtn').addEventListener('click', () => handleAction(planOfficialBaudrateChange));
    document.getElementById('runOfficialBaudrateBtn').addEventListener('click', () => {
        showModal(
            '确认执行官方波特率变更',
            '该命令会写入电机通信参数。请确认当前只连接目标电机、接口处于 CAN 2.0、了解写入次数限制，并准备断电重上电复核。',
            () => handleAction(runOfficialBaudrateChange)
        );
    });
    document.getElementById('jointLinkTestBtn').addEventListener('click', () => {
        showModal('确认执行链路测试', '将对当前关节执行 enable -> disable 链路测试，不发送位置动作命令。', () => handleAction(runJointLinkTest));
    });
    document.getElementById('jointMicroTestBtn').addEventListener('click', () => {
        showModal('确认执行极小幅响应测试', '将对当前关节执行单关节极小幅 MIT 微动测试，测试后自动 disable。请确认机械无遮挡。', () => handleAction(runJointMicroResponseTest));
    });
    document.getElementById('createJobBtn').addEventListener('click', () => handleAction(createJob));
    document.getElementById('workflowActionBtn').addEventListener('click', () => handleAction(executeWorkflowPrimaryAction));
    document.getElementById('refreshIssuesBtn').addEventListener('click', () => handleAction(refreshIssues));
    document.getElementById('writeParamsBtn').addEventListener('click', confirmWriteParams);
    document.getElementById('verifyParamsBtn').addEventListener('click', () => handleAction(verifyParams));
    document.getElementById('saveFlashBtn').addEventListener('click', confirmSaveFlash);
    document.getElementById('refreshReportBtn').addEventListener('click', () => handleAction(refreshReport));
    document.getElementById('refreshFactoryBtn').addEventListener('click', () => handleAction(refreshFactoryOverview));
    document.getElementById('factoryWorkflowActionBtn').addEventListener('click', () => handleAction(executeFactoryWorkflowPrimaryAction));
    document.getElementById('generateArmCnBtn').addEventListener('click', () => handleAction(generateFactoryArmCn));
    document.getElementById('generateMotorSnBtn').addEventListener('click', () => handleAction(generateFactoryMotorSn));
    document.getElementById('bindArmCnBtn').addEventListener('click', () => handleAction(bindArmIdentity));
    document.getElementById('bindMotorSnBtn').addEventListener('click', () => handleAction(bindMotorIdentity));
    document.getElementById('assignJointMotorBtn').addEventListener('click', () => handleAction(actions.assignFactoryJointMotor));
    document.getElementById('attachCurrentJobToMotorBtn').addEventListener('click', () => handleAction(attachCurrentJobToMotor));
    document.getElementById('attachCurrentJobToArmBtn').addEventListener('click', () => handleAction(attachCurrentJobToArm));
    document.getElementById('startZeroWorkflowBtn').addEventListener('click', () => handleAction(actions.startZeroWorkflow));
    document.getElementById('completeZeroWorkflowStepBtn').addEventListener('click', () => handleAction(completeZeroWorkflowStep));
    document.getElementById('finalizeZeroWorkflowBtn').addEventListener('click', () => handleAction(finalizeZeroWorkflow));
    document.getElementById('failZeroWorkflowBtn').addEventListener('click', () => handleAction(failZeroWorkflow));
    document.getElementById('runNativeZeroCalibrationBtn').addEventListener('click', () => {
        showModal(
            '确认执行工站辅助静态零位',
            '本步骤只作为辅助静态写零位检查，不等同官方动态零位校准。请确认单臂 J1~J8 通信扫描已通过、机械臂已手动摆到 OpenARM 官方零位姿态、夹爪已闭合、工作空间清空且急停/断电可用。本步骤只发送 disable、set_zero、save，不发送动作控制命令。',
            () => handleAction(runNativeZeroCalibration)
        );
    });
    document.getElementById('planOfficialZeroBtn').addEventListener('click', () => handleAction(planOfficialZeroCommand));
    document.getElementById('runOfficialZeroBtn').addEventListener('click', () => {
        showModal(
            '确认受控执行官方动态零位校准',
            '官方零位校准会让机械臂自动运动。请确认 Step 1~3 已通过，工作空间已清空，急停/快速断电可用，机械臂已摆到官方零位姿态，并且当前只对单侧手臂执行。',
            () => handleAction(runOfficialZeroCommand)
        );
    });
    document.getElementById('startDemoWorkflowBtn').addEventListener('click', () => handleAction(actions.startDemoWorkflow));
    document.getElementById('completeDemoWorkflowStepBtn').addEventListener('click', () => handleAction(completeDemoWorkflowStep));
    document.getElementById('finalizeDemoWorkflowBtn').addEventListener('click', () => handleAction(finalizeDemoWorkflow));
    document.getElementById('failDemoWorkflowBtn').addEventListener('click', () => handleAction(failDemoWorkflow));
    document.getElementById('planOfficialDemoBtn').addEventListener('click', () => handleAction(planOfficialDemoCommand));
    document.getElementById('runOfficialDemoBtn').addEventListener('click', () => {
        showModal(
            '确认受控执行官方 Step 5 Demo',
            '官方 Demo 会使能电机并执行位置控制、力矩控制、夹爪控制和状态监测。请确认官方动态零位已经完成、通信验收通过、工作空间已清空、急停和快速断电可用。',
            () => handleAction(runOfficialDemoCommand)
        );
    });
    document.getElementById('recordZeroCalibrationBtn').addEventListener('click', () => handleAction(recordZeroCalibration));
    document.getElementById('recordDemoValidationBtn').addEventListener('click', () => handleAction(recordDemoValidation));
    document.getElementById('buildFactoryBundleBtn').addEventListener('click', () => handleAction(buildFactoryBundle));
    document.getElementById('captureCanHealthBtn').addEventListener('click', () => handleAction(captureFactoryCanHealth));
    document.getElementById('captureCandumpBtn').addEventListener('click', () => handleAction(captureFactoryCandump));
    document.getElementById('runReleaseGateBtn').addEventListener('click', () => handleAction(runFactoryReleaseGate));
    document.getElementById('generateZeroReportBtn').addEventListener('click', () => handleAction(() => generateArmReport('zero')));
    document.getElementById('generateSafetyReportBtn').addEventListener('click', () => handleAction(() => generateArmReport('safety')));
    document.getElementById('generateFactoryAcceptanceReportBtn').addEventListener('click', () => handleAction(() => generateArmReport('factory')));
    document.getElementById('generateFactoryAcceptanceReportArchiveBtn').addEventListener('click', () => handleAction(() => generateArmReport('factory')));
    document.getElementById('factoryArmCn').addEventListener('change', () => handleAction(() => validateFactorySerial('arm_cn', document.getElementById('factoryArmCn').value.trim())));
    document.getElementById('factoryMotorSn').addEventListener('change', () => handleAction(() => validateFactorySerial('motor_sn', document.getElementById('factoryMotorSn').value.trim())));
    ['factoryArmCn', 'factoryMotorSn', 'factoryArmType', 'factoryBomProfile', 'factoryMotorType', 'factoryEscId', 'factoryMstId', 'factorySerialRole', 'factorySerialDate', 'factorySerialSequence', 'factoryZeroScope', 'factoryZeroStatus', 'factoryZeroPoseName', 'factoryZeroOperator', 'factoryZeroNotes', 'factoryDemoScope', 'factoryDemoStatus', 'factoryDemoName', 'factoryDemoOperator', 'factoryDemoCommand', 'factoryDemoNotes']
        .forEach(id => {
            const node = document.getElementById(id);
            if (node) {
                node.addEventListener('input', renderFactoryWorkflow);
                node.addEventListener('change', renderFactoryWorkflow);
            }
        });

    document.getElementById('zeroBtn').addEventListener('click', confirmZeroMotor);
    document.getElementById('testBtn').addEventListener('click', () => {
        const jobType = document.getElementById('jobType').value;
        const scanOnly = isArmVerification(jobType);
        const commCheckOnly = isSingleCommCheck(jobType);
        const paramConfigOnly = isSingleParamConfig(jobType);
        showModal(
            isArmAcceptance(jobType) ? '确认执行整臂 CAN2.0 验收'
                : scanOnly ? '确认执行 CAN2.0 通信扫描'
                : commCheckOnly ? '确认执行通信校验'
                : paramConfigOnly ? '确认完成参数配置'
                : '确认执行 safe_mit_ping',
            isArmAcceptance(jobType)
                ? '将进行整臂总线盘点、参数一致性校验，并给出 PASS / HOLD 放行结论。'
                : scanOnly ? '将只进行总线扫描、参数读取和 ID 对账，不会发送动作控制帧。'
                : commCheckOnly ? '将只进行参数读取和状态校验，不会发送动作控制帧。'
                : paramConfigOnly ? '将结束参数配置任务，生成报告与问题清单，不会发送动作控制帧。'
                : '请确认机械无遮挡且可以安全完成小幅动作测试。',
            () => handleAction(runTest)
        );
    });

    document.getElementById('modalCancelBtn').addEventListener('click', closeModal);
    document.getElementById('modalConfirmBtn').addEventListener('click', () => {
        const action = state.pendingModalAction;
        closeModal();
        if (action) {
            action();
        }
    });

    document.getElementById('clearLogBtn').addEventListener('click', () => {
        state.logEntries = [];
        renderLog();
    });
}
