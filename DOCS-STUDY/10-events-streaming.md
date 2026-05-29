# 10 — 流式事件系统：EventType + SSE 推送链路

> **日期**: 2026-05-15 | **Sprint**: 4 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/events.py`](../backend/packages/harness/deerflow/collaboration/events.py) | EventType 枚举 + StreamEvent TypedDict + make_event() 工厂 |
| [`backend/packages/harness/deerflow/runtime/stream_bridge/base.py`](../backend/packages/harness/deerflow/runtime/stream_bridge/base.py) | DeerFlow StreamBridge 抽象（已有基础设施） |
| [`backend/packages/harness/deerflow/runtime/runs/worker.py`](../backend/packages/harness/deerflow/runtime/runs/worker.py) | Run worker — graph.astream() → SSE（已有基础设施） |

---

## Q1: events.py 是给什么用的？ `📄 events.py`

**A:** 前后端实时通信的"信号约定"。

协作图一次运行可能 15-25 分钟。前端不能干等着——需要实时展示进度：

```
前端界面：

  ✅ 研究计划已制定
  🔍 Data Scout 正在采集... (3/3)
  ⚔️ Critic 正在验证数据...
  👨‍⚖️ Meta-Judge 正在裁决...
  ⏸️ 等待审批 [approve] [modify] [replan]
  📝 正在生成报告...
  ✅ 完成
```

`events.py` 定义了每一步对应的**事件类型和数据结构**，保证前后端说的是同一个"语言"。

### 文件结构

```python
# 25 种事件按阶段分组
EventType:
  Research:  RESEARCH_STARTED → PLAN_READY → SCOUT_DISPATCHED → ...
  Analysis:  ANALYSIS_STARTED → SYNTHESIS_PROGRESS → ...
  HITL:      HITL_WAITING → HITL_DECISION_RECEIVED
  Compose:   COMPOSE_STARTED → COMPOSE_COMPLETED
  System:    PHASE_TRANSITION, ERROR, WORKFLOW_COMPLETED

# 统一的 payload 结构
StreamEvent(TypedDict):
  type: str           # 对应 EventType 的值
  phase: str          # 当前阶段
  data: dict          # 具体数据（每个事件不同）
  timestamp: float    # 时间戳
  message: str        # 人类可读文本

# 工厂函数，保证格式一致
make_event(event_type, phase, data, message) → StreamEvent
```

### 为什么不仅用一个 message 字段？

不同事件携带不同数据，前端需要结构化信息做差异化渲染：
- `SCOUT_RESULT` 的 `data` 里可能有 `{"scout_id": "A", "sources_found": 5}`
- `HITL_WAITING` 的 `data` 里是审批选项 `{"decisions": [...], "summary": {...}}`
- `ERROR` 的 `data` 里是 `{"node": "...", "detail": "..."}`

---

## Q2: SSE Channel 是什么？如何保持状态推送到前端？后续会在哪里写这部分代码？

**A:** SSE = **Server-Sent Events**，HTTP 协议原生的服务器推送机制。

```
WebSocket:  客户端 ◄══════════► 服务器  （双向，需要握手升级协议）
SSE:        客户端 ◄──────────── 服务器  （单向，普通 HTTP 请求）
```

SSE 是标准 HTTP，浏览器原生支持 `EventSource` API，不需要任何库。

### 完整推送链路（我们只需写第 2 步，其余全复用 DeerFlow）

```
我们的节点代码              DeerFlow 基础设施                    前端
─────────────────      ──────────────────────────      ─────────────
                        ① worker.py
                        graph.astream(
research_nodes.py         stream_mode=["custom",      前端 EventSource
   │                      "values",                   订阅 /api/.../stream
   │                      "messages-tuple"]
   │                    )                                  │
   ├─ writer =              │                              │
   │  get_stream_writer()   ② LangGraph 每次自定义事件      │
   │                        触发 chunk                     │
   ├─ writer(                │                              │
   │    make_event(         ③ worker 收到 chunk             │
   │      RESEARCH_          ├─ mode = "custom"             │
   │      STARTED,           ├─ sse_event = "custom"        │
   │      ...                ├─ bridge.publish(             │
   │    )                    │    run_id,                   │
   │  )                      │    "custom",                 │
   │                         │    serialize(chunk)  ───────►│ 收到 event
   └─ ...                    │  )                           │ "custom"
                              │                              │
                             ④ StreamBridge (Memory)        ├─ 根据
                              ├─ 内存队列缓存                │  data.type
                              ├─ 等待订阅者                  │ 更新进度条
                              └─ 推送到 SSE endpoint         │
```

**关键：我们只需要在自己节点里调 `get_stream_writer()` 发射事件，其余全走 DeerFlow 已有基础设施。**

### 后续在哪里写这部分代码？

在**节点文件**里，每个关键步骤前后 emit 事件。需要改的文件：

| 文件 | 要加的事件 |
|------|-----------|
| `nodes/research_nodes.py` | `RESEARCH_STARTED`, `RESEARCH_PLAN_READY`, `SCOUT_DISPATCHED`, `SCOUT_RESULT`, `CRITIQUE_STARTED`, `CHALLENGE_ISSUED` 等 |
| `nodes/analysis_nodes.py` | `ANALYSIS_STARTED`, `SYNTHESIS_PROGRESS`, `SYNTHESIS_COMPLETED`, `REVIEW_STARTED` 等 |
| `nodes/hitl_gate.py` | `HITL_WAITING`, `HITL_DECISION_RECEIVED` |
| `nodes/analysis_nodes.py` (report_composer) | `COMPOSE_STARTED`, `COMPOSE_COMPLETED` |

无需新建文件。Sprint 4 后期或 Sprint 5 做这些集成。

### 需要新增的文件

| 文件 | 内容 |
|------|------|
| `app/gateway/routers/collaboration.py` | HITL resume API（接收 `Command(resume=...)`）+ stale 检查 |
