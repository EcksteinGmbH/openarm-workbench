# agent_wiki — 本项目的跨 runtime 知识存储

在写任何页面之前先读本文件。这里是本地契约;它实现的方法论来自
Eckstein workbench skills 的 typed-knowledge 生命周期。

这个存储存在的原因:Claude Code 和 Codex 会话都维护本项目,彼此看不见对方
的上下文。一个 runtime 确立、另一个 runtime 否则要重新推导的东西,都属于这里。

## 分层

| 路径 | 类型 | 存放 | 索引 | 提交 |
|---|---|---|---|---|
| `agent_wiki/*.md` | durable 工程知识 | 已验证、超出单个任务生命周期的事实 | 是,`scripts/wiki_reindex.py` | 是 |
| `agent_wiki/runtime/` | 运行态/工作层 | 跨 runtime 交接、尚未 durable 的发现 | 否 | 见 .gitignore(单 checkout 不提交;多 checkout 团队提交) |

## 兼容入口是入口,不是存储

```
.omc/wiki -> ../agent_wiki/runtime
```

符号链接**必须保持 tracked**(git mode 120000),克隆即复现布线。Claude 的
OMC `wiki_*` 工具经它写入中立存储;Codex 用 `rg` 读、直接写 Markdown。

**绝不**通过 `.omc/wiki/` 创建"独有"知识,**绝不**把符号链接换成真目录——
那会静默分叉存储,直到两个 runtime 对"已知"产生分歧才会暴露。

## 页面规则

- frontmatter 必填:`title`、`category`、`tags`、`sources`、`confidence`。
- `category` ∈ `architecture` / `decision` / `pattern` / `debugging` /
  `convention` / `reference` / `environment`。
- **不写 `session-log` 页**。时间序内容属于任务文档,不是知识。
- `sources` 写清页面为真的依据——脚本、命令输出、任务路径。没有 source 的
  页面是观点。
- `confidence: high` 需要拿得出手的证据;拿不准写 `medium` 并说明何以定案。
- 不放 secrets、客户数据、无界日志。

改完页面后:

```bash
python3 scripts/wiki_reindex.py agent_wiki     # 重建 index.md + frontmatter lint
```

## 晋升

`runtime/` 页面在**对当前证据复核通过**且**可复用于产生它的任务之外**时晋升:
写一个陈述规则、范围、证据的 durable 页,然后删除或标记 superseded 原工作页。
关闭的任务留下未晋升的工作态,是该任务的缺陷,不是存档。

## 查询纪律

wiki 命中是**假设,不是证据**——必须对当前代码/输出复核通过才能行动;
wiki 与代码冲突时以代码为准,并把该页记为更新候选。
