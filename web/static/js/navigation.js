import {
    isArmAcceptance,
    isArmVerification,
    isSingleCommCheck,
    isSingleCommissioning,
    isSingleParamConfig,
} from './job-types.js';

function primaryTabButton(tabId) {
    return document.querySelector(`.tab-button[data-tab="${tabId}"]`)
        || document.querySelector(`.tab-button[data-tab-target="${tabId}"]`)
        || document.querySelector('.tab-button[data-tab="connectTab"]');
}

export function switchPrimaryTab(tabId) {
    const activeButton = primaryTabButton(tabId);
    const targetPanelId = activeButton?.dataset.tabTarget || activeButton?.dataset.tab || tabId;
    document.body.dataset.primaryFlow = activeButton?.dataset.tab || targetPanelId;
    document.querySelectorAll('.tab-button').forEach(button => {
        button.classList.toggle('active', button === activeButton);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === targetPanelId);
    });
    if (activeButton?.dataset.testSubtab) {
        switchTestingSubtab(activeButton.dataset.testSubtab);
    }
    if (activeButton?.dataset.factorySection) {
        switchFactorySection(activeButton.dataset.factorySection);
    }
}

export function currentPrimaryTab() {
    return document.querySelector('.tab-button.active')?.dataset.tab || 'connectTab';
}

export function preferredWorkbenchTab(jobType = document.getElementById('jobType')?.value) {
    return isArmVerification(jobType) ? 'staticAcceptanceTab' : 'motorWorkbenchTab';
}

export function switchExecuteTab(subtabId) {
    document.querySelectorAll('.subtab-button').forEach(button => {
        button.classList.toggle('active', button.dataset.subtab === subtabId);
    });
    document.querySelectorAll('.subtab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === subtabId);
    });
}

export function switchTestingSubtab(subtabId) {
    document.querySelectorAll('.testing-subtab-button').forEach(button => {
        button.classList.toggle('active', button.dataset.testSubtab === subtabId);
    });
    document.querySelectorAll('.testing-subtab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === subtabId);
    });
}

export function switchFactorySection(sectionId) {
    document.querySelectorAll('.factory-section-button').forEach(button => {
        button.classList.toggle('active', button.dataset.factorySection === sectionId);
    });
    document.querySelectorAll('.factory-section-panel').forEach(panel => {
        panel.classList.toggle('active', panel.dataset.factorySectionPanel === sectionId);
    });
}

function visibleExecuteSubtabs(jobType) {
    if (isSingleCommissioning(jobType)) {
        return ['paramPanel', 'savePanel', 'zeroPanel', 'testPanel'];
    }
    if (isSingleParamConfig(jobType)) {
        return ['paramPanel', 'savePanel', 'testPanel'];
    }
    return ['testPanel'];
}

export function renderExecuteTabs(jobType) {
    const visible = new Set(visibleExecuteSubtabs(jobType));
    document.querySelectorAll('.subtab-button').forEach(button => {
        const isVisible = visible.has(button.dataset.subtab);
        button.classList.toggle('hidden', !isVisible);
    });
    document.querySelectorAll('.subtab-panel').forEach(panel => {
        panel.classList.toggle('hidden', !visible.has(panel.id));
    });

    const testTabButton = document.querySelector('.subtab-button[data-subtab="testPanel"]');
    if (testTabButton) {
        testTabButton.textContent = isArmAcceptance(jobType)
            ? '验收'
            : isArmVerification(jobType)
                ? '扫描'
                : isSingleCommCheck(jobType)
                    ? '校验'
                    : '测试';
    }

    const activeVisible = document.querySelector('.subtab-button.active:not(.hidden)');
    if (!activeVisible) {
        switchExecuteTab(visibleExecuteSubtabs(jobType)[0]);
    }
}
