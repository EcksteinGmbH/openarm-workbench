---
title: OpenARM Workstation Versioning and Changelog
category: convention
tags:
  - openarm
  - workstation
  - versioning
  - changelog
  - release
  - factory-qa
sources:
  - VERSION:1
  - docs/WORKSTATION_CHANGELOG.md:3
  - docs/WORKSTATION_CHANGELOG.md:6
  - docs/WORKSTATION_CHANGELOG.md:8
  - docs/WORKSTATION_CHANGELOG.md:10
  - docs/WORKSTATION_CHANGELOG.md:11
  - docs/WORKSTATION_CHANGELOG.md:12
  - docs/WORKSTATION_CHANGELOG.md:13
  - docs/WORKSTATION_CHANGELOG.md:325
  - docs/WORKSTATION_CHANGELOG.md:338
  - docs/WORKSTATION_CHANGELOG.md:343
confidence: high
---

# OpenARM Workstation Versioning and Changelog

凡是会影响出厂测试、报告输出、硬件操作或操作员流程的 OpenARM 工站软件变更，都必须按影响级别更新 `VERSION` 和 `docs/WORKSTATION_CHANGELOG.md`，并记录验证证据与运行影响。

## Version Classification

- `MAJOR`：存在不兼容的工作流、报告契约或硬件控制变更。
- `MINOR`：新增出厂测试能力、修改报告模板、改变 UI 工作流或安全行为。
- `PATCH`：缺陷修复、文字/布局修正、数据映射修复或维护更新。
- 工站快速演进期间允许使用描述性 suffix，例如 `-factory-report` 或 `-left-timeout-unification`，但 suffix 不能替代语义版本级别判断。

## Changelog Entry Contract

- 标题采用 `x.y.z[-suffix] - YYYY-MM-DD`，并提供一句 Summary。
- `Changes` 记录可观察的行为或契约变化，不写会话流水账。
- `Verification` 记录具体测试命令、结果或真机检查证据；没有验证的猜测不应写成已完成变更。
- `Operational Notes` 说明硬件、安全、报告或操作员影响，尤其要标出参数写入、Flash 保存、运动和正式交付物变化。
- `VERSION:1` 与 changelog 的 `Current workstation version` 必须保持一致；发布检查应同时核对两处。

## Maintenance Notes

- 历史条目是变更证据，不是当前策略来源。TIMEOUT、追溯和报告规则应以最新条目及当前代码/Profile 为准，不能恢复旧版本中的互斥断言。
- 可复用的当前规则应沉淀到对应 durable Wiki，例如验收流程见 [[openarm-factory-arm-acceptance-flow]]，报告证据规则见 [[openarm-formal-report-evidence-selection]]；本页只维护版本与 changelog 写法。

## Provenance

### sources

- `VERSION:1`
- `docs/WORKSTATION_CHANGELOG.md:3`
- `docs/WORKSTATION_CHANGELOG.md:6`
- `docs/WORKSTATION_CHANGELOG.md:8`
- `docs/WORKSTATION_CHANGELOG.md:10`
- `docs/WORKSTATION_CHANGELOG.md:11`
- `docs/WORKSTATION_CHANGELOG.md:12`
- `docs/WORKSTATION_CHANGELOG.md:13`
- `docs/WORKSTATION_CHANGELOG.md:325`
- `docs/WORKSTATION_CHANGELOG.md:338`
- `docs/WORKSTATION_CHANGELOG.md:343`

### evidence

- `VERSION` 与 changelog 当前版本均为 `0.6.16-left-timeout-unification`。
- changelog 明确定义 MAJOR/MINOR/PATCH 分类、可选 suffix，以及 Summary/Changes/Verification/Operational Notes 条目结构。

### related_tasks

- None
