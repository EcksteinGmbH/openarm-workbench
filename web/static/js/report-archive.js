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
                <thead><tr><th>报告</th><th>生成时间</th><th>文件</th><th></th></tr></thead>
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
                            <td><button class="btn btn-ghost slim" data-ra-withdraw="${esc(report.report_id)}" ${archive.busy ? 'disabled' : ''}>撤回</button></td>
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

function withdraw(reportId) {
    const arm = selected();
    if (!arm) return;
    // A report issued against wrong or incomplete evidence is worse than none: it is a
    // signed statement about an arm. Withdrawing moves the files aside rather than
    // erasing them, because a report that may have left the building has to stay
    // reconstructable.
    showModal(
        '撤回这份报告？',
        `${reportId} 会从 ${arm.arm_cn} 的报告列表移除，文件移到 withdrawn_reports/ 备查，不会真正删除。撤回后可以重新生成。`,
        async () => {
            archive.busy = true;
            render();
            try {
                await api(`/api/reports/${encodeURIComponent(arm.arm_cn)}/${encodeURIComponent(reportId)}`, { method: 'DELETE' });
                addLog(`报告归档：${reportId} 已撤回`, 'info', 'report');
            } catch (error) {
                addLog(`报告归档：撤回失败 ${error.message}`, 'error', 'report');
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
    const withdrawBtn = event.target.closest('[data-ra-withdraw]');
    if (withdrawBtn) {
        withdraw(withdrawBtn.dataset.raWithdraw);
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

// ---- disk maintenance (engineer tools on tab 03) ---------------------------------
// Job directories accumulated with no way to clear them but by hand. Cleanup is bulk,
// so it shows what it would take first and never touches a directory anything cites.

let maintenanceBusy = false;

function renderMaintenance(payload) {
    const target = document.getElementById('mtResult');
    if (!target) return;
    if (!payload) {
        target.className = 'empty-state';
        target.textContent = '点「检查未关联任务」看看有多少可以清理';
        return;
    }
    const { unlinked, linked_count: linked, total_size_kb: size } = payload;
    target.className = '';
    if (!unlinked.length) {
        target.innerHTML = `<p class="muted">没有可清理的任务：${linked}个任务全部被记录引用着。</p>`;
        return;
    }
    target.innerHTML = `
        <p>可清理 <strong>${unlinked.length}</strong> 个任务目录，约 ${size} KB。另有 ${linked} 个被引用，不会动。</p>
        <table class="smw-table compact">
            <thead><tr><th>目录</th><th>类型</th><th>状态</th><th>大小</th></tr></thead>
            <tbody>${unlinked.slice(0, 20).map(job => `
                <tr><td>${esc(job.directory)}</td><td>${esc(job.job_type || '-')}</td>
                    <td>${esc(job.status || '-')}</td><td>${job.size_kb} KB</td></tr>`).join('')}
            </tbody>
        </table>
        ${unlinked.length > 20 ? `<p class="muted">…另有 ${unlinked.length - 20} 个未列出</p>` : ''}
        <div class="smw-actions">
            <button class="btn btn-warning" id="mtArchiveBtn" ${maintenanceBusy ? 'disabled' : ''}>
                ${maintenanceBusy ? '正在归档…' : `归档这 ${unlinked.length} 个任务`}
            </button>
            <span class="muted">移动到 artifacts/_archive_&lt;日期&gt;/jobs/，不会删除。</span>
        </div>`;
    document.getElementById('mtArchiveBtn')?.addEventListener('click', archiveUnlinked);
}

async function scanUnlinked() {
    try {
        renderMaintenance(await api('/api/maintenance/unlinked-jobs'));
    } catch (error) {
        addLog(`磁盘维护：检查失败 ${error.message}`, 'error', 'report');
    }
}

function archiveUnlinked() {
    showModal(
        '归档未关联任务？',
        '这些任务目录没有被任何机械臂档案或电机记录引用。它们会移动到 artifacts/_archive_<日期>/jobs/，不会删除，需要时可以移回来。',
        async () => {
            maintenanceBusy = true;
            try {
                const payload = await api('/api/maintenance/unlinked-jobs/archive', {
                    method: 'POST',
                    body: JSON.stringify({ confirmed: true })
                });
                addLog(`磁盘维护：已归档 ${payload.moved_count} 个任务到 ${payload.moved_to}`, 'success', 'report');
            } catch (error) {
                addLog(`磁盘维护：归档失败 ${error.message}`, 'error', 'report');
            } finally {
                maintenanceBusy = false;
                await scanUnlinked();
            }
        }
    );
}

export function initDiskMaintenance() {
    document.getElementById('mtScanBtn')?.addEventListener('click', scanUnlinked);
}
