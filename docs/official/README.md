# 官方文档本地参照

`docs.openarm.dev` 的关键页面摘录，带抓取日期和原始链接。

## 为什么要存这一份

工作站的流程必须和官方一致，但官方内容分散在**两处**：

- **代码**：`enactic/openarm_can`（已归档在 `external/openarm_can_1.2.2` 和 `_1.4.0`）
- **文档**：`docs.openarm.dev`（就是这个目录）

只看代码会漏掉只写在文档里的东西。相机就是个例子：`openarm_can` 整个仓库
grep 不到任何相机代码，但官方 setup 教程里有完整的相机识别方案。
2026-09-21 因为只查了代码包，得出过"官方没有相机相关内容"的错误结论。

## 规矩

- 每份摘录顶部写明**原始 URL** 和**抓取日期**。
- 只记录影响工作站行为的内容：命令、参数、判据、顺序、硬件型号。不做全文镜像。
- 官方改版后重新抓取时，**保留旧版本并注明**，因为已出厂的臂是按当时的流程测的。
- 我们和官方有偏离的地方，在摘录里直接标出来，写清为什么。

## 目录

| 文件 | 覆盖 | 原始页面 |
|------|------|---------|
| `setup-tutorial.md` | 2.0 的 CAN 配置、零位、相机 | https://docs.openarm.dev/tutorial/setup |
| `cell-calibration-workflow.md` | 2.0 校准夹具的机械安装 | https://docs.openarm.dev/hardware/openarm-cell/calibration-workflow |
