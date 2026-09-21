# 验收阈值推导

官方没有公布的判据，在这里按"官方 + 真机 + 社区"推出来，**每个数都写清依据链和它推不到的地方**。

推导日期：2026-09-21

一手来源：

- https://docs.openarm.dev/ （官方文档站）
- `enactic/openarm` → `website/docs/dataset/dataset.mdx`、`website/docs/dataset/api.mdx`
- `external/openarm_can_1.4.0/`（本仓库已归档，commit f340d4b）
- 本工作站 17 条真机夹爪测量（`artifacts/reports/` 与 `artifacts/factory/arms/`）

---

## 1. 相机：≥30 fps @ ≥960×600

**这一条依据最硬，因为它不是"相机应该多好"，而是"数据管线需要多少"。**

### 依据链

官方数据集文档 `website/docs/dataset/dataset.mdx`，实际数据的示例输出：

```python
>>> [(name, img.load().shape) for name, img in samples[0].cameras.items()]
[('wrist_left', (600, 960, 3)), ('wrist_right', (600, 960, 3)),
 ('ceiling', (600, 960, 3)), ('head', (600, 960, 3))]
```

→ **四路相机全部 960×600**（`(H, W, 3)`）。

`website/docs/dataset/api.mdx`：

- `openarm_dataset` 转换 API 签名里 `fps: int = 30`
- 示例 `dataset.sample(hz=30, episode_index=0)`

→ **重采样目标 30 Hz**。

### 为什么"低于 30 fps"是必须拦的缺陷

`Dataset.sample` 的对齐方式（api.mdx 原文）：

> For each modality the *previous-or-equal* element by timestamp is selected
> via `np.searchsorted`

**不插值、无容差**。相机掉到 30 fps 以下时，`sample(hz=30)` 会**静默重复上一帧**——
不报错、不警告，数据集看起来完整，实际含重复帧。

**这种缺陷装机之后发现不了，只能在出厂时拦。**

### 建议判据

| 项 | 值 | 依据 |
|---|---|---|
| 分辨率 | ≥ 960×600 | 官方数据集实际尺寸 |
| 帧率 | ≥ 30 fps **持续** | 官方重采样频率 |
| 单帧最大间隔 | ≤ 33.3 ms（1/30 s） | 超过即产生重复帧 |
| 测试时长 | ≥ 30 s | 短窗口测不出偶发掉帧 |
| 丢帧 | 窗口内 0 次超时 | 同上 |

**推不到的**：官方没给清晰度/对焦/白平衡判据，那些和具体相机型号绑定
（我们的 BOM 是夹爪 DCXGW20 或 D405、顶部 D435i），需要你们按镜头定。

---

## 2. 2.0 夹爪行程阈值：建议 1.20 rad（**外推，非实测**）

### 1.0 的真实分布（17 条测量，两台 Leader + 多台 Follower）

| | 值 |
|---|---|
| 目标 | ±1.0472 rad（60°）|
| 实测行程 | 0.868 – 1.020 rad |
| 达成率 | **82.9% – 97.4%**，均值 89.9% |
| 现用阈值 | 0.8 rad = 目标的 **76.4%** |
| 阈值与最差实测的余量 | 0.068 rad（7.9%）|

### 外推到 2.0

2.0 目标 1.5708 rad（π/2，出处 `examples/gripper_posforce.cpp:45`）。

按同一达成率下限 76.4% → **1.5708 × 0.764 ≈ 1.20 rad**。

### 这个外推的三处不确定（必须实测确认）

1. **控制模式不同。** 1.0 是 MIT（kp=5.0，无力矩上限），2.0 官方用
   **POS_FORCE + 力矩上限 0.15 pu**。带力矩封顶的达成率**不能假定和 MIT 相同**——
   力矩不足时会提前停住。
2. **机构不同。** 1.0 是连杆平行夹爪，2.0 是紧凑夹爪，摩擦和行程特性都可能不同。
3. **1.0 的 7.9% 余量偏紧。** 17 条里最差 82.9%，阈值 76.4%，只差 6.5 个百分点。
   2.0 若沿用同比例，建议**先按 1.20 记录实测但不判 FAIL**，积累 5–10 台后再定死。

**结论：1.20 rad 是个起点假设，不是规格。** 注册表里保持
`min_travel_rad: null`（只记录不判定），直到有 2.0 真机数据。

---

## 3. 2.0 TIMEOUT：推不出来，官方无依据

`openarm_can` 1.4.0 对 RID 9 的全部描述（`motor_read_param_commands.cpp:51`）：

```
{RID::TIMEOUT, {"CAN Timeout", "RW", "uint32", "[0, 2^32-1]"}}
```

**只有类型和取值范围，没有推荐值。** 官方文档、示例、issue 里都没有出现过具体数值。

我们现用的 5000 是自己定的（1.0 两臂统一）。2.0 暂时沿用，标记
`timeout_hardware_verified: false`。

**这个数只能由你们按实际通信中断容忍度定**，官方帮不上忙。
