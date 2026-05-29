# 03 — Parent Graph 组装与条件路由

> **日期**: 2026-05-14 | **Sprint**: 1 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/graph.py`](../backend/packages/harness/deerflow/collaboration/graph.py) | Parent Graph 组装 + 条件路由 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py) | state_in / state_out 映射函数 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py) | Research SubGraph（被挂载） |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/analysis_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/analysis_subgraph.py) | Analysis SubGraph（被挂载） |

---

## Q1: `add_conditional_edges` 的语法——为什么边指向 research_subgraph 但又声明 analysis_subgraph？ `📄 graph.py`

**A:** 第一眼看容易误读。`"research_subgraph"` 不是目标，是**源节点**。

```python
builder.add_conditional_edges(
    "research_subgraph",          # ← 参数1: 源节点（从谁出发），不是目标！
    route_after_research,         # ← 参数2: 路由函数
    {
        "analysis_subgraph": "analysis_subgraph",  # ← 参数3: path_map
        "error_handler": "error_handler",
    },
)
```

**语义**：`research_subgraph` 执行完毕后 → 调用 `route_after_research()` 检查状态 → 如果返回 `"analysis_subgraph"`，则跳到 analysis_subgraph 节点；如果返回 `"error_handler"`，则跳到 error_handler。

`path_map` 里的 key 是路由函数的**可能返回值**，value 是**对应的下一个节点名**。key 和 value 恰好同名是常见的（节点名 = 路由返回值），但不是必须的。

**Research 正常完成时的完整数据流**：

```
Step 1: research_subgraph 启动
  state_in: map_parent_to_research(ParentState) → 传入 workflow_type, max_scouts
  Research 内部: PI → Scouts(Send) → Critic ⇄ Scouts → Judge → PI Review
  产出: validated_brief, research_quality_score

Step 2: research_subgraph 结束
  state_out: map_research_to_parent(ResearchState, ParentState) → 写入 Parent
  ParentState 现在: validated_brief = {...}, research_quality_score = 0.85

Step 3: 路由判断
  route_after_research(ParentState) → collaboration_error 为空 → 返回 "analysis_subgraph"

Step 4: analysis_subgraph 启动
  state_in: map_parent_to_analysis(ParentState) → 传入 validated_brief, quality_score
  Analysis 内部: Analyst Lead → Synthesizer → Internal Reviewer
  产出: synthesis_report

Step 5: analysis_subgraph 结束
  state_out: map_analysis_to_parent(AnalysisState, ParentState) → 写入 Parent
  ParentState 现在: synthesis_report = {...}

Step 6: 路由判断
  route_after_analysis → 无错误 → 进入 hitl_gate

Step 7: HITL Gate
  人类审批 → review_decision = "approve"

Step 8: 路由判断
  route_after_hitl → "approve" → 进入 report_composer

Step 9: report_composer → END
```

用图表示：

```
                    ┌─────────────────┐
                    │ research_subgraph │
                    └────────┬────────┘
                             │ state_out → validated_brief
                    ┌────────▼────────┐
                    │ route_after_     │
                    │ research()       │
                    └────────┬────────┘
                             │ return "analysis_subgraph"
                    ┌────────▼────────┐
                    │ analysis_subgraph│
                    └────────┬────────┘
                             │ state_out → synthesis_report
                    ┌────────▼────────┐
                    │ route_after_     │
                    │ analysis()       │
                    └────────┬────────┘
                             │ return "hitl_gate"
                    ┌────────▼────────┐
                    │   hitl_gate      │
                    └────────┬────────┘
                             │ review_decision = "approve"
                    ┌────────▼────────┐
                    │ route_after_hitl │
                    └────────┬────────┘
                             │ return "report_composer"
                    ┌────────▼────────┐
                    │ report_composer  │
                    └────────┬────────┘
                             │
                            END
```

---

## Q2: "父子图共享 checkpointer 实例"是什么意思？ `📄 graph.py`

**A:** checkpointer 是 LangGraph 的状态持久化组件。当图执行到某个节点后，会自动把当前 State 序列化保存。

"共享实例"意味着：Parent Graph 和两个 SubGraph 向**同一个数据库连接**写入 checkpoint。

```
Parent Graph invoke(state, config={"configurable": {"thread_id": "t-001"}})
  │
  ├── research_subgraph 执行
  │     └── PostgresSaver.save(thread_id="t-001", checkpoint_ns="research", state={...})
  │
  ├── analysis_subgraph 执行
  │     └── PostgresSaver.save(thread_id="t-001", checkpoint_ns="analysis", state={...})
  │
  └── hitl_gate: interrupt()
        └── PostgresSaver.save(thread_id="t-001", checkpoint_ns="", state={...})
