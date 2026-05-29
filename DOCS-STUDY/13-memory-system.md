# 13 — 协作记忆系统：来源可信度 + 产品知识库双轨记忆

> **日期**: 2026-05-19 | **Phase**: 4 P3 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/memory/__init__.py`](../backend/packages/harness/deerflow/collaboration/memory/__init__.py) | Memory 模块入口，导出两个 Memory 类 |
| [`backend/packages/harness/deerflow/collaboration/memory/source_credibility.py`](../backend/packages/harness/deerflow/collaboration/memory/source_credibility.py) | 来源可信度记忆（200 行），基于 Critic→Meta-Judge 验证闭环累积域名评分 |
| [`backend/packages/harness/deerflow/collaboration/memory/product_knowledge.py`](../backend/packages/harness/deerflow/collaboration/memory/product_knowledge.py) | 产品知识记忆（170 行），跨 run 累积已验证数据点，检测收敛/分歧 |
| [`backend/packages/harness/deerflow/collaboration/nodes/research_nodes.py`](../backend/packages/harness/deerflow/collaboration/nodes/research_nodes.py) | 三个节点（critic/judge/pi_review）各挂载 Memory 触发钩子 |
| [`backend/packages/harness/deerflow/collaboration/state.py`](../backend/packages/harness/deerflow/collaboration/state.py) | 两个 State 新增 `source_credibility_memory` / `product_knowledge_memory` 字段 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py) | State Mapping 函数传递 Memory 数据（父→子、子→父） |
| [`backend/tests/test_collaboration_memory.py`](../backend/tests/test_collaboration_memory.py) | 29 个单元测试（域提取、评分更新、钳位、裁剪、节点集成） |

---

## Q1: memory 目录下的两个文件分别干什么？

### source_credibility.py — 来源可信度记忆

**一句话**: 利用对抗式验证流程（Critic 质疑→Meta-Judge 裁决）的"副作用"，自动累积数据源的可靠性评分。

**核心机制**:
- 每个数据源（按域名归一化，如 `apple.com`、`gsmarena.com`）有一个 0.0~1.0 的可信度分数
- 初始值 `DEFAULT_SCORE = 0.50`（中性），即未知来源既不全信也不全疑
- Meta-Judge 裁决后自动更新：
  - **Resolved**（挑战被解决，来源数据经受住考验）→ `+0.05` boost
  - **Unresolved**（挑战无法解决，来源数据有问题）→ `-0.10` penalty
  - **Dismissed**（挑战被驳回，噪声）→ `-0.02` 微调
- Critic 提交质疑时记录涉及的 domain（不改分，做审计追踪）
- 超过 200 个 domain 时自动裁剪低质量条目（用 `verified_count - failed_count` 排序）

**关键 API**:
```python
mem = SourceCredibilityMemory.from_state(state.get("source_credibility_memory"))
mem.apply_challenges(challenges)          # Critic 提交质疑 → 记录 domain
mem.apply_ruling(ruling, scout_results)   # Judge 裁决 → 调整分数
state["source_credibility_memory"] = mem.to_dict()  # 写回 State → Checkpointer 持久化
```

### product_knowledge.py — 产品知识记忆

**一句话**: 跨 run 累积已验证的产品数据点。多次独立研究对同一数据点达成一致时，置信度自动提升。

**核心机制**:
- 每次 PI Review 确认 `validated_brief` 后，`ingest_brief()` 将数据点合并到产品知识库
- 只存储置信度 ≥ `MIN_CONFIDENCE_FOR_STORAGE (0.6)` 的数据点
- **Convergence（收敛）**: 新来源与已存值一致 → `confidence += 0.05`，`sources += 1`
- **Divergence（分歧）**: 新来源与已存值不一致 → 创建 `_alt_` 备选条目，标记分歧
- 5% 容差数值匹配（如 4000mAh vs 4050mAh 视为一致）
- `query_product("iPhone 17")` 支持模糊匹配（case-insensitive substring）

---

## Q2: 这些新增文件和修改点之间，一个完整的 Memory 协作流转过程是怎样的？

以下是一次研究 run 中 Memory 数据的完整生命周期：

```
┌─────────────────────────────────────────────────────────────────┐
│  1. 初始化（Parent Graph）                                       │
│                                                                 │
│  CollaborationState.source_credibility_memory = None             │
│  CollaborationState.product_knowledge_memory = None              │
│  → map_parent_to_research() 将 memory 字段传入选                                                 │
│  ResearchSubGraphState                                           │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│  2. Critic Agent — 记录质疑的 source domains                     │
│     (research_nodes.py:323-338)                                  │
│                                                                 │
│  critic_agent_node() 执行后:                                     │
│    if challenges:                                                │
│      src_mem = SourceCredibilityMemory.from_state(               │
│          state.get("source_credibility_memory"))                 │
│      src_mem.apply_challenges(challenges)  ← 解析证据URL提取domain│
│      return {                                                    │
│        "challenges": [...],                                      │
│        "source_credibility_memory": src_mem.to_dict()  ← 写回State│
│      }                                                           │
│                                                                 │
│  此时: 不改变分数，只记录 domain 和 sample_topics（审计追踪）      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│  3. Meta-Judge — 根据裁决结果调整可信度分数                       │
│     (research_nodes.go:397-401)                                  │
│                                                                 │
│  meta_judge_node() 执行后:                                       │
│    src_mem = SourceCredibilityMemory.from_state(                 │
│        state.get("source_credibility_memory"))                   │
│    src_mem.apply_ruling(ruling_data, scout_results)              │
│      → resolved challenges: domain.score += 0.05                 │
│      → unresolved: domain.score -= 0.10                          │
│      → dismissed: domain.score -= 0.02                           │
│      → _prune_stale() 裁剪超过200个domain的低质条目               │
│    return {                                                      │
│      "ruling": {...},                                            │
│      "source_credibility_memory": src_mem.to_dict()  ← 持久化    │
│    }                                                             │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│  4. PI Review — 验证数据点存入产品知识库                          │
│     (research_nodes.go:464-471)                                    │
│                                                                 │
│  pi_review_node() 执行后:                                        │
│    if validated_brief:                                           │
│      prod_mem = ProductKnowledgeMemory.from_state(               │
│          state.get("product_knowledge_memory"))                  │
│      prod_mem.ingest_brief(validated_brief, quality_score)       │
│        → 仅存储 confidence ≥ 0.6 的数据点                        │
│        → 新值与已存值一致 → convergence boost (+0.05)            │
│        → 新值与已存值不同 → divergence (创建 _alt_ 条目)          │
│    return {                                                      │
│      "validated_brief": {...},                                   │
│      "product_knowledge_memory": prod_mem.to_dict()  ← 持久化    │
│    }                                                             │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│  5. State Mapping — Memory 数据回流到 Parent Graph               │
│     (state_mapping.py: map_research_to_parent)                   │
│                                                                 │
│  src_mem = child_state.get("source_credibility_memory")          │
│  if src_mem is not None:                                         │
│      result["source_credibility_memory"] = src_mem               │
│  prod_mem = child_state.get("product_knowledge_memory")          │
│  if prod_mem is not None:                                        │
│      result["product_knowledge_memory"] = prod_mem               │
│                                                                 │
│  → Checkpointer 自动将 CollaborationState 持久化到 SQLite/Postgres│
│  → 下一次 run 时，Memory 数据随 State 恢复，实现跨 run 累积       │
└─────────────────────────────────────────────────────────────────┘
```

**关键设计决策**:

1. **Memory 更新被 try/except 包裹** — Memory 更新失败只打 debug 日志，绝不阻塞主分析流程。这是"双流并行"架构的核心保障。

2. **State 作为传输介质而非直接文件 I/O** — Memory 数据嵌入 `CollaborationState`，通过 LangGraph Checkpointer 自动持久化。这比直接写文件有两个优势：（a）Checkpointer 的原子性和事务性；（b）父子图 State Mapping 自然地保证了数据一致性。

3. **分数更新是线性的、简单的** — 刻意不用复杂的 Bayesian 更新或 ML 模型。当前用固定增量更新，方便调试和审计。以后可插拔更复杂的算法（Beta 分布后验、时间衰减等）。

---

## Q3: 来源可信度记忆为什么是"神来之笔"？它是 PA-Agent-DF 的核心技术壁垒之一

**核心价值**: 传统 Agent 每次研究从零开始，不记得哪些数据源靠谱。PA-Agent-DF 利用对抗式验证流程的"副作用"，自动累积来源评分，使系统随使用次数增多而变得更聪明。

**差异化分析**:

| 维度 | 传统 RAG | 传统 ReAct Agent | CrewAI 角色化 | **PA-Agent-DF** |
|------|---------|-----------------|-------------|-----------------|
| 数据源记忆 | 无 | 无 | 无 | **自动累积域名评分** |
| 验证机制 | 无 | 无 | 无 | **Critic→Judge 闭环驱动更新** |
| 跨 run 学习 | 无 | 无 | 无 | **Checkpointer 持久化，越用越聪明** |
| 评分可审计 | — | — | — | **verified_count / failed_count 完整追踪** |

**未来扩展方向**（已在 project memory 中标记）:
- Bayesian 更新（Beta 分布后验替代线性加减）
- 冷启动信任网络（预置官方来源高分，如 `apple.com`、`reuters.com`）
- 跨用户共享评分（社区信任共识网络）
- 时间衰减（长期未验证的来源回归中性分）
- PageRank 式来源互引图
- 与向量数据库联动（retrieval 结果按 credibility score 重排序）

---

## Q4: Memory 和向量数据库的异同与互补关系

这不是"二选一"的问题——两者解决的是不同维度的问题，是互补关系。

### 核心差异

| 维度 | 向量数据库（Qdrant/Milvus/PGVector） | 协作记忆（SourceCredibility + ProductKnowledge） |
|------|--------------------------------------|--------------------------------------------------|
| **解决的问题** | "找到相关内容" — 基于语义相似度 | "判断内容是否可信" — 基于历史验证记录 |
| **数据粒度** | 文档片段/embedding vector | 域名级评分 / 产品属性键值对 |
| **更新方式** | 写入新文档 / 重新 embedding | Critic→Judge 验证闭环的"副作用" |
| **查询方式** | `query_vector(query_embedding, top_k=10)` | `mem.get_score("gsmarena.com")` |
| **学习能力** | 不学习（被动存储） | 主动学习（验证结果反馈评分） |
| **一致性要求** | 低（向量略变不影响检索） | 高（评分变化直接影响信任决策） |

### 互补关系

```
用户的查询 "iPhone 17 电池容量"
        │
        ▼
