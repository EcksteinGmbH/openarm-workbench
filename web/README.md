# OpenARM Motor Commissioning Station

基于 Flask + Socket.IO 的本地 Web 工站，用于 OpenARM 使用的 Damiao 电机建站、参数校验、零位，以及整臂 CAN2.0 通信扫描。

## V1 功能

- 单电机建站：识别、套用 Joint 模板、写入参数、回读校验、保存 Flash、零位、`safe_mit_ping`
- 整臂 CAN2.0 通信扫描：按 OpenARM profile 逐 Joint 对账、读取参数和健康状态、输出报告
- 双 transport：
  - `serial_bridge`：完整建站
  - `socketcan`：CAN2.0 只读验证与整臂扫描
- WebSocket 事件：
  - `job_state`
  - `motor_status`
- 本地工件落盘：
  - `job.json`
  - `motors/*.json`
  - `events.jsonl`
  - `report.html`

## UI 约束

- 主界面按 `1920x1080` 工作站屏幕设计
- 单屏完成，不允许页面级纵向滚动
- 顶层固定 5 个主 Tab：
  - `任务`
  - `连接`
  - `识别`
  - `执行`
  - `报告`

## 核心 API

### 配置
- `GET /api/config`

### 设备
- `POST /api/device/connect`
- `POST /api/device/disconnect`
- `POST /api/device/scan`

### Job
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/apply-profile`
- `POST /api/jobs/{job_id}/write-params`
- `POST /api/jobs/{job_id}/verify-params`
- `POST /api/jobs/{job_id}/save-flash`
- `POST /api/jobs/{job_id}/zero`
- `POST /api/jobs/{job_id}/test`
- `GET /api/jobs/{job_id}/report`

## 前端模块结构

Web 前端已开始按 ES module 渐进拆分，入口为 `static/js/main.js`：

- `api.js`：统一封装后端 JSON API 调用
- `main.js`：浏览器入口，只负责在 DOM ready 后启动应用
- `store.js`：页面级共享状态
- `job-types.js`：任务类型判断与整臂矩阵字段
- `navigation.js`：主 Tab、执行 Tab、测试区和工厂 Section 切换
- `log.js`：事件日志渲染
- `event-bindings.js`：集中维护 DOM 事件绑定和危险动作确认入口
- `socket-client.js`：Socket.IO 事件订阅与状态分发
- `factory-helpers.js`：出厂模块 DOM 取值和安全确认 payload
- `diagnostic-helpers.js`：单关节诊断 DOM 取值
- `form-payloads.js`：连接、专家覆盖参数等表单请求体构造
- `modal.js`：危险动作确认弹窗
- `ui-helpers.js`：通用 DOM 渲染小工具
- `app.js`：仍保留主要业务流程，后续继续拆为 `workflow.js`、`factory.js`、`ui-render.js`

## 启动

```bash
./start_web.sh
```

或：

```bash
python3 web/app.py
```

## Profile

默认 profile：

- [openarm_v1.yaml](/home/ubuntu/Projects/OpenARM/profiles/openarm/openarm_v1.yaml)

现场真机测试与排障：

- [OPENARM_LIVE_TEST_CHECKLIST.md](/home/ubuntu/Projects/OpenARM/docs/OPENARM_LIVE_TEST_CHECKLIST.md)

可选覆盖目录：

- `config/profiles/openarm_v1.yaml`

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/pytest -q
```
