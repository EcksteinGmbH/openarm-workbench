# OpenArm Cell 与零位校准夹具（官方摘录）

- 原始页面：https://docs.openarm.dev/hardware/openarm-cell/general/
- 仓库路径：`enactic/openarm` → `website/docs/hardware/openarm-cell/general.mdx`
- 抓取日期：2026-09-21

## Cell 是什么

> OpenArm Cell is developed to provide a standardized benchmark for accurately
> comparing and evaluating the performance of robotic foundation models.

不只是机械臂，而是**把灯光、相机、校准流程一并定义成一个统一系统**，目的是让模型评测可复现。
用 MISUMI 等通用型材搭外壳和电源系统，带可升降的 Z 轴。

## 零位校准夹具（本节是关键）

> OpenArm Cell also includes a **high-precision dedicated calibration jig** that
> secures the gripper in a fixed position and **physically constrains all degrees of
> freedom to their ideal CAD-defined angles**.
>
> By eliminating unavoidable assembly errors and component tolerances through
> calibration, it ensures a consistent data foundation...

**要点：**

- **夹具随 Cell 提供**（"Cell also includes"），不是单独售卖的配件。
- 作用是把全部自由度**物理约束到 CAD 理论角度**，用夹具精度抵消装配误差和零件公差。
- 这解释了为什么 2.0 零位**不需要运动**：姿态由夹具保证，软件只负责"把当前位置记成零"
  （`openarm-can-cli set_zero`，只发失能帧 + 置零帧）。

**对我们的意义**：2.0 的官方零位方式依赖这个夹具。没有夹具就没有 CAD 基准，
`set_zero` 记下来的只是"当时碰巧的姿态"，等于没校准。
→ **所以问题不是"零位怎么做"，而是"产线买不买 Cell"。**

## 图纸与 BOM

官方提供 3D CAD + BOM（含各零件采购信息），链接在 general 页：
Google Drive `1HzonRqvZ_1FZSTvcW09gT69bLr4alACN`

## 装机前要确认的硬指标

> each OpenArm Cell weighs approximately **100 kg** and consumes approximately
> **480 W**, plus the power required by the installed PC.

官方明确提醒要事先确认：

- 安装点的**供电容量**和**楼板承重**
- 从建筑入口到安装位置的**全部搬运通道**：门宽、门高、电梯尺寸

## 其他

**Reach-In Stop**：基于区域传感器的闯入检测，运行中有人进入工作区会自动断电。

## 夹具的机械安装步骤

见 `cell-calibration-workflow.md`（HNTP6-6 弹簧螺母 + M6 螺丝，套中心立柱，
末端座入椭圆槽、J7 座入圆槽，开始前确认所有关节都已固定不可动）。