┌──────────────────────────────────┐
│  向量数据库（语义检索）            │
│  找到包含 "iPhone 17 battery"     │
│  的所有文档片段 → 10 条候选结果    │
│  来源: apple.com, gsmarena.com,   │
│        reddit.com, cnbeta.com...  │
└──────────┬───────────────────────┘
           │ 10 条候先结果
           ▼
┌──────────────────────────────────┐
│  协作记忆（可信度过滤）            │
│  apple.com → 0.95 (官方, 已验证×12)│
│  gsmarena.com → 0.78 (专业, 已验证×8)│
│  reddit.com → 0.40 (社交, 未验证)   │
│  cnbeta.com → 0.35 (低质, 失败×3)   │
│                                    │
│  重排序: 高可信度优先               │
│  排除: < 0.3 的直接丢弃             │
└──────────┬───────────────────────┘
           │ 只有可信来源的数据进入
           ▼
      分析管道（Synthesizer）
```

**一句话总结**: 向量数据库负责"找到相关内容"，协作记忆负责"判断内容是否可信"。两者联手 = 既有广度又有深度。

---

## Q5: 这个 Memory 机制是否产生了"双流并行"的架构效果？

是的。虽然当前实现在代码上是同步调用（Memory 更新嵌在节点返回里），但架构设计上已经实现了"双流并行"的语义：

```
主分析流（Primary Flow）               记忆积累流（Background Flow）
========================               =============================