```

**为什么共享？**

1. **一致性** — Parent 和 SubGraph 的状态属于同一个 `thread_id`，存在同一个数据库中，恢复时不会出现"Parent 恢复了但 Research 丢了"的情况
2. **HITL 暂停/恢复** — `interrupt()` 把整个图状态写入 checkpointer，几天后 `Command(resume=...)` 可以从同一条记录恢复，包括 SubGraph 内部进度
3. **不自动共享** — 需要在 `invoke(graph, config)` 时把同一个 `PostgresSaver` 实例传入 `config`。如果 Parent 用 A 实例、SubGraph 用 B 实例，就做不到一致恢复

**独立 `checkpoint_ns`（命名空间）**：虽然是同一个 checkpointer 实例，但每个 SubGraph 用不同的 `checkpoint_ns` 前缀写入。这防止两个 SubGraph 的内部 channel（都叫 `messages`）在 checkpointer 中互相覆盖。类似于同一个数据库里的不同表。

---

## Q3: `add_conditional_edges` 的参数详解 `📄 graph.py`

**A:** 函数签名：

```python
def add_conditional_edges(
    source: str,                              # 参数1: 源节点名
    router: Callable[[State], str],           # 参数2: 路由函数
    path_map: dict[str, str | type[END]],     # 参数3: 路由表
) -> None:
```

| 参数 | 类型 | 作用 |
|------|------|------|
| `source` | `str` | 当这个节点执行完后，触发路由判断 |
| `router` | `(State) → str` | 接收当前 State，返回一个路由 key |
| `path_map` | `dict[str, str]` | router 的返回值 → 目标节点名；`"__end__"` 映射到 `END` |

**以文件中最复杂的 HITL 路由为例**：

```python
builder.add_conditional_edges(
    "hitl_gate",           # ① source: hitl_gate 节点执行完毕后触发
    route_after_hitl,      # ② router: 读 state.review_decision
    {                      # ③ path_map: 4 条可能路径
        "report_composer": "report_composer",
        "analysis_subgraph": "analysis_subgraph",
        "research_subgraph": "research_subgraph",
        "__end__": END,
    },
)
```

对应的路由函数：

```python
def route_after_hitl(state: CollaborationState) -> Literal[
    "report_composer", "analysis_subgraph", "research_subgraph", "__end__"
]:
    decision = state.get("review_decision")
    if decision == "approve":
        return "report_composer"       # → path_map → report_composer 节点
    elif decision == "modify":
        return "analysis_subgraph"     # → path_map → analysis_subgraph 节点
    elif decision == "replan":
        return "research_subgraph"     # → path_map → research_subgraph 节点
    return "__end__"                   # → path_map → END（图结束）
```

**执行流程**：

```
hitl_gate 完成
  ↓
route_after_hitl(state)
  ├── state.review_decision == "approve"  → return "report_composer"  → report_composer 节点
  ├── state.review_decision == "modify"   → return "analysis_subgraph" → analysis_subgraph 节点
  ├── state.review_decision == "replan"   → return "research_subgraph" → research_subgraph 节点
  └── state.review_decision == None       → return "__end__"           → END
```

**本质**：`add_conditional_edges` 是在图里声明一个**有限状态机**——同一个源节点，根据状态不同走向不同目标。`router` 是转移逻辑，`path_map` 是转移表。

**与 `add_edge` 的对比**：

```python
# add_edge: 固定转移, A 之后永远是 B
builder.add_edge("report_composer", END)

# add_conditional_edges: 条件转移, A 之后根据 state 走 B/C/D
builder.add_conditional_edges("hitl_gate", route_after_hitl, path_map)
```

**path_map 的 key 和 value 可以不同**：

```python
# 允许: key 是 router 返回值, value 是节点名, 可以不同
{
    "approve_decision": "report_composer",
    "modify_decision": "analysis_subgraph",
}
# 此时 router 返回 "approve_decision" → 跳转到 "report_composer"
```

当前文件中 key 和 value 同名是惯例而非强制——这让代码更可读。

---

## Q4: 为什么 Parent 条件边多，SubGraph 条件边少？ `📄 graph.py` `📄 research_subgraph.py` `📄 analysis_subgraph.py`

**A:** 统计三个图就能看到差异：

| | Research SubGraph | Analysis SubGraph | Parent Graph |
|---|---|---|---|
| 固定边 | 3 | 2 | 2 |
| 条件边 | 2 | 1 | 3 |
| 条件边占比 | 40% | 33% | **60%** |

**原因是职责分工不同**：

- **SubGraph 内部是"工序"** — 大部分流程是确定的：PI 规划完一定到 Critic，Synthesizer 完一定到 Reviewer。只有工序结果不确定时才分岔（Critic 觉得数据有问题→补采，没问题→裁决）

- **Parent Graph 是"调度中心"** — 它的全部工作就是根据状态做决策：Research 成功还是异常？Analysis 成功还是异常？人类批了还是驳回？每步都要判断，每步都是条件边

```
SubGraph（工序）:                    Parent（调度）:
┌──────────────────────┐           ┌──────────────────────┐
│ PI → Critic → ?      │           │ Research → ?         │
│   ↓       ↓          │           │   ↓                  │
│  固定   条件(2条)     │           │  成功? → Analysis    │
│                      │           │  失败? → Error       │
│ Synthesizer → Rev.   │           │                      │
│   固定               │           │ Analysis → ?         │
└──────────────────────┘           │  成功? → HITL        │
                                   │  失败? → Error       │
                                   │                      │
                                   │ HITL → ?             │
                                   │  批准/修改/重规划     │
                                   └──────────────────────┘
```

**这是 Nested SubGraph 模式的设计意图**：把确定性工序封进 SubGraph（内部少分支、易测试），把不确定性调度留在 Parent（全局视角、条件路由集中管理）。两条设计原则：
1. SubGraph 内部只在**工序结果真的不可预测**时才用条件边
2. 跨阶段决策（成功/失败、批准/驳回）一律放 Parent

---

> **已完成文档**: [01 — 三层 State 体系](01-state-system.md) | [02 — SubGraph 构建](02-subgraph-design.md)
