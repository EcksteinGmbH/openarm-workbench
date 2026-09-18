# OpenARM Workstation Changelog

This file records workstation-level software changes that can affect factory
testing, report output, hardware operation, or operator workflow.

Current workstation version: `0.10.2-wizard-rail-fix`

## Versioning Rule

- `MAJOR`: incompatible workflow, report, or hardware-control changes.
- `MINOR`: new factory-test capability, report template change, UI workflow change, or safety behavior change.
- `PATCH`: bug fix, wording/layout correction, data mapping fix, or maintenance update.
- Suffixes such as `-factory-report` may be used while the workstation is still evolving rapidly.

## Update Log

### 0.10.2-wizard-rail-fix - 2026-09-18

Summary: fixed the task rail reappearing on the wizard tabs after a page load or refresh.

Changes:

- The rails are hidden by CSS keyed on `body[data-primary-flow]`, but nothing set that attribute until the operator clicked a tab, so a fresh load of the default 准备建链 tab showed the engineer task rail next to the wizard. The template now ships `<body data-primary-flow="connectTab">`, so the wizard owns the full width from first paint.
- Boot now also calls `switchPrimaryTab(currentPrimaryTab())` so the attribute always matches the active tab, including when the active tab is restored by other code.
- Asset cache keys bumped so browsers pick up the corrected template and script.

Verification:

- `.venv/bin/python -m pytest -q`: 103 passed, including a new regression test that asserts the served page carries the default `data-primary-flow`, that both wizard rail-hiding selectors exist in the stylesheet, and that boot syncs the attribute.
- Server restarted; the served page and script contain both fixes.

Operational Notes:

- The task rail and live monitor remain available under 高级工具（工程师）on both wizard tabs.

### 0.10.1-advanced-tools-layout - 2026-09-18

Summary: reordered the engineer advanced tools into labelled sections that follow the actual work order; no behaviour change.

Changes:

- The single-motor advanced page is now five titled sections in workflow order: 参数写入与保存 (the existing step subtabs), 参数核对 (target vs. measured), 单关节诊断 (the joint test buttons together with their recent-result summary, previously split between the body and the side rail), 官方命令 (motor-check and baudrate change) and 报告与厂商维护 (motor report, DMTool, maintenance records).
- Each section header carries a one-line purpose note; the diagnostics header states that 参数诊断/链路测试 are read-only while 极小幅响应 moves the motor.
- The side rail keeps only the two cards that are context rather than tools: 电机工站建议 and 关联整臂任务.
- The link advanced page labels its manual connection area and marks the two transport forms (串口桥参数 / SocketCAN 参数).
- Any adapter Linux exposes as SocketCAN is reported by its real state; the previous "非 gs_usb 驱动" text no longer overrides a healthy non-gs_usb adapter (e.g. peak_usb).

Verification:

- `.venv/bin/python -m pytest -q`: 102 passed, including a new assertion that a healthy `peak_usb` CAN FD interface is reported as 正常.
- Markup check after the restructure: HTML tags balanced, no element id lost, added or duplicated (compared against the pre-change template), so all existing JS bindings keep working.
- Server restarted; the reordered sections render under 高级工具（工程师）.

Operational Notes:

- No tool was removed. Zero save, safe_mit_ping, 极小幅响应 and 受控执行 remain engineer-only and still move or write to the motor.

### 0.10.0-link-wizard - 2026-09-18

Summary: tab 01 is now a beginner link wizard with the same layout and troubleshooting behaviour as the single-motor wizard.

Changes:

- The connection tab leads with a four-step wizard (detect adapter -> configure and start the CAN port -> connect the workstation -> read-only bus check -> done), one primary button per step, a step rail, a per-step help panel and a live connection status chip.
- New backend endpoints `POST /api/link/wizard/detect|prepare|connect|bus-check|disconnect` and the matching `WorkstationService.link_wizard_*` methods. Detect lists every SocketCAN port with beginner-readable health, mode and bitrate text; prepare configures the port (CAN 2.0 1 Mbps by default, CAN FD 1M/5M optional) and brings it up; connect reuses an open session for the same port instead of stacking CAN sockets; the bus check is a read-only inventory of ESC IDs 0x01-0x20 that reports matched Profile joints, factory-default IDs, duplicate ESC IDs and faulted motors.
- Every failure returns a structured problem (title, cause, ordered fix steps, technical detail) and can be retried at the step that produced it. New catalog entries: `adapter_missing` (no CAN port at all, including the gs_usb firmware hint), `interface_prepare_failed` (with the exact `ip link` commands) and `bus_no_motor` (power, wiring, termination, wrong channel).
- No step writes motor parameters, enables a motor or sends a motion command.
- The previous manual connection form, interface list and system CAN configuration remain unchanged under "高级工具（工程师）".

