# 05 — 对抗式批判协议

> **日期**: 2026-05-14 | **Sprint**: 2 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/protocols/messages.py`](../backend/packages/harness/deerflow/collaboration/protocols/messages.py) | Challenge/Rebuttal/Ruling 数据结构 |
| [`backend/packages/harness/deerflow/collaboration/protocols/debate.py`](../backend/packages/harness/deerflow/collaboration/protocols/debate.py) | DebateState 状态机 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py) | 使用协议的 Research SubGraph |

---

## Q1: 两个协议文件是给哪些 Graph 使用的？ `📄 messages.py` `📄 debate.py`

**A:** 只给 **Research SubGraph** 使用。三个 Graph 的职责边界：

```
Parent Graph         → 协调 Research → Analysis → HITL，不做内部数据验证
Research SubGraph    → ← 协议文件的使用者：Critic 质疑 → Scout 补采 → Judge 裁决
Analysis SubGraph    → 只管分析，不碰质疑/裁决逻辑
```

具体来说，Research SubGraph 内部的 6 个节点中，4 个直接使用这些协议：

| 节点 | 使用的类型 | 做什么 |
|------|----------|--------|
| `critic_agent_node` | `Challenge`, `DebateState.advance_to_critique()` | 生成结构化质疑，推进辩论 |
| `data_scout_node` | `Rebuttal`, `DebateState.advance_to_rebuttal()` | 定向补采，附带新数据 |
| `meta_judge_node` | `Ruling`, `DebateState.advance_to_adjudication()` | 独立裁决，产出质量评分 |
| `pi_review_node` | `Ruling`, `DebateState.complete()` | 审核裁决，生成 validated_brief |

---

## Q2: `DebateState` 的方法在哪里被调用？ `📄 debate.py`

**A:** 每个方法对应 Research SubGraph 工作流中的一步。下面追踪完整调用链。

**前提：DebateState 存在哪里？**

`DebateState` 不直接作为 State 字段——它从 `ResearchSubGraphState` 的三个字段重建：

```python
# 在节点函数中从 State 重建 DebateState
debate_state = DebateState(
    current_round=state.get("debate_round", 0),
    challenges=state.get("challenges", []),   # Annotated[list, add]
    rebuttals=state.get("rebuttals", []),     # Annotated[list, add]
)
```

节点操作完后再把字段写回 State dict。

**完整调用链：**

```
① PI 规划完成，Scout 采集完成
   ↓
② critic_agent_node
   ├── 读取 state["scout_results"]
   ├── LLM 生成 Challenge 对象列表
   ├── 👉 debate_state.advance_to_critique(challenges)
   │   └── 副作用: phase→CRITIQUING, current_round+=1
   └── 返回 {"challenges": challenges, "debate_round": debate_state.current_round}

③ route_after_critic  ← 条件路由
   ├── 👉 debate_state.needs_rebuttal()?
   │   ├── True → 跳转到 "data_scout" (定向补采)
   │   └── False → 跳转到 "meta_judge" (裁决)
   │
   ├── [补采路径]
   │   ④ data_scout_node
   │     ├── 读取未回应的 Challenge，定向采集新数据
   │     ├── 生成 Rebuttal 对象
   │     ├── 👉 debate_state.advance_to_rebuttal(rebuttals)
   │     │   └── 副作用: phase→REBUTTAL, rebuttals 列表扩展
   │     └── 返回 {"rebuttals": rebuttals}
   │     ↓
   │   回到 ② critic_agent_node (重新审查，最多 2 轮)
   │
   └── [裁决路径]
       ⑤ meta_judge_node
         ├── 👉 remaining = debate_state.advance_to_adjudication()
         │   └── 副作用: phase→ADJUDICATING, 返回未解决数量
         ├── 基于计算验证生成 Ruling
         └── 返回 {"ruling": ruling}