PI → Scouts → Critic → Judge → PI     Critic 质疑 → 记录 domain
     │         │         │       │     Judge 裁决 → 调整分数
     │         │         │       │     PI Review → 数据点入库
     ▼         ▼         ▼       ▼
  分析报告 ← ← ← ← ← ← ← ← ← ←┘      Memory 数据随 State 持久化
                                          │
                                          ▼
                                     下一 run 自动加载（越用越聪明）
```

**零耦合设计**: Memory 更新失败只打 `logger.debug`，绝不抛异常阻塞主流程。这意味着即使 Memory 逻辑出 bug，分析报告仍然正常生成。

**Checkpointer 驱动的被动持久化**: 不需要后台线程、不需要定时 flush——State 字段被 LangGraph Checkpointer 在每次 `checkpoint()` 时自动序列化。这比传统的"后台线程写数据库"模式更简洁、更可靠。

---

## 编码要点回顾

1. **`_extract_domain()`** — 从 URL/字符串归一化提取域名，处理 `https://`、`www.`、路径、查询参数
2. **`apply_ruling()` 的 `_domain_matches()`** — resolved/unresolved items 只包含 `challenge_id`/`issue`/`reason` 文本字段，需要通过子串匹配来判断与 domain 的关联
3. **`ingest_brief()` 的重构** — 原来在 `verified_data_points` 为空时提前返回，导致没有创建 product 条目。修复为始终调用 `_ensure_product()` 先创建条目
4. **Mock path 的注意事项** — 节点内函数本地导入 `SubagentExecutor`，mock 路径必须是 `deerflow.subagents.executor.SubagentExecutor`，不能是 `deerflow.collaboration.nodes.research_nodes.SubagentExecutor`
5. **`_values_match()` 的 5% 容差** — 4000mAh vs 4050mAh 视为一致，避免浮点精度问题导致的假性分歧

---

> **Phase 4 P3 完成。Memory 双轨（来源可信度 + 产品知识）已实装，29 个测试通过。**
> 关键记忆: [source-credibility-architecture](../.claude/projects/-root-Projects-deer-flow/memory/source-credibility-architecture.md)
