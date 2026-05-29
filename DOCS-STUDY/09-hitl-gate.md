# 09 — HITL 人类审批门：interrupt() + Checkpoint 暂停/恢复机制

> **日期**: 2026-05-15 | **Sprint**: 4 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/nodes/hitl_gate.py`](../backend/packages/harness/deerflow/collaboration/nodes/hitl_gate.py) | HITL Gate 节点 + 审批包构建 |
| [`backend/packages/harness/deerflow/collaboration/graph.py`](../backend/packages/harness/deerflow/collaboration/graph.py) | Parent Graph 中的 HITL 条件路由 |

---

## Q1: 审批的图暂停除了暂存机制还用到什么异步机制吗？ `_stale_check` 的时间戳如何检查超时？审批 Node 的完整流程是怎样的？ `📄 hitl_gate.py` `📄 graph.py`

**A: 没有用到任何异步/挂起/定时器机制。** 这是最容易产生误解的地方。

### 核心纠正：`interrupt()` 不是"暂停线程"

```
interrupt() ≠ time.sleep()（阻塞等待）
interrupt() = 序列化状态到数据库 + 彻底退出执行
```

线程不阻塞，不占用资源，没有定时器在跑，函数调用直接结束。

---

### 完整流程（10 步）

```
时间线 ──────────────────────────────────────────────────────────────►

第一段：暂停
┌────────────────────────────────────────────────────────────┐
│ ① Analysis SubGraph 输出 → Parent Graph 路由到 hitl_gate  │
│                                                             │
│ ② hitl_gate_node(state) 开始执行                            │
│    ├─ 幂等检查: state.review_decision → None，继续          │
│    ├─ build_approval_payload(state) → 审批包                │
│    ├─ payload["_stale_check"] = {                           │
│    │      "generated_at": 1715800000.0,  ← 这一刻的时间戳   │
│    │      "stale_after": 1800            ← "30分钟后过期"    │
│    │  }                                                     │
│    └─ decision = interrupt(payload)  ← 函数在这里"冻结"    │
│                                                             │
│ ③ LangGraph 内部：                                          │
│    ├─ 将当前 state 写入 PostgresSaver checkpoint            │
│    ├─ 将 payload 存入 checkpoint 的 interrupt 槽位          │
│    ├─ 抛出 GraphInterrupt 异常（正常中断，不是崩溃）         │
│    └─ 函数调用彻底结束，线程释放                             │
│                                                             │
│ ④ 客户端收到 interrupt 事件，展示审批界面                    │
└────────────────────────────────────────────────────────────┘

                      ⏸️  图完全停止。没有线程在等待。
                          可能是 5 秒后恢复，也可能是 5 小时后。

第二段：恢复（人类点击按钮后）
┌────────────────────────────────────────────────────────────┐
│ ⑤ 客户端调用 POST /api/threads/{id}/runs/{rid}/resume     │
│    body: {"resume": "approve"}                              │
│                                                             │
│ ⑥ resume API（App 层，Sprint 5）在处理前做 stale 检查：      │
│    ├─ 从 checkpoint 读取 interrupt payload                 │
│    ├─ now = time.time()  // 1715802000.0                    │
│    ├─ generated_at = 1715800000.0                           │
│    ├─ elapsed = now - generated_at = 2000s                  │
│    ├─ 2000 > 1800 (STALE_TIMEOUT_SECONDS) → ⚠️ STALE!      │
│    └─ 选择：拒绝 + 提示"审批已过期" OR 警告但允许继续       │
│                                                             │
│ ⑦ 如果未过期 → LangGraph 从 checkpoint 恢复：               │
│    ├─ 从 PostgresSaver 加载 state                           │
│    ├─ 定位到 hitl_gate_node 内的 interrupt() 调用点         │
│    ├─ Command(resume="approve") 的值作为 interrupt() 返回值  │
│    └─ 继续执行 ↓                                            │
│                                                             │
│ ⑧ hitl_gate_node 从中断点继续（第 114 行之后）：             │
│    decision = "approve"  ← interrupt() 返回了这个值          │
│    ├─ 校验: decision in ("approve","modify","replan")→True  │
│    └─ return {"review_decision": "approve"}                  │
│                                                             │
│ ⑨ Parent Graph route_after_hitl(state):                    │
│    state["review_decision"] = "approve"                     │
│    → return "report_composer"                               │
│                                                             │
│ ⑩ Report Composer 执行 → END                                │
└────────────────────────────────────────────────────────────┘
```

---

### `_stale_check` 的本质：冷检查（Cold Check），不是热监控

`_stale_check` 不是计时器，是暂停时贴的"保质期标签"：

```
interrupt 时：打上时间戳标签
resume 时：  看一眼标签 → 过期了？拒绝 / 没过期？放行

就像食品包装上的生产日期，不是在包装里装了个倒计时炸弹。
```

**所有检查都在恢复时（步骤⑥）做一次时间减法，不需要后台定时器。**

---

### 涉及的外部机制汇总

| 机制 | 由谁提供 | 在哪里发挥作用 |
|------|---------|---------------|
| Checkpoint 持久化 | LangGraph `PostgresSaver` | interrupt 时写入，resume 时读取 |
| GraphInterrupt 异常 | LangGraph 内部 | 中断图执行但不崩溃 |
| `Command(resume=...)` | LangGraph 2.0 API | 携带人类决定恢复执行 |
| Stale 检测 | **我们的代码**（`collaboration.py` router，Sprint 5） | resume 前做时间比较 |
| 幂等性检查 | **我们的代码**（`hitl_gate_node` 第 95-98 行） | 防止重复暂停 |

---

### 这个模型的核心优势

```
interrupt() = 序列化状态到数据库 + 退出进程
resume      = 从数据库反序列化 + 重新执行中断点
```

- **不占用内存**：图暂停期间没有 Python 对象驻留，只有数据库里的一条记录
- **可跨进程/跨机器恢复**：停的时候在服务器 A，人可以第二天在服务器 B 点 approve
- **天然幂等**：checkpoint 数据不丢，重复 resume 也不会出问题
- **Stale 检测极简**：不需要后台定时器，恢复时做一个时间减法就行
