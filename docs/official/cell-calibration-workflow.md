# OpenArm Cell 校准夹具安装（官方摘录）

- 原始页面：https://docs.openarm.dev/hardware/openarm-cell/calibration-workflow
- 抓取日期：2026-09-21

## 所需物料

校准夹具，配 HNTP6-6 后插弹簧螺母和 M6 螺丝。

## 步骤

1. **放螺母**：在标记位置放入弹簧螺母，此时位置不用很准。
2. **插入夹具**：> "Slowly insert the jig so that it fits around the central column
   to which OpenArm is mounted."
3. **固定夹具**：用薄扳手把螺母对准夹具孔位，M6 螺丝拧紧。
4. **就位末端**：> "Place the base of the end effector into the oval-shaped recess,
   and place the bottom of the J7 motor into the circular recess."
5. **确认到位**：> "Confirm that all joints are secured and cannot move"
   —— 开始校准前必须确认所有关节都被固定住、动不了。

## 这一页只讲机械安装

官方这一页**不包含**任何命令、软件参数，也没说校准时机械臂会不会动。
实际的置零命令在 setup 教程里（见 `setup-tutorial.md` 第 2 节）：

```bash
openarm-can-cli -i can0 set_zero --arm
```

两页合起来才是完整流程：**夹具固定 → 确认关节不可动 → 原地清零（不运动）**。
