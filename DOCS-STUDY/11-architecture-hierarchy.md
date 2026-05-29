# 11 — 协作系统整体层级调用图

> **日期**: 2026-05-15 | **Sprint**: 4 收尾 | **作者**: Wu Gang + Claude

---

## Q: 新增了这么多文件代码，整体层级调用关系是怎样的？`subgraphs/` 是不是偏向于总的调用其他几个，然后自己被 `graph.py` 调用？

**A: 正是如此。** `subgraphs/` 是"组装车间"，`graph.py` 是"总装车间"。

---

## 完整 5 层调用图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         外部入口（Sprint 5）                              │
│  lead_agent/agent.py ──→ build_collaboration_graph()                    │
│  app/gateway/routers/collaboration.py ──→ HITL resume API                │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
        ═════════════════════════╪═════════════════════════
        Layer 3: Parent Graph    │
        ═════════════════════════╪═════════════════════════
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  graph.py                                                               │
│  ────────                                                               │
│  build_collaboration_graph() → CompiledStateGraph                        │
│                                                                          │
│  职责：挂载 SubGraph + Parent 层节点 + 条件路由                            │
│                                                                          │
│  import: subgraphs/*, nodes/hitl_gate, nodes/analysis_nodes(report),     │
│          state, state_mapping                                           │
└────┬──────────┬──────────┬──────────┬─────────────┐
     │          │          │          │             │
     ▼          ▼          ▼          ▼             ▼
┌─────────┐ ┌───────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│research │ │analysis│ │hitl_gate │ │report    │ │state_mapping │
│subgraph │ │subgraph│ │.py       │ │_composer │ │.py           │
│.py      │ │.py     │ │          │ │          │ │(4 纯函数)     │
└────┬────┘ └───┬────┘ └────┬─────┘ └────┬─────┘ └──────────────┘
     │          │           │            │
     │          │           │            └─ analysis_nodes.report_composer_node
     │          │           └─ nodes/hitl_gate.hitl_gate_node
     │          │
     │          │    ═══════════════════════════════════════════
     │          │    Layer 2: SubGraph Builders（组装车间）       ╯
     │          │    ═══════════════════════════════════════════
     │          │
     │          └── build_analysis_subgraph():
     │               StateGraph(AnalysisSubGraphState)
     │               .add_node("analyst_lead", analyst_lead_node)
     │               .add_node("synthesizer", synthesizer_node)
     │               .add_node("internal_reviewer", internal_reviewer_node)
     │               .add_edge(...)  .add_conditional_edges(...)
     │               .compile()
     │
     └── build_research_subgraph():
          StateGraph(ResearchSubGraphState)
          .add_node("pi_agent", pi_agent_node)
          .add_node("data_scout", data_scout_node)
          .add_node("critic_agent", critic_agent_node)
          .add_node("meta_judge", meta_judge_node)
          .add_node("pi_review", pi_review_node)
          .add_node("error_handler", error_handler_node)
          .add_edge(...)  .add_conditional_edges(...)
          .compile()

     ═══════════════════════════════════════════════════════════
     Layer 1: Node Implementations（干活的人）                  ╯
     ═══════════════════════════════════════════════════════════

┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│ nodes/research_nodes │  │ nodes/analysis_nodes │  │ nodes/hitl_gate  │
│ .py                  │  │ .py                  │  │ .py              │
│                      │  │                      │  │                  │
│ pi_agent_node()      │  │ analyst_lead_node()  │  │ hitl_gate_node() │
│ data_scout_node()    │  │ synthesizer_node()   │  │                  │
│ critic_agent_node()  │  │ internal_reviewer_   │  │ 只用 state 和    │
│ meta_judge_node()    │  │   node()             │  │ langgraph.types  │
│ pi_review_node()     │  │ report_composer_     │  │                  │
│ error_handler_node() │  │   node()             │  │                  │
│                      │  │                      │  │                  │
│ 每个 = func(state)   │  │ 每个 = func(state)   │  │                  │
│       → dict         │  │       → dict         │  │                  │
│                      │  │                      │  │                  │
│ import:              │  │ import:              │  │                  │
│  state               │  │  state               │  │                  │
│  protocols/*         │  │  prompts/analysis    │  │                  │
│  prompts/research    │  │  SubagentExecutor    │  │                  │
│  SubagentExecutor    │  │                      │  │                  │
└──────┬───────────────┘  └──────┬───────────────┘  └──────────────────┘
       │                         │
       │    ═════════════════════╪══════════════════════════════════════
       │    Layer 0: Pure Data（只有被 import，不 import 项目内部）    ╯
       │    ═════════════════════╪══════════════════════════════════════
       │                         │
       ├── state.py              │  3 个 TypedDict，扩展 AgentState
       ├── protocols/messages.py │  Challenge / Rebuttal / Ruling
       ├── protocols/debate.py   │  DebateState FSM
       ├── prompts/research_*.py │  4 个角色 system prompt 字符串
       ├── prompts/analysis_*.py │  4 个角色 system prompt 字符串
       └── events.py             │  EventType 枚举 + StreamEvent

┌──────────────────────────────────────────────────────────────────┐
│ 横向基础设施（独立于调用层级，通过中间件机制注入）                   │
│                                                                   │
│ permissions/role_definition.py  ← Action 枚举 + ROLES 字典         │
│          ↑                                                        │
│ permissions/permission_guard.py ← AgentMiddleware, before_tool_call│
│                                                                   │
│ 这两个不参与图调用链，而是在 SubagentExecutor 执行工具时被 DF 中间件 │
│ 链自动触发。                                                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 一句话总结每个目录的角色

| 目录 | 角色 | 类比 |
|------|------|------|
| `state.py` | 数据模型 | 数据库表结构 |
| `prompts/` | 角色提示词 | 员工的岗位说明书 |
| `protocols/` | 协作消息格式 + 状态机 | 公司内部审批单模板 |
| `nodes/` | **干活的人**（每个函数是一个角色的一次行为） | 员工本人 |
| `subgraphs/` | **组装车间**（把 nodes 组装成图） | 部门组织架构 |
| `graph.py` | **总装车间**（把 subgraphs 组装成完整流程） | 公司组织架构 |
| `permissions/` | 门禁系统（横向拦截） | 门禁刷卡机 |
| `events.py` | 通知协议（横向推送） | 公司广播系统 |

---

## 文件导入关系（仅内部 import）

`subgraphs/` 确实是"偏向于总的调用其他几个"——它 import `nodes/`，被 `graph.py` import。`permissions/` 和 `events.py` 是横向切面，不在垂直调用链上。

```
graph.py
  ├── subgraphs/research_subgraph.py   → nodes/research_nodes.py
  │                                        → protocols/*
  │                                        → prompts/research_prompts.py
  ├── subgraphs/analysis_subgraph.py   → nodes/analysis_nodes.py
  │                                        → prompts/analysis_prompts.py
  ├── subgraphs/state_mapping.py       → state.py（纯函数，不 import 其他）
  ├── nodes/hitl_gate.py               → state.py
  └── nodes/analysis_nodes.py          → report_composer_node

permissions/permission_guard.py  → permissions/role_definition.py
                                    （横向：不经过 subgraphs 或 graph.py）
```