⑥ pi_review_node
   ├── 审核 Ruling
   ├── 👉 unresolved_count = debate_state.complete(ruling)
   │   └── 副作用: phase→COMPLETE
   ├── 如果批准 → 生成 validated_brief
   └── 返回 {"validated_brief": brief}
```

**用时间轴表示**：

```
Round 1:
  Critic.advance_to_critique()  → 质疑 3 条
  route.needs_rebuttal()        → True
  Scout.advance_to_rebuttal()   → 回应 2 条
  Critic.advance_to_critique()  → 仍有 1 条未解决

Round 2:
  route.needs_rebuttal()        → True (can_continue, 还有质疑)
  Scout.advance_to_rebuttal()   → 回应 1 条
  Critic.advance_to_critique()  → 全部解决

  route.needs_rebuttal()        → False
  Judge.advance_to_adjudication() → remaining=0
  PI.complete(ruling)           → validated_brief quality_score=0.9
```

**每个方法被谁调用，一句话总结**：

| 方法 | 调用者 | 时机 |
|------|--------|------|
| `advance_to_critique()` | `critic_agent_node` | Critic 审查完 scout_results 后 |
| `needs_rebuttal()` | `route_after_critic` | 条件路由：决定补采还是裁决 |
| `advance_to_rebuttal()` | `data_scout_node` | Scout 补采完新数据后 |
| `advance_to_adjudication()` | `meta_judge_node` | Judge 开始独立裁决前 |
| `complete()` | `pi_review_node` | PI 审核裁决后，结束辩论 |

---

## Q3: 四个角色 Prompt 的核心区别是什么？ `📄 research_prompts.py`

**A:** 四个 prompt 是四权分立在 LLM 层面的编码——越往下自由度越小，权威越高。

| 角色 | 核心指令 | 权限底线 | 输出要求 |
|------|---------|---------|---------|
| **PI Agent** | 你是研究主管，规划任务、分发 Scouts、审核裁决书 | 不能自己采数据，不能当裁判。推翻裁决必须书面解释 | `validated_brief`：验证过的数据点 + 被驳回的声索 + 质量分 |
| **Data Scout** | 你是数据采集员，从网络/文件/Python 拿数据 | 不能质疑别人，不能做裁决。回应 Critic 质疑必须带新数据 | `{source, content, data_points, methods}` |
| **Critic Agent** | 你是审查官，找一切数据里的矛盾、漏洞、过期、偏见 | 每一条质疑必须引用具体证据。不能自己采数据，不能做裁决 | `{challenge_id, claim, evidence[], severity, suggested_remedy}` |
| **Meta-Judge** | 你是独立裁决官，只看证据不看身份，用 Python 计算验证 | 裁决前至少跑一次 Python 统计检验。不能采数据、不能质疑、不能合成 | `{ruling_id, resolved[], unresolved[], quality_score, computation_summary}` |

**自由度与权威的梯度**：

```
高自由度 ← Scout（什么工具都能用，想搜什么搜什么）
           ↓
         Critic（只能读文件 + Python，不能搜新东西）
           ↓
         Judge（只能读文件 + Python，必须跑统计检验）
           ↓
低自由度 → PI（只能读文件，只管审批不管执行）

低权威 ← Scout（收集原始数据，谁都可以质疑）
           ↓
         Critic（质疑需要证据，但质疑本身可被 Judge 驳回）
           ↓
         Judge（裁决不可被同級推翻，只有 PI 能推翻且需审计）
           ↓
高权威 → PI（最终审批权，但推翻裁决要记录审计日志）
```

这种设计的源头是 ClawdLab 论文：**质疑者（Critic）和裁决者（Judge）分离**——解决了"自己质疑自己裁决"的结构性公正缺陷。

---

> **已完成文档**: [01](01-state-system.md) | [02](02-subgraph-design.md) | [03](03-graph-orchestration.md) | [04](04-testing-patterns.md)
