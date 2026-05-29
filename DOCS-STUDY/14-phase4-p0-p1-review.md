# 14 — Phase 4 P0/P1 Review: 生产就绪关键修补

> **日期**: 2026-05-19 | **Phase**: 4 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | P0/P1 | 变更内容 |
|------|-------|---------|
| [`backend/langgraph.json`](../backend/langgraph.json) | P0 | 注册 `collaboration` graph + checkpointer 路径 |
| [`backend/packages/harness/deerflow/collaboration/graph.py`](../backend/packages/harness/deerflow/collaboration/graph.py) | P0 | 新增 `make_collaboration_agent(config)` 工厂函数 + `build_collaboration_graph(checkpointer)` |
| [`backend/packages/harness/deerflow/agents/lead_agent/agent.py`](../backend/packages/harness/deerflow/agents/lead_agent/agent.py) | P0 | `_build_middlewares()` 注入 `CollaborationMiddleware` |
| [`backend/packages/harness/deerflow/collaboration/nodes/research_nodes.py`](../backend/packages/harness/deerflow/collaboration/nodes/research_nodes.py) | P1 | 新增 `pi_dispatch_node`，`data_scout_node` 增加 Send API payload 优先逻辑 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py) | P1 | 插入 `pi_dispatch` 节点，`pi_agent → pi_dispatch → critic_agent` 替代直达边 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py) | P3 | Memory 字段传递（父↔子双向），见 [13-memory-system.md](13-memory-system.md) |

---

## P0: LangGraph 注册 + Graph 工厂函数 + Checkpointer 集成

### Q1: `langgraph.json` 为什么要注册两个 graph？ `📄 langgraph.json`

**A:** LangGraph Server 支持多 graph 注册。`lead_agent` 是对话主干，`collaboration` 是协作分析专用图。

```json
{
  "graphs": {
    "lead_agent": "deerflow.agents:make_lead_agent",
    "collaboration": "deerflow.collaboration.graph:make_collaboration_agent"
  },
  "checkpointer": {
    "path": "./packages/harness/deerflow/runtime/checkpointer/async_provider.py:make_checkpointer"
  }
}
```

**关键设计点**:
- 两个 graph 共享同一个 checkpointer 实例（由 DeerFlow Worker 注入）
- 前端/API 可通过 `assistant_id=collaboration` 选择协作图
- `make_collaboration_agent(config: RunnableConfig)` 的签名与 `make_lead_agent(config)` 完全兼容

### Q2: `make_collaboration_agent(config)` 工厂函数的设计意图

**A:** LangGraph Runtime 要求 `graphs` 注册的函数签名为 `(RunnableConfig) → CompiledStateGraph`。

```python
# collaboration/graph.py:192-203
def make_collaboration_agent(config: "RunnableConfig") -> "CompiledStateGraph":
    checkpointer = config.get("configurable", {}).get("checkpointer") if config else None
    return build_collaboration_graph(checkpointer=checkpointer)
```

**为什么 checkpointer 从 config 取而不是硬编码？**

DeerFlow Worker 在启动时创建 checkpointer（SQLite/Postgres），然后在调用 graph 工厂函数前注入到 `config.configurable.checkpointer`。这保持了与 `make_lead_agent` 的完全一致性——两者都以同样的方式接收 checkpointer。

**为什么分开 `build_collaboration_graph(checkpointer)` 和 `make_collaboration_agent(config)` 两个函数？**

`build_collaboration_graph` 是纯编译逻辑，测试中可以直接传入 `InMemorySaver()`，不需要构造完整的 `RunnableConfig`。这是标准的两段式设计：
- `build_*()` — 可测试的纯编译
- `make_*()` — 符合 LangGraph Runtime 签名的工厂包装

### Q3: 当前状态 — 协作图已注册但 Lead Agent 尚未路由到它

**现状**: `langgraph.json` 已注册 `collaboration` graph，`CollaborationMiddleware` 已注入到 Lead Agent 中间件链。但 Lead Agent 本身仍是标准 ReAct 图（不是协作图）。

**这意味着**:
- 如果前端/API 显式指定 `assistant_id=collaboration` → 直接使用协作图 ✅
- 如果用户通过 Lead Agent 对话 → 仍是标准 ReAct，不会自动切换到协作图 ❌
- `CollaborationMiddleware` 当前主要作用是：当 Lead Agent 触发子代理时，注入 agent_role 权限上下文

**完整的"Lead Agent 自动路由到协作图"方案**（P0 剩余工作，需后续实施）:
```python
# 在 make_lead_agent() 中检查 collaboration.enabled
if config.collaboration.enabled:
    return make_collaboration_agent(config)
else:
    return build_lead_agent(...)  # 标准 ReAct
```

当前不执行此方案的原因：协作图假设了完整的 Research→Analysis→HITL→Compose 流程，而简单对话场景（"你好"、"今天天气怎么样"）不需要这个流程。自动路由需要先解决"何时该走协作图"的判断逻辑。

---

## P1: Send API Fan-out — 并行 Scout 采集

### Q4: `pi_dispatch_node` 为什么需要单独成一个节点？ `📄 research_nodes.go:144-164`

