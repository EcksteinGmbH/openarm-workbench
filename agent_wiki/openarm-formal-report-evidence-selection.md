---
title: OpenARM Formal Factory Report Evidence Selection
category: pattern
tags:
  - openarm
  - factory-report
  - evidence
  - traceability
  - pdf
  - acceptance
  - timeout
sources:
  - src/formal_factory_report.py:143
  - src/formal_factory_report.py:149
  - src/formal_factory_report.py:155
  - src/formal_factory_report.py:162
  - src/formal_factory_report.py:164
  - src/formal_factory_report.py:167
  - src/formal_factory_report.py:172
  - src/formal_factory_report.py:182
  - src/formal_factory_report.py:199
  - src/formal_factory_report.py:210
  - src/formal_factory_report.py:212
  - src/formal_factory_report.py:724
  - src/formal_factory_report.py:735
  - src/formal_factory_report.py:1229
  - src/formal_factory_report.py:1232
  - src/formal_factory_report.py:1241
  - src/formal_factory_report.py:1427
  - src/formal_factory_report.py:1445
  - src/workstation.py:1134
  - src/workstation.py:1136
  - src/workstation.py:1137
  - src/workstation.py:1138
  - src/workstation.py:1140
  - src/workstation.py:1141
  - docs/WORKSTATION_CHANGELOG.md:34
  - docs/WORKSTATION_CHANGELOG.md:35
  - docs/WORKSTATION_CHANGELOG.md:45
  - docs/WORKSTATION_CHANGELOG.md:46
  - docs/WORKSTATION_CHANGELOG.md:168
  - docs/WORKSTATION_CHANGELOG.md:169
  - docs/WORKSTATION_CHANGELOG.md:170
  - docs/WORKSTATION_CHANGELOG.md:172
  - docs/WORKSTATION_CHANGELOG.md:188
confidence: high
---

# OpenARM Formal Factory Report Evidence Selection

OpenARM 正式出厂报告只能采用同一整臂 CN、同侧、同 Profile 的已关联证据，并把 TIMEOUT 标准化、官方零位和 Demo 分阶段取证；缺失测量值必须显式告警，不能借用其他机械臂数据或用固定值填充。

## Evidence Selection Rules

- `_latest_job_payload()` 只接受 `arm_acceptance` job，并按目标 `profile_id` 过滤。
- 候选 job 会按 `status_rank` 和时间排序；`passed` job 的优先级高于 failed/warning 记录，避免早期失败扫描覆盖后来的合格验收。
- `_passed_command()` 在 command history 中查找指定 kind 和 side，并只返回 `status == "passed"` 的记录。
- `_timeout_adjustments()` 读取同一整臂 CN 下的 `timeout_adjustments` evidence，只接受同侧且 payload 通过的记录。
- TIMEOUT evidence 兼容 `timeout`、`after_save` 和 `target_timeout` 字段，便于报告同时读取写入保存记录和断电重启后的验证记录。

## Report Integrity Rules

- 报告入口要求 `arm_cn`，数据策略固定为 `strict_arm_serial_and_side`，禁止退回到同 Profile 的全局最新 job；`linked_jobs` 是整臂证据边界。
- 正式报告中的 pre-dynamic snapshot 应来自 arm acceptance job，而不是后续 motor-check recovery 或 Demo 阶段的帧。
- Low-Gain Enable、TIMEOUT detail、Zero 和 Demo 等行应各自读取对应 evidence，不应复用无关阶段的计数或帧。
- 如果某项只是记录默认参数，应作为记录项排版；不得用 `RECORDED` 字段冲击 PASS/FAIL 测试项。
- 缺少必需测量数据时，报告应输出结构化 `missing_required_data` 和 `recommended_actions` 并降为 WARNING；模板可以固定，但测量值、状态帧、参数和 PASS/WARNING 判定不能固定。
- 缺少的电机内部 SN 不应生成 warning；正式追溯以整臂 CN 加 joint label 为主。

## Formal PDF Contract

- 客户正式 PDF 必须由 Chromium/Skia 标准模板生成；默认 `allow_reportlab_fallback=False`。
- PDF 生成失败时仍保留 JSON/HTML 和 `pdf_error.txt`，同时返回 `pdf_generated=False`、`pdf_path=None`；不得用紧凑 fallback PDF 静默替换正式交付件。

## Maintenance Notes

- 生成或修复 PDF 时，优先检查 evidence selection，再看排版。很多“报告内容变少/出现旧错误”的根因是选错了 job 或用了旧 evidence。
- 如果新增测试阶段，应为该阶段新增独立 evidence 读取规则，避免从 Demo 或 static acceptance 的 summary 里借字段。
- 如果报告中出现旧失败 TIMEOUT 或旧位置数据，先检查 `linked_jobs` 顺序、job status、profile_id 过滤和 `timeout_adjustments` 同侧过滤。

## Provenance

### sources

- `src/formal_factory_report.py:143`
- `src/formal_factory_report.py:149`
- `src/formal_factory_report.py:155`
- `src/formal_factory_report.py:162`
- `src/formal_factory_report.py:164`
- `src/formal_factory_report.py:167`
- `src/formal_factory_report.py:172`
- `src/formal_factory_report.py:182`
- `src/formal_factory_report.py:199`
- `src/formal_factory_report.py:210`
- `src/formal_factory_report.py:212`
- `src/formal_factory_report.py:724`
- `src/formal_factory_report.py:735`
- `src/formal_factory_report.py:1229`
- `src/formal_factory_report.py:1232`
- `src/formal_factory_report.py:1241`
- `src/formal_factory_report.py:1427`
- `src/formal_factory_report.py:1445`
- `src/workstation.py:1134`
- `src/workstation.py:1136`
- `src/workstation.py:1137`
- `src/workstation.py:1138`
- `src/workstation.py:1140`
- `src/workstation.py:1141`
- `docs/WORKSTATION_CHANGELOG.md:34`
- `docs/WORKSTATION_CHANGELOG.md:35`
- `docs/WORKSTATION_CHANGELOG.md:45`
- `docs/WORKSTATION_CHANGELOG.md:46`
- `docs/WORKSTATION_CHANGELOG.md:168`
- `docs/WORKSTATION_CHANGELOG.md:169`
- `docs/WORKSTATION_CHANGELOG.md:170`
- `docs/WORKSTATION_CHANGELOG.md:172`
- `docs/WORKSTATION_CHANGELOG.md:188`

### evidence

- `_latest_job_payload()` implements status-ranked, time-ranked selection over same-profile `arm_acceptance` jobs.
- `_timeout_adjustments()` filters timeout evidence by same arm side and accepts only passed payloads, then extracts the latest per-joint value from `timeout`, `after_save`, or `target_timeout`.
- `0.6.15-report-field-integrity` and `0.6.14-report-timeout-evidence` changelog entries document prior report integrity fixes for stage-specific snapshots and TIMEOUT overlays.
- `/api/config.report_data_policy` 明确要求 arm serial、side 和 profile 严格匹配，禁用全局 latest-job fallback，并把缺失证据转为 WARNING 和补测建议。
- 正式报告 metadata 和失败路径都声明 Chromium/Skia 是正式 PDF 要求；默认生成失败只保留机器可读工件和错误说明，不生成 ReportLab 替代件。

### related_tasks

- None