Verification:

- `.venv/bin/python -m pytest -q`: 102 passed, including detect with no adapter, interface health text for an UP/DOWN port, prepare issuing the `ip link` sequence, connect reusing an existing session, disconnect closing it, a permission-denied prepare failure, an empty-bus check and joint matching on a populated bus.
- Live, 2026-09-18: with the adapter unplugged, all four endpoints returned the `adapter_missing` problem with operator guidance instead of a raw error. The happy path could not be re-run live because the adapter was disconnected; it remains to be walked through on hardware.

Operational Notes:

- Operators start here before any test; after re-plugging the adapter or restarting a CAN port, run the wizard again so the workstation opens a fresh CAN socket.
- The bus check is the fastest way to see whether a motor answers at all before opening the single-motor or whole-arm workflow.

### 0.9.0-single-motor-inspect - 2026-09-18

Summary: added a read-only motor parameter viewer to the single-motor page, so operators can look at what a motor carries without starting a commissioning job.

Changes:

- New "查看电机参数" button in the single-motor wizard header opens a read-only dialog: it scans ESC IDs 0x01-0x20 on the selected CAN port and shows, per answering motor, the communication identity (ESC_ID, MST_ID, control mode, bitrate, TIMEOUT), motor parameters (Gr, KT, PMAX, VMAX, TMAX), protection thresholds, versions and the raw SN register, plus live status, position and temperatures.
- New backend `POST /api/single-motor/inspect` and `WorkstationService.single_motor_inspect()`. The call only reads parameters and refreshes status: it never enables, writes, saves Flash or zeroes, and it creates no job and no record.
- The viewer reports the matched Profile joint for the motor's current ID pair, marks factory-default IDs, infers the motor family from the limit registers, and lists every motor on the bus instead of blocking when more than one answers; duplicate ESC IDs are called out.
- Failures reuse the operator troubleshooting catalog (missing adapter, interface down, bus error, connect failure, no motor found), so a read attempt explains the cause and the fix instead of failing silently.
- `can_br` display accepts both the raw register code and an already decoded bitrate; `TIMEOUT=0` is shown as not enabled.

Verification:

- `.venv/bin/python -m pytest -q`: 99 passed, including a service-level test asserting no write/enable/zero call and no job is created during inspection, ID-to-joint matching, display formatting, the multi-motor listing, and the API-level rows and problem envelope.
- Live hardware, 2026-09-18: read back a right-arm J8 motor on can0 (ESC 0x08 / MST 0x18, MIT, can_br code 4 = 1 Mbps, TIMEOUT 0, Gr 10.0, PMAX/VMAX/TMAX 12.5/30/10, DISABLED, no fault) using the same read path.

Operational Notes:

- The viewer is safe to use at any time, including on an already commissioned motor; it sends no motion or write command.
- Use it before commissioning to confirm which joint a motor is currently configured as, and after assembly to check a joint without creating a job.

### 0.8.0-single-motor-wizard - 2026-09-17

Summary: the single-motor page is now a beginner wizard with built-in troubleshooting, and loose-motor commissioning saves a traceable record instead of generating a per-motor report.

Changes:

- New operator wizard on the single-motor tab: choose product line (OpenArm 2.0 default / 1.0), arm side, joint and CAN port -> identify -> review current vs target parameters -> write and verify -> save Flash -> power cycle -> saved readback -> PASS. One primary button per step; the page never offers zero save or motion commands.
- New backend endpoints `GET /api/single-motor/wizard/options`, `POST /api/single-motor/wizard/identify`, `POST /api/single-motor/wizard/<job_id>/write|save|finish`, and `GET /api/single-motor/records`.
- Identify auto-starts the selected SocketCAN port at the requested bitrate when it is down or misconfigured (`sudo -n ip link`), scans ESC IDs 0x01-0x20, and blocks on no motor, multiple motors, fault status, unknown status codes or over-temperature before any job is created.
- Every wizard failure returns a structured problem (title, explanation, ordered fix steps, technical detail) from a single troubleshooting catalog; hardware exceptions are converted to an `unknown_error` problem instead of a raw 502. Retryable problems (CAN, identification, save, no answer after power cycle) can be retried in place; the finish step keeps the job retryable when the motor has not answered yet after the power cycle.
- A completed single-motor ID test (pass or fail) no longer writes `report.html`; it saves one immutable single-motor commissioning record per run under `artifacts/factory/single_motor_records/<record_id>.json` (target IDs, before/after readback, recorded TIMEOUT, firmware, final status, product line, joint, job reference, workstation version). These records are inputs for the later whole-arm factory report.
- The Damiao `SN` register is not unique per motor: during the 2026-09-17 live batch, four different factory-new motors all read `SN=1412444213`. It is stored only as raw `sn_register` evidence and never used as a motor identity. "Already configured" is judged from the IDs the motor currently carries (factory default MST_ID 0x00 vs. a Profile joint's ESC/MST pair). Legacy SN-grouped record files are split automatically into per-record files and the original is kept under `_legacy_by_sn/`.
- The wizard lists recent saved records. The completion card and records table show the post-power-cycle readback (ESC_ID, MST_ID, control mode, bitrate with raw `can_br` code, bus mode, TIMEOUT); new records also store these under `verified`.
- Identify shows the motor model check: Damiao motors expose no model register, so the family is inferred from the factory limit registers (PMAX/VMAX/TMAX, matched against the driver's `LIMIT_PARAM` table; Gr shown as evidence) and compared with the joint's Profile motor type. A mismatch or unknown result shows a warning and keeps "写入并校验" disabled until the operator confirms the nameplate. J3 (DM-J4340P) and J4 (DM-J4340) share limits and must be distinguished by nameplate. The check is stored in the record as `model_check`.
- "配置下一颗电机" advances to the next joint, and identify warns when the selected joint already has a PASS record from a different motor SN.
- The previous single-motor controls, official commands, diagnostics and vendor maintenance tools remain available unchanged under "高级工具（工程师）"; the left task rail and live monitor rail are hidden while the wizard is shown.

Verification:

- `.venv/bin/python -m pytest -q`: 96 passed, including two motors sharing an SN register value producing two separate records, legacy SN-grouped record migration, including motor model inference (DM8009 match, DM4310-on-J1 mismatch, DM4340 match, unreadable limits), wizard happy path (ID change, no motion/zero/write/save during finish, record content, no report.html, previous-record lookup), no-motor / multiple-motor blocking, fault blocking, retryable no-answer readback, readback drift failure record, and the API-level wizard flow with problem envelope.
- Headless Chromium walkthrough against a fake-driver server on port 5055: all five steps, the parameter-change highlight, the problem panel and the advanced-tools view rendered without page errors.
- Live hardware, 2026-09-17: R-J1, R-J2, L-J1 and L-J2 (four factory-new DM8009-family motors, all reporting SN register 1412444213) configured PASS; migrated to four separate records. First motor on can0 (CAN 2.0, 1 Mbps). MST_ID changed 0x00 -> 0x11, ESC_ID stayed 0x01, CTRL_MODE MIT, `can_br` code 4 (1 Mbps), TIMEOUT 0 recorded; saved readback after power cycle PASS with no motion.

Operational Notes:

- Operators should use the wizard; engineers use the advanced tools. Neither path saves a loose-motor zero by default.
- The whole-arm factory report does not yet read `single_motor_records`; linking those records into the final report is a follow-up.

### 0.7.0-single-saved-readback - 2026-09-17

Summary: loose-motor ID commissioning now completes with a no-motion saved-parameter readback instead of zero save and a motion ping.

Changes:

- Default (non-expert) single-motor ID jobs no longer offer `zero`; the backend rejects zero save unless the job is an expert `single_id_config` job, enforcing `single_motor_zero_save_default=False`.
- After `save_flash`, the `test` action runs a `saved_readback` check: it reads back ESC_ID, MST_ID, CTRL_MODE, can_br and the other target fields plus motor status, never enables the motor or sends motion frames, and passes the job with a report only when readback matches and the motor is fault-free, disabled and within temperature limits.
- `safe_mit_ping` (absolute `q=0.05 -> 0` MIT command) is only reachable from the `zeroed` state of an expert job, so an un-zeroed motor is never driven toward absolute zero.
- A failed single-motor test now also writes the job report for traceability.
- `run_comm_check` on a saved single-motor ID job previously dispatched to the motion ping; it now resolves to the same no-motion saved readback.
- Single-motor ID target configs report `requires_zero=False` and `test_profile=saved_readback`.
- UI: the single-motor step bar, execute panel, primary workflow action and confirmation dialog show the saved-readback step (with a power-cycle-before-readback hint); the zero button is hidden for non-expert jobs; the write-params hint no longer claims TIMEOUT is written.

Verification:

- `.venv/bin/python -m pytest -q`: 90 passed, including new coverage for the no-motion default flow (no enable/MIT/zero/write/save calls during readback), the expert zero plus motion ping flow, a readback MST_ID drift failure, and the API-level flow (zero rejected, saved readback passes).
- `node --check web/static/js/app.js`: passed.
- Not yet verified on live hardware (no USB-CAN adapter attached on 2026-09-17).

Operational Notes:

- Loose-motor commissioning flow: write params -> readback verify -> save Flash -> (power cycle recommended) -> saved readback -> report. No zero is saved and no motion command is sent.
- Operational zero remains an assembled-arm step (official dynamic zero calibration). Expert zero on a loose motor is only for documented service fixtures with a known mechanical reference.

### 0.6.18-esc-id-ack-transition - 2026-09-01

Summary: eliminated false ESC ID write failures when a motor acknowledges with its newly assigned ID.

Changes:

- Serial and SocketCAN drivers temporarily recognize both the old and target ESC IDs while waiting for the parameter-write acknowledgement.
- A successful acknowledgement atomically updates the driver's motor mapping; a timeout removes the temporary target mapping and preserves the original identity.
- Added regression coverage for new-ID acknowledgements on both transports.

### 0.6.17-single-timeout-stage-guard - 2026-09-01

Summary: enforced the existing rule that operational TIMEOUT standardization belongs to assembled-arm acceptance, not loose-motor commissioning.

Changes:

- Non-expert single-motor ID/parameter jobs now keep the measured `TIMEOUT` as read-only evidence instead of inheriting the assembled-arm Profile target.
- Default single-motor writes are limited to communication identity fields; `TIMEOUT`, `Gr`, `KT_Value`, `PMAX`, `VMAX`, and `TMAX` require an explicit expert parameter-service job.
- The single-motor comparison UI labels `TIMEOUT` as a read-only record.
- Restored the live R-J1 under test from the mistakenly applied `TIMEOUT=5000` to its pre-test measured value `0`, with Flash save and readback verification.

### 0.6.16-left-timeout-unification - 2026-08-05

Summary: standardized the assembled left arm to the same TIMEOUT policy as the right arm.

Changes:

- The left-arm Profile now requires `TIMEOUT=5000` for L-J1 through L-J8.
- The commissioning policy and live checklist now expose J1-J8=`5000` for both arm sides.
- The TIMEOUT-only maintenance tool accepts repeatable exact joint-name filters, so scoped writes do not touch unrelated motors.
- The live L-J1 through L-J4 update followed `disable -> write -> readback -> save Flash -> readback`; the whole left arm then passed a no-motion readback at `5000`.

### 0.6.15-report-field-integrity - 2026-08-05

Summary: made formal-report test rows and snapshots traceable to their actual measurement stages.

Changes:

- The Low-Gain Enable row now reads the independent same-CN, same-side low-gain record instead of reusing Demo counts.
- The pre-dynamic snapshot now comes only from the arm acceptance job; later motor-check recovery frames cannot be mislabeled as pre-dynamic data.
- TIMEOUT detail rows identify their adjustment evidence and no longer display unrelated static status/frame context from an earlier sample.
- Independent low-gain evidence is copied into the report bundle and included in the evidence hash manifest.

### 0.6.14-report-timeout-evidence - 2026-08-05

Summary: fixed formal-report TIMEOUT overlays for current write and power-cycle evidence formats.

Changes:

- Formal reports now accept passed timeout evidence that uses either `after_save` or power-cycle `timeout` fields.
- Evidence remains restricted to the same whole-arm CN and arm side; the latest passed per-joint value overrides an older static acceptance snapshot.
- Added a regression test proving a later right-arm `TIMEOUT=5000` power-cycle record supersedes an earlier `1000` record.

### 0.6.13-demo-flow-dedup - 2026-08-05

Summary: removed a duplicate post-zero motor-check stage and corrected per-joint motor type decoding.

Changes:

- The zero-calibration workflow now follows the live checklist: pre-zero motor-check, official dynamic zero, power-cycle verification, then Demo.
- Removed the duplicate post-zero `openarm-can-motor-check` step. Existing measured records remain unchanged and are treated as extra verification evidence.
- The safe motor-check wrapper now maps J1-J2 to DM8009, J3-J4 to DM4340, and J5-J8 to DM4310 for both arm ID ranges.
- Added regression coverage for the workflow step order and right/left motor type mapping.

### 0.6.12-right-arm-timeout5000 - 2026-08-05

Summary: synchronized the right-arm workstation policy with the live `OAF26080401` communication-watchdog correction.

Changes:

- Right-arm J1-J8 now require `TIMEOUT=5000`; the left-arm Profile keeps J1-J4=`1000` and J5-J8=`5000`.
- Dynamic readiness reads expected TIMEOUT values from the selected side-specific Profile instead of using hard-coded joint indices.
- API configuration, operator prompts, report guidance, and automated tests now expose the same side-specific policy.
- Live R-J1 through R-J4 values were written, saved to Flash, and independently verified after a power cycle; R-J5 through R-J8 remained at `5000` without redundant Flash writes.
- No motion command was used for the parameter correction or persistence verification.

### 0.6.11-traceability-readiness-sync - 2026-08-05

Summary: aligned optional motor identity handling and the no-motion dynamic readiness gate with the established whole-arm traceability and split TIMEOUT rules.

Changes:

- Reconfirmed from the factory specification and prior formal reports that only the whole-arm CN is required; motors are identified by their side/joint labels, while an internal per-motor traceability number is optional.
- Zero Damiao controller SN/HW readbacks remain preserved as measured values but no longer generate a warning or metadata note when no per-motor identity is assigned.
- Updated the no-motion dynamic readiness tool to require J1-J4 `TIMEOUT=1000` and J5-J8 `TIMEOUT=5000` instead of the obsolete all-joint `1000` rule.
- Control-critical parameter, state, position-stability, CAN, and script-safety checks remain unchanged.

### 0.6.10-metadata-classification - 2026-08-05

Summary: classified zero-valued Damiao controller SN/HW fields according to the factory traceability standard after a raw-frame comparison of R-J4, R-J5, and R-J6.

Changes:

- Confirmed R-J5 repeatedly returns literal zero payloads for RID `0x0F` (SN) and RID `0x0D` (HW); this is not a dropped frame or parser substitution.
- Zero SN/HW values are now retained as `sn_unprogrammed` and `hw_ver_unprogrammed` metadata notes instead of failing an otherwise healthy joint.
- Motor traceability remains strictly based on the matching whole-arm CN and joint label. The workstation does not synthesize or copy controller metadata from another motor.
- Control-critical fields remain blocking: ESC_ID, MST_ID, CTRL_MODE, CAN bitrate, TIMEOUT, online state, fault state, and temperature checks are unchanged.

### 0.6.9-arm-status-policy - 2026-08-05

Summary: corrected the read-only arm status gate after the first right-arm scan under the split TIMEOUT policy.

Changes:

- Read-only arm status checks now compare ESC_ID, MST_ID, control mode, CAN bitrate, and each joint's TIMEOUT against the selected Profile.
- A joint with a mismatched TIMEOUT can no longer be reported as passed merely because it is online, disabled, and fault-free.
- Zero-valued motor `SN` or `hw_ver` readbacks are retained as measured data and explicitly flagged for identity readback investigation.
- No motor parameter write or motion command is part of this status-check correction.

### 0.6.8-timeout-workflow-sync - 2026-08-04

Summary: enforced the current split TIMEOUT policy in the workstation control path, UI, API configuration, tests, and operator documentation.

Changes:

- The assembled-arm TIMEOUT action now reads each joint target from the selected Profile: J1-J4 use `1000`, and J5-J8 use `5000`.
- Removed the browser's hard-coded all-joint `1000` payload. The API now rejects obsolete scalar TIMEOUT overrides so an old client cannot silently overwrite J5-J8.
- The backend validates every Profile target before starting any motor write, then performs the existing disable, write, readback, Flash save, and final readback sequence per joint.
- `/api/config`, workstation guidance, report rules, and both active arm Profiles now expose the same current policy.
- Single-motor testing remains read-only for TIMEOUT by default. Formal reports continue to use measured values from the same arm CN and side rather than substituting Profile targets as measurements.

Verification:

- Added backend coverage for split per-joint writes and API coverage for current policy exposure and rejection of uniform overrides.

### 0.6.7-j4310-timeout-policy - 2026-08-04

Summary: synchronized the active J4310 timeout rule with the actual arm verification profiles after a clean live left-arm read-only scan exposed four stale template mismatches.

Changes:

- Updated the built-in OpenARM profile and code fallback so J1-J4 require `TIMEOUT=1000` and J5-J8 require `TIMEOUT=5000`.
- Both `openarm_right_arm_v1` and `openarm_left_arm_v1` now inherit the same current timeout rule during static acceptance and read-only arm scans.
- No motor parameters were rewritten during this correction; live `OAF26080401` already reported the intended J5-J8 value `5000`.
- Added profile assertions and updated scan fixtures so future changes cannot silently revert J5-J8 to `1000`.
- Formal report packaging now includes only the CAN health record selected for the current release decision, preventing an older superseded snapshot from remaining in the regenerated evidence bundle.

Verification:

- Live pre-fix scan found all eight left-arm joints online, disabled, healthy, with zero CAN errors/drops; its only four mismatches were the stale J5-J8 timeout expectations.
- `pytest -q tests/test_arm_can_scan_cli.py tests/test_workstation.py tests/test_web_api.py`: 71 passed.

### 0.6.6-report-audit - 2026-08-04

Summary: corrected formal report sign-off ownership, evidence evaluation, snapshot provenance, archive deduplication, and PDF readability after auditing `OAF26080401` against previous factory reports.

Changes:

- Restored the established sign-off defaults to test engineer `Peng Cheng` and project lead `Xiang Kun`; generic service labels such as `OpenARM workstation` and `OpenARM QA` are no longer accepted as person names.
- Added sign-off names and report revision to the structured report JSON for machine-readable traceability.
- CAN Health now requires ERROR-ACTIVE, 1 Mbps, interface up, zero RX/TX errors, and zero dropped frames. Existing evidence with `tx_dropped=10` correctly produces `WARNING` and a recapture action.
- TIMEOUT passes only when every measured joint value matches the same-arm expected/adjusted value; mere field presence no longer passes the gate.
- Zero-write PASS now numerically enforces the `0.020 rad` threshold and reports the maximum absolute readback. Near-guard stops such as L-J5 are preserved in the stop summary.
- Final Post-Demo Snapshot values now come from the matching Demo monitor and disable feedback instead of being copied from the static acceptance scan.
- Renamed the post-zero table to Post-Zero Recovery Snapshot to reflect that it is captured after restoring the initial physical pose.
- Motor model, control mode, and CAN baud fields are sourced from the matching profile/evidence instead of fixed report values.
- Formal report generation now rejects opposite-side command fallback and warns when required post-zero or post-Demo status samples are absent.
- Repeated generation of the same report ID replaces its arm archive reference instead of accumulating contradictory duplicate entries.
- PDF output suppresses local file-path headers/footers, keeps Sign-Off together, and prevents raw CAN frames from splitting across lines.

Verification:

- `pytest -q tests/test_workstation.py tests/test_web_api.py`: 70 passed.
- Focused integrity tests cover CAN dropped-frame warnings, numeric zero threshold enforcement, sign-off placeholder replacement, and Demo final-status extraction.

### 0.6.5-report-integrity - 2026-08-04

Summary: locked down formal factory report data integrity after live `OAF26080401` left-arm testing and R-J5 timeout investigation.

Changes:

- Updated the active workstation version to `0.6.5-report-integrity`.
- Formal factory reports now enforce strict same-arm data selection: the arm serial, requested side, requested `profile_id`, and linked `arm_acceptance` job must match before measured data can enter the report.
- Removed the previous global "latest passed job for profile" fallback from formal report generation. A report can no longer borrow data from another arm with the same profile.
- Added structured `missing_required_data` and `recommended_actions` to formal report API responses and JSON output. Missing required evidence now makes the report `WARNING` and tells the operator what to retest or what standard item to remove.
- Added a report "Data Completeness And Follow-Up" section to HTML/PDF output.
- Formal reports no longer fill measured/default motor parameter cells from nominal constants. Missing measured fields are rendered as `-` and listed as missing when they belong to the active report standard.
- ID values in formal reports are shown in hex format such as `0x05`, `0x0D`, and `0x1D`.
- TIMEOUT report overlay now reads same-arm timeout adjustment evidence and supports the live rule used on `OAF26080401`: J1-J4 remain `1000`; J5-J8 J4310 motors are `5000` after the same-arm evidence is present.
- Timeout evidence copying now skips invalid or empty JSON files so stale 0-byte evidence cannot enter the report hash manifest.
- Added `/api/config.report_data_policy` so AI-assisted workflows and browser-only workflows use the same integrity rules.
- Updated the workbench report UI to display final decision, missing required data, recommended actions, and the report data-source policy after report generation.

Verification:

- Syntax checked `src/workstation.py` and `src/formal_factory_report.py` with direct Python compilation.
- Regenerated `OAF26080401` left-arm formal report after attaching same-serial CAN health evidence.
- Confirmed report result is `PASS`, `missing_required_data=[]`, J5-J8 TIMEOUT values are `5000`, CAN health evidence is under `OAF26080401`, and evidence hashes include no 0-byte files.
- Confirmed workbench service restarted and `/api/config` exposes `workstation_version = 0.6.5-report-integrity`.

Operational Notes:

- Report templates may keep fixed section structure and wording, but measured values, status frames, parameter values, evidence paths, and PASS/WARNING decisions must come from the corresponding arm serial and side.
- If a required item was actually measured but not linked, attach or recapture same-serial evidence before final report generation.
- If a future test standard removes an item, remove it from the active report standard instead of emitting blank or fixed values.
- Right-arm `R-J5` remains on hold pending its separate issue resolution; the current PASS report is for `OAF26080401` left arm only.

### 0.6.4-factory-flow-sync - 2026-06-24

Summary: synchronized the latest live Follower right/left arm factory flow into the workstation so the next arm can follow the same steps from the UI.

Changes:

- Updated the active workstation version to `0.6.4-factory-flow-sync`.
- Added a controlled whole-arm `TIMEOUT=1000` standardization action to the static acceptance area.
- The new TIMEOUT action performs `disable -> write TIMEOUT -> readback -> save Flash -> readback` per joint and does not send motion commands.
- Kept loose single-motor ID commissioning separate from operational TIMEOUT standardization; TIMEOUT is standardized after assembled-arm static acceptance and before official zero/Demo.
- Formal factory reports now prefer the latest passed arm acceptance job for the requested arm side/profile so old failed pre-standardization scans do not contaminate final PASS reports.
- Formal zero parsing now treats successful official zero write/readback as pass even when initial-pose restore is performed as a separate evidence step.
- Preserved the current official zero defaults used in live testing: max bump `90 deg`, timeout `20 s`, velocity threshold `0.2 deg/s`, control step `0.005 s`, gripper skipped during zero, initial-pose restore enabled, restore max `120 deg`.
- Preserved the `L-J8` / CAN ID `0x10` special status-frame handling used during left-arm Demo validation.
- Confirmed `OAF26062401` Follower right-arm and left-arm final reports are PASS using the synchronized flow.

Verification:

- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache python3 -m py_compile src/workstation.py src/formal_factory_report.py web/app.py`
- `node --check web/static/js/app.js web/static/js/event-bindings.js web/static/js/store.js`
- Live `OAF26062401` right-arm factory report: `artifacts/reports/OAF26062401_right_arm_20260624/OpenARM_Follower_Right_Arm_Factory_Test_Report_20260624.pdf`
- Live `OAF26062401` left-arm factory report: `artifacts/reports/OAF26062401_left_arm_20260624/OpenARM_Follower_Left_Arm_Factory_Test_Report_20260624.pdf`

Operational Notes:

- Recommended assembled-arm order is now: static acceptance scan -> whole-arm TIMEOUT standardization when needed -> official dynamic zero -> restore initial pose -> official Demo -> formal report generation.
- The TIMEOUT standardization action is a parameter write/save action. Operators must still confirm correct side/profile, clear workspace, and available emergency stop or power cut before running it.

### 0.6.3-single-id-safety - 2026-06-22

Summary: locked in the current single-motor ID commissioning rule and fixed a Damiao status-frame parsing edge case found during live motor setup.

Changes:

- Updated the active workstation version to `0.6.3-single-id-safety`.
- Standardized the single-motor ID commissioning rule: write only communication-critical fields by default (`ESC_ID`, `MST_ID`, `CTRL_MODE`, `can_br`, and recorded `TIMEOUT=0` when required by the current ID setup flow).
- Kept `Gr`, `KT_Value`, `PMAX`, `VMAX`, and `TMAX` as read/record fields during single-motor ID setup unless an operator intentionally performs a separate parameter service step.
- Confirmed `TIMEOUT` remains read/record-only during loose-motor ID setup; OpenARM acceptance-stage standardization is handled later in the assembled-arm workflow.
- Fixed SocketCAN Damiao frame classification so status frames whose third payload byte equals `0x33` or `0x55` are not misclassified as parameter frames.
- Added a regression test for the L-J4 case where a valid status frame such as `0C5F557FF8001F1C` previously produced zero position/temperature feedback in the workstation.
- Reconfirmed left-arm `L-J8` with `ESC_ID=0x10` / `MST_ID=0x20` remains supported.

Verification:

- `./.venv/bin/python -m pytest tests/test_workstation.py::test_socketcan_status_payload_with_0x55_position_byte_is_not_param_frame tests/test_workstation.py::test_status_payload_reads_error_from_first_byte_not_position_byte tests/test_workstation.py::test_probe_joint_unknown_status_is_not_passed -q` -> `3 passed`
- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache ./.venv/bin/python -m py_compile src/damiao_motor_driver.py src/workstation.py`
- Live L-J4 retest after restart: `ESC_ID=0x0C`, `MST_ID=0x1C`, status frame `0C5F557FF7FD1F1C`, position `-3.1901 rad`, MOS/rotor `31/28 C`, no fault, CAN error counters `0`.
- Live single-motor ID commissioning completed for the current set: right arm `R-J1` to `R-J8` and left arm `L-J1` to `L-J8`.

Operational Notes:

- This update changes the workstation status-frame parser and the documented default single-motor ID commissioning rule.
- It does not add automatic Damiao vendor encoder calibration, output-shaft calibration, or loose-motor zero-save.
- Operators should continue using Damiao upper software or an approved fixture for vendor encoder/output-shaft calibration only when abnormal feedback or Damiao support guidance requires it.

### 0.6.2-vendor-maintenance - 2026-06-10

Summary: added safe Damiao DMTool integration for manual vendor maintenance records.

Changes:

- Added workstation API endpoints to report DMTool availability, launch the DMTool AppImage, and store manual vendor maintenance records.
- Added a single-motor page card for opening DMTool and recording motor encoder calibration, output shaft encoder calibration, and zero-save status.
- Stored vendor maintenance records under `artifacts/factory/vendor_maintenance/records`.
- Kept vendor encoder calibration as manual-record-only; the workstation still does not automatically execute encoder calibration or zero-save vendor actions.
- Updated web API tests to use temporary artifact directories so test runs do not touch real factory records.
- Kept arm-scan missing parameter reads as unknown matrix cells instead of reporting false parameter mismatches.
- Updated tests to reflect the current safe default that single-joint link tests are read-only unless enable is explicitly allowed.
- Removed obsolete one-off report generator scripts that could still emit old `Motor SN` / `Not assigned` report tables.
- Updated the V4 factory QA spec and UI wording to use optional internal motor trace IDs instead of required motor SN wording.
- Added `pytest.ini` so default test discovery only runs workstation tests and does not collect external OpenARM example scripts that require live `can0`.

Verification:

- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache python3 -m py_compile src/workstation.py web/app.py`
- `node --check web/static/js/app.js web/static/js/event-bindings.js web/static/js/store.js`
- `./.venv/bin/python -m pytest tests/test_web_api.py -q`
- `./.venv/bin/python -m pytest tests/test_web_api.py tests/test_workstation.py -q` -> `67 passed`
- `./.venv/bin/python -m pytest -q` -> `73 passed`
- Confirmed `/api/config` exposes `workstation_version = 0.6.2-vendor-maintenance`.

Operational Notes:

- This update does not change single-motor parameter writes, whole-arm scan, official zero calibration, Demo, or factory report PASS/FAIL gates.

### 0.6.1-calibration-policy - 2026-06-10

Summary: documented the Damiao encoder calibration, zero-save, and TIMEOUT policy without changing the active test flow.

Changes:

- Added `docs/DAMIAO_CALIBRATION_POLICY.md` to separate vendor encoder calibration, OpenARM zero save, and TIMEOUT standardization rules.
- Exposed a non-invasive `commissioning_policy` block through `/api/config` so the UI and reports can reference the current policy later.
- Clarified that single-motor ID commissioning should not routinely write `TIMEOUT` or save an operational arm zero.
- Clarified that whole-arm factory acceptance remains the stage for OpenARM `TIMEOUT` standardization, official dynamic zero calibration, and Demo.

Verification:

- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache python3 -m py_compile src/workstation.py`
- Confirmed `/api/config` data exposes `workstation_version = 0.6.1-calibration-policy` and the new `commissioning_policy` block.

Operational Notes:

- No motor-control sequence, endpoint behavior, report generation rule, or UI action gating was changed in this update.

### 0.6.0-factory-report - 2026-06-10

Summary: factory report format and traceability cleanup for the OpenARM Damiao workstation.

Changes:

- Added the workstation version file `VERSION`.
- Added this workstation changelog and versioning rule.
- Standardized the factory report rule that motor serial numbers are not reported; motors are identified by joint labels such as `R-J1` and `L-J1`.
- Separated acceptance-critical test items from recorded default motor configuration items.
- Ensured recorded default motor parameters do not appear as `RECORDED` results and do not affect PASS/FAIL acceptance gates.
- Corrected report model labels so `J3` is `DM-J4340P-2EC` and `J4` is `DM-J4340-2EC`.
- Regenerated the `OAF26060901` left-arm and right-arm factory reports with corrected model labels and formal report layout.
- Fixed the left-arm 2026-06-09 report regeneration path to avoid producing compact fallback PDFs as formal deliverables.
- Exposed the workstation version through the `/api/config` response as `workstation_version`.

Verification:

- `python3 -m py_compile src/formal_factory_report.py tools/generate_follower_left_factory_report_20260609.py tools/generate_follower_right_factory_report_20260610.py`
- Confirmed the left-arm report is a Chromium/Skia PDF, `PASS`, and contains no `Motor SN`, `Not assigned`, or `RECORDED` result fields.
- Confirmed the right-arm report lists `R-J3 = DM-J4340P-2EC` and `R-J4 = DM-J4340-2EC`.

Operational Notes:

- Snap Chromium may require `snapd.apparmor` to be running before formal PDF generation.
- Formal factory reports should fail or preserve the last valid formal PDF rather than silently replacing it with a fallback layout.

## Entry Template

### x.y.z[-suffix] - YYYY-MM-DD

Summary:

- Short purpose of the update.

Changes:

- Change 1.
- Change 2.

Verification:

- Command or test result.
- Manual check result, if applicable.

Operational Notes:

- Any hardware, safety, report, or operator impact.