**A:** LangGraph 的 `Command(goto=[Send(...)])` 不合并状态更新——它只控制控制流。

这是 LangGraph 的一个微妙但关键的设计：

```python
# pi_agent_node — 存储研究计划到 State
def pi_agent_node(state):
    # ... 执行 LLM ...
    return {"research_plan": plan}  # ← 更新 State

# pi_dispatch_node — 读取计划，Send API 并行分发
def pi_dispatch_node(state):
    plan = state.get("research_plan")  # ← 读取 State
    sends = [Send("data_scout", {"scout_task": t}) for t in plan["sub_tasks"]]
    return Command(goto=sends)  # ← 只控制流，不更新 State
```

**如果把 pi_agent 和 pi_dispatch 合并成一个节点**:
```python
def pi_agent_node(state):
    # 生成计划...
    plan = {"sub_tasks": [...]}
    sends = [Send("data_scout", {"scout_task": t}) for t in plan["sub_tasks"]]
    return Command(goto=sends, update={"research_plan": plan})
    #                                     ↑ 这个 update 不会生效！
    # Command 带 goto 时，update 被忽略（LangGraph 1.1.9 行为）
```

**结论**: 必须分两步——pi_agent 存 plan（dict return），pi_dispatch 读 plan 后发 Send（Command return）。这就是为什么 SubGraph 的边是 `pi_agent → pi_dispatch → critic_agent` 而非 `pi_agent → critic_agent`。

### Q5: `list[Send]` 直接返回为什么在 LangGraph 1.1.9 报错？ `🔬 源码级发现`

**A:** 这是本阶段最关键的框架内部发现。

**报错**: `InvalidUpdateError: Expected dict, got list`

**根因**: LangGraph 的 `_get_updates()`（`langgraph/pregel/_algo.py` → `state.py:1284`）对节点返回值做类型检查：

```python
# LangGraph 1.1.9 内部逻辑（简化）
if isinstance(output, (NoneType, dict)):
    return output          # ✅ 直接返回
elif isinstance(output, Command):
    if output.goto:
        return output      # ✅ Command 带 goto
    else:
        return output.update  # ✅ Command 不带 goto，返回 update dict
elif isinstance(output, list) and all(isinstance(c, Command) for c in output):
    return [c.update for c in output]  # ✅ list[Command]
elif is_annotated_type(output):
    return output          # ✅ 带 reducer 的 Annotated 类型
else:
    raise InvalidUpdateError(...)  # ❌ list[Send] 落到这里！
```

**`list[Send]` 能工作的情况**: 仅在 `_control_branch()`（`state.py:1537`）处理 `Command.goto` 时：
```python
# state.py:1537
elif isinstance(cmd.goto, list) and all(isinstance(s, Send) for s in cmd.goto):
    for send in cmd.goto:
        self.tasks[W].append(send)  # ← 每个 Send 分发到 TASKS channel
```

**关键**: `Send` 对象只能出现在 `Command.goto` 内部，不能作为节点直接返回值。这是 LangGraph 的显式设计——`Send` 是控制流原语，不是状态更新原语。

### Q6: `data_scout_node` 如何区分 Send 模式 vs 手动模式？ `📄 research_nodes.go:224-239`

**A:** 按优先级：

```
1. pending challenges 存在？ → Rebuttal Mode（定向补采，回应 Critic 质疑）
2. state.scout_task 存在？   → Send Mode（Send API 传入的并行任务）
3. 否则                     → Fallback Mode（读取 research_plan 的子任务）
```

```python
# research_nodes.py:224-239
scout_task = state.get("scout_task")  # ← Send API 注入的 payload
if scout_task:
    instruction = f"Assigned Task: {json.dumps(scout_task)}\n\nExecute this specific sub-task..."
else:
    plan = state.get("research_plan", {})  # ← fallback
    instruction = f"Research Plan: {json.dumps(plan)}\n\nExecute your assigned sub-task..."
```

**Send API 的 payload 合并语义**: 当 `Send("data_scout", {"scout_task": t})` 执行时，`{"scout_task": t}` 被**浅合并**到目标节点的 State 副本中。这意味着每个 Scout 实例看到的是：基础 ResearchSubGraphState + 自己的 `scout_task`。

---

## P0 剩余工作清单

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | Lead Agent 路由到协作图 | 在 `make_lead_agent()` 中根据 `collaboration.enabled` 切换到 `make_collaboration_agent()` |
| P0 | 协作意图检测 | 判断用户输入是否适合走协作分析流程（竞品分析/市场趋势/定价优化）vs 简单对话 |
| P1 | Checkpointer 测试 | 验证 `build_collaboration_graph(checkpointer=InMemorySaver())` 在真实 State 流转下的 checkpoint/restore |
| P2 | 真实 LLM 集成测试 | 至少 1 个集成测试用真实 LLM 跑通最小流程 |

---

> **Phase 4 P0/P1 总结完成。Send API 的 `Command(goto=[Send(...)])` vs `list[Send]` 发现是 LangGraph 1.1.9 框架内部行为的关键洞察。**
