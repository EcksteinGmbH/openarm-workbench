import { api } from './api.js';
import { addLog } from './log.js';
import { showModal } from './modal.js';

// Tab 04. It used to offer one button that said "use the current arm CN" without
// naming, showing or letting you choose that arm - the thing it acted on was hidden
// state. Looking a report up is what an operator actually comes here for, so the
// archive leads and generating follows the arm you picked.

const archive = {
    arms: [],
    armCn: null,
    busy: false
};

function esc(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

function selected() {
    return archive.arms.find(item => item.arm_cn === archive.armCn) || null;
}

function renderArms() {
    const target = document.getElementById('raArms');
    if (!archive.arms.length) {
        target.innerHTML = `
            <div class="aw-empty">
                <strong>还没有建档的机械臂</strong>
                <p class="muted">报告按整机编号归档。先到「03 整臂测试」为机械臂建档并完成测试，报告会出现在这里。</p>
            </div>`;
        return;
    }
    target.innerHTML = `
        <p class="muted aw-hint">报告按整机编号归档。选一台看它的报告。</p>
        <div class="aw-arm-list">
            ${archive.arms.map(item => `
                <button class="aw-arm ${item.arm_cn === archive.armCn ? 'selected' : ''}"
                    data-ra-arm="${esc(item.arm_cn)}" ${archive.busy ? 'disabled' : ''}>
                    <span class="aw-arm-cn">${esc(item.arm_cn)}</span>
                    <span class="aw-arm-meta">${esc(item.product_label)} · ${esc(item.arm_type || '-')}</span>
                    <span class="aw-arm-meta">${item.reports.length ? `${item.reports.length} 份报告` : '还没有报告'}</span>
                </button>`).join('')}
        </div>`;
}

function renderDetail() {
    const section = document.getElementById('raDetailSection');
    const target = document.getElementById('raDetail');
    const arm = selected();
    section.classList.toggle('hidden', !arm);
    if (!arm) {
        target.innerHTML = '';
        return;
    }
    target.innerHTML = `
        ${arm.reports.length ? `
            <table class="smw-table compact ra-table">
                <thead><tr><th>报告</th><th>生成时间</th><th>文件</th></tr></thead>
                <tbody>
                    ${arm.reports.map(report => `
                        <tr>
                            <td><strong>${esc(report.title || report.report_id)}</strong><br><small class="muted">${esc(report.report_id)}</small></td>
                            <td>${esc((report.generated_at || '-').replace('T', ' ').slice(0, 16))}</td>
                            <td>
                                ${report.html_available ? '<span class="ra-file ok">HTML</span>' : '<span class="ra-file missing">HTML 缺失</span>'}
                                ${report.pdf_available ? '<span class="ra-file ok">PDF</span>' : '<span class="ra-file missing">PDF 未生成</span>'}
                                ${report.directory ? `<br><small class="muted">${esc(report.directory)}</small>` : ''}
                            </td>
                        </tr>`).join('')}
                </tbody>
            </table>`
        : '<p class="muted">这台臂还没有正式出厂报告。</p>'}
        <div class="ra-generate">
            <div>
                <strong>为 ${esc(arm.arm_cn)} 生成正式出厂报告</strong>
                <p class="muted">只使用这台臂自己的测试记录：整臂验收、官方零位、Demo、原始帧和证据哈希。报告里会写明用的工作站版本、官方工具版本和夹爪控制模式。</p>
            </div>
            <button class="btn btn-warning" data-ra-generate="1" ${archive.busy ? 'disabled' : ''}>
                ${archive.busy ? '正在生成…' : '生成出厂报告'}
            </button>
        </div>`;
}

function renderCount() {
    const badge = document.getElementById('raCount');
    const total = archive.arms.reduce((sum, item) => sum + item.reports.length, 0);
    badge.textContent = total ? `共 ${total} 份报告` : '还没有报告';
}

function render() {
    renderCount();
    renderArms();
    renderDetail();
}

async function load() {
    try {
        const payload = await api('/api/reports/archive');
        archive.arms = payload.arms || [];
        if (!archive.arms.some(item => item.arm_cn === archive.armCn)) {
            // Land on an arm that actually has something to read.
            archive.armCn = (archive.arms.find(item => item.reports.length) || archive.arms[0])?.arm_cn || null;
        }
    } catch (error) {
        addLog(`报告归档：读取失败 ${error.message}`, 'error', 'report');
    }
    render();
}

function generate() {
    const arm = selected();
    if (!arm) return;
    // Writes a signed factory record, so it is confirmed rather than one click away.
    showModal(
        `为 ${arm.arm_cn} 生成出厂报告？`,
        `将按这台臂已有的测试记录生成正式出厂报告。缺少的数据会在报告里标注，不会用别的机械臂的数据填补。`,
        async () => {
            archive.busy = true;
            render();
            try {
                await api('/api/factory/reports/formal-factory-acceptance', {
                    method: 'POST',
                    body: JSON.stringify({ arm_cn: arm.arm_cn })
                });
                addLog(`报告归档：${arm.arm_cn} 出厂报告已生成`, 'success', 'report');
            } catch (error) {
                addLog(`报告归档：生成失败 ${error.message}`, 'error', 'report');
            } finally {
                archive.busy = false;
                await load();
            }
        }
    );
}

function handleClick(event) {
    if (archive.busy) return;
    const pick = event.target.closest('[data-ra-arm]');
    if (pick) {
        archive.armCn = pick.dataset.raArm;
        render();
        return;
    }
    if (event.target.closest('[data-ra-generate]')) generate();
}

export async function initReportArchive(refreshJobReport) {
    const root = document.getElementById('reportArchive');
    if (!root) return;
    root.addEventListener('click', handleClick);
    // One button refreshes the whole tab: the archive above and the engineer job
    // view below. Two handlers on the same button refreshed half of it each.
    document.getElementById('refreshReportBtn').addEventListener('click', async () => {
        await load();
        try {
            await refreshJobReport?.();
        } catch (error) {
            addLog(`报告归档：任务报告刷新失败 ${error.message}`, 'error', 'report');
        }
    });
    render();
    await load();
}
