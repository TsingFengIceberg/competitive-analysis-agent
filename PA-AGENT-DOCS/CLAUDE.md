# PA-Agent-DF 开发指令与架构规约

> **Phase 2 输出** | **日期**: 2026-05-14 | **基于**: PA-Agent-DF-architecture.md v2.0

---

## 0. 学习优先声明

> **本项目同时服务于两个目标：**
> 1. **学习实践** — 深入理解 LangGraph 多智能体架构、DeerFlow 框架内部机制、对抗式批判协议等 2026 年前沿 Agent 技术
> 2. **工程产出** — 构建一个具有技术壁垒的泛商品协同分析系统

**编码时须遵循"边做边讲"原则：**

- **遇到新模块时** — 先简要说明该模块在 DF 框架中的角色和设计意图（1-3 句话），再开始编码
- **关键设计决策时** — 解释 WHY（例如：为什么用 Nested SubGraph 而不是单图？为什么 State Mapping 必须是纯函数？），不只看 WHAT
- **LangGraph API 使用时** — 点明 API 的语义差异（如 `add_node` vs `add_node(subgraph, state_in=fn)`、`interrupt()` 的 checkpoint 行为）
- **DF 框架机制时** — 揭示"为什么 DF 这样设计"（如 18 个中间件的顺序为何严格、SubagentExecutor 的双线程池设计）
- **不解释的部分** — 纯 Python 语法、类型注解写法、变量命名等语言层面内容，假设已知

**学习节奏控制：**
- 每个新概念/模块首次出现时做完整解释，后续同类不再重复
- 解释放在代码注释中（1-2 行短注释），避免大段文档阻塞编码
- 如果某个知识点值得深入，在代码写完后提一句"这个机制值得单独精讲"

---

## 1. 项目身份与战略目标

### 1.1 项目定位

**PA-Agent-DF** (Pan-Product Analysis Agent on DeerFlow) 是一个基于 ByteDance DeerFlow 框架的**泛商品协同分析 AI 系统**。它不局限于传统竞品分析，而是围绕商品/电商数据展开复杂分析任务的多智能体协作系统。

**核心差异化**: 系统表现为一个"数字调研小组"——多个专门化 AI Agent 以结构化协作协议完成数据采集、交叉验证、多维度分析和报告生成。

### 1.2 战略目标 (Resume-Driven Development)

- **超越玩具级项目**: 架构上必须超越市面上普遍的"单 Agent + ReAct 循环"模式
- **体现前沿特性**: LangGraph 图编排、Human-in-the-Loop、自纠正研究循环、流式响应、并行并发
- **对标学术界**: 参考 2026 年 Bioptic Agent 等前沿论文的设计思路
- **生产级工程质量**: Checkpointer 持久化、幂等性、审计追踪、Stale State 检测

### 1.3 竞品差异化矩阵

| 维度 | 典型 ReAct Agent | CrewAI 角色化 | **PA-Agent-DF** |
|------|-----------------|-------------|-----------------|
| 流程控制 | 线性 Tool Calling | 顺序任务链 | **图式 DAG + 条件路由 + 动态重规划** |
| 数据质量 | 无验证 | 无验证 | **Cross-Validator + 自纠正循环** |
| 人机协作 | 无 | 有限 | **LangGraph 2.0 interrupt() HITL Gate** |
| 状态管理 | 对话历史 | 隐式 | **TypedDict State + PostgresSaver** |
| 协作模式 | 无 | 角色扮演 | **Supervisor + 受限 Swarm 混合** |
| 并行执行 | 无 | 有限 | **LangGraph Send API Fan-out** |

---

## 2. 核心架构约束 — DeerFlow-First 铁律

### 2.1 优先级规则

```
DeerFlow 原生实现 > 外围封装/适配器 > 引入外部框架 > 从零自建
```

**具体应用**:
- Agent 创建：使用 `deerflow.agents.lead_agent` 的 `create_agent()`，不直接使用 LangChain 的 `create_agent()`
- 沙箱操作：全部通过 `deerflow.sandbox.tools` 的 `ensure_sandbox_initialized()`，不绕过虚拟路径系统
- 子代理执行：协作节点封装 `deerflow.subagents.executor.SubagentExecutor`，不自己实现 Agent 循环
- 工具系统：复用 `deerflow.tools.get_available_tools()` 加载工具，通过 `SubagentConfig.tools` 白名单控制
- 中间件：复用 DeerFlow 18 个中间件链，通过插入 `CollaborationMiddleware` 扩展而非替换
- 配置：扩展 `config.yaml` 的 `collaboration` 段，使用 `deerflow.config` 的热加载机制
- Checkpointer：使用 DeerFlow 已有的 LangGraph Checkpointer 基础设施
- **DF 基座最大化利用**: 不只用 DF 的"壳"（Agent 框架），更要用 DF 的"核"——沙箱 Python 计算（pandas/scipy/sklearn）、Skills 系统（8 个分析 Skills）、Memory 系统（来源可信度+产品知识库双轨）、文件上传+文档自动转换、Community Tools 全工具链（firecrawl/image_search/jina_ai）、MCP 外部服务协议。编码时必须逐项确认每个 DF 能力是否被充分利用。

### 2.2 架构边界 (不可违反)

```
Harness (deerflow.*)  ─── 绝不 import ───>  App (app.*)
                      ◄── 可以 import ─────
```

- 协作系统核心逻辑放在 `deerflow/collaboration/` (Harness 层)
- HITL 恢复 API 放在 `app/gateway/routers/collaboration.py` (App 层)
- `test_harness_boundary.py` 在 CI 中自动执行边界检查

### 2.3 DeerFlow 底座复用矩阵

| DeerFlow 组件 | 复用方式 | 关键 API |
|-------------|---------|---------|
| Sandbox | 直接复用 | `ensure_sandbox_initialized(runtime)` |
| SubagentExecutor | 包装复用 | `SubagentExecutor(config, tools, ...).execute(task)` |
| Tools | 白名单复用 | `get_available_tools(groups=...)` |
| Middlewares | 扩展复用 | `_build_middlewares()` + 自定义注入 |
| Memory | 扩展复用 | `MemoryMiddleware` + 协作记忆维度 |
| Checkpointer | 升级复用 | `SqliteSaver` → `PostgresSaver` |
| Config | 扩展复用 | `config.yaml` 增加 `collaboration` 段 |
| Stream Bridge | 直接复用 | `stream_mode=["custom", "values"]` |

---

## 3. 协作系统架构：ClawdLab + Nested SubGraph

### 3.1 架构三层融合

| 层级 | 来源 | 角色 | 核心机制 |
|------|------|------|---------|
| **底座层** | DeerFlow | — | Sandbox、SubagentExecutor、Tools、Middleware、Checkpointer |
| **协作协议层** | ClawdLab (arXiv 2602.19810) | PI、Critic、Meta-Judge | 对抗式批判前置、四权分立、角色门控、计算验证接地 |
| **工程结构层** | LangGraph Nested SubGraph | Parent + 2 SubGraphs | State 隔离、命名空间隔离、独立编译、失败隔离 |

### 3.2 双层 SubGraph + 对抗式验证核心

```
┌──────────────────────────────────────────────────────────────┐
│                      Parent Graph                             │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │         Research SubGraph (独立编译, 独立 State)        │    │
│  │                                                       │    │
│  │  PI Agent ──→ Scouts (Send 并行)                       │    │
│  │    │              │                                    │    │
│  │    │         ┌────▼─────┐                              │    │
│  │    │         │  Critic   │ ← 对抗式质疑 (合成前!)        │    │
│  │    │         └────┬─────┘                              │    │
│  │    │    ┌─────────▼──────────┐                         │    │
│  │    │    │ issues? → Scouts   │  ← 最多2轮              │    │
│  │    │    │ clean?  → Judge    │                         │    │
│  │    │    └─────────┬──────────┘                         │    │
│  │    └──────► Meta-Judge (独立裁决)                       │    │
│  │                 │                                      │    │
│  │            PI 审核 → ValidatedBrief                    │    │
│  └─────────────────┬────────────────────────────────────┘    │
│                    │ (State Mapping: 只传精炼结果)            │
│  ┌─────────────────▼────────────────────────────────────┐    │
│  │        Analysis SubGraph (独立编译, 独立 State)         │    │
│  │                                                       │    │
│  │  Analyst Lead → Synthesizer → Internal Reviewer        │    │
│  │                                    │                   │    │
│  │                              SynthesisReport            │    │
│  └─────────────────┬────────────────────────────────────┘    │
│                    │                                          │
│         ┌──────────▼──────────┐                               │
│         │     HITL Gate       │  (Parent 层)                   │
│         └──────────┬──────────┘                               │
│         ┌──────────▼──────────┐                               │
│         │  Report Composer    │  (Parent 层)                   │
│         └─────────────────────┘                               │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 八角色配置

| 角色 | 层级 | 模型 | Thinking | 工具 | Skills | max_turns | 权限约束 |
|------|------|------|----------|------|--------|-----------|---------|
| **PI Agent** | Research SubGraph | `claude-opus-4-7` | on | `read_file` | — | 15 | 可推翻裁决(需审计) |
| **Data Scout** (×2-4) | Research SubGraph | `inherit` | off | `web_search`, `web_fetch`, `firecrawl`, `python`, `write_file` | `data-normalizer`, `sentiment-analyzer` | 30 | 不可质疑/裁决/合成 |
| **Critic Agent** | Research SubGraph | `claude-opus-4-7` | on | `read_file`, `python` | `source-credibility` | 30 | 质疑必须附证据, 不可采集/裁决 |
| **Meta-Judge** | Research SubGraph | `claude-opus-4-7` | on | `read_file`, `python` | — | 25 | 不可采集/质疑/合成, 裁决必须引证据 |
| **Analyst Lead** | Analysis SubGraph | `claude-opus-4-7` | on | `read_file` | — | 15 | 不可修改验证数据 |
| **Synthesizer** | Analysis SubGraph | `claude-opus-4-7` | on | `read_file`, `python`, `write_file` | `spec-comparator`, `price-elasticity`, `market-share-calc`, `trend-detector` | 50 | — |
| **Internal Reviewer** | Analysis SubGraph | `inherit` | off | `read_file`, `python` | — | 15 | — |
| **Report Composer** | Parent Graph | `inherit` | off | `write_file`, `python`, `bash`, `present_files` | `swot-generator` | 40 | — |

### 3.4 四个协作协议

**协议 1 — 任务分发与采集 (PI → Send API → Scouts)**:
```
PI 拆解任务 → Send API Fan-out → [Scout A, B, C] → 返回结构化 JSON → PI 汇总
```

**协议 2 — 对抗式批判协议 (ClawdLab 核心 — Critic ⇄ Scouts → Meta-Judge → PI)**:
```
PI 汇总完成 → Critic 审查 → 生成 Challenge[] (每条必须附证据)
  → [有问题] → 指定 Scout 定向补采 → Rebuttal (附带新证据)
    → Critic 重新评估 (最多 2 轮)
      → Meta-Judge 独立裁决 (只看证据, 不站队)
        → PI 审核 → 批准/推翻(需审计日志)
          → ValidatedBrief
```

**协议 3 — SubGraph 间通信 (State Mapping)**:
```
Research SubGraph 输出 (ChildState) ──state_out──→ ParentState.validated_brief
ParentState.validated_brief ──state_in──→ Analysis SubGraph 输入 (ChildState)
```

**协议 4 — 人类审批 (HITL Gate, Parent Graph 层)**:
```
Analysis SubGraph 输出 → HITL Gate (interrupt)
  → approve → Report Composer
  → modify → Analysis SubGraph (重新合成)
  → replan → Research SubGraph (重新规划)
```

### 3.5 四权分立

| 权力 | 角色 | 约束 |
|------|------|------|
| **质疑权** | Critic Agent | 必须附证据, 不可自行采集 |
| **执行权** | Data Scout | 可采集+回应质疑, 不可质疑/裁决 |
| **裁决权** | Meta-Judge | 只看证据不站队, 不可采集/质疑/合成 |
| **监督权** | PI Agent + HITL Gate | PI 可推翻裁决(需审计), HITL 可重定向 |

**关键**: 质疑者(Critic)和裁决者(Judge)分离——解决了传统 Cross-Validator "自己质疑自己裁决"的结构性问题。

### 3.6 工作流阶段

```
Research SubGraph: planning → collecting ⇄ (critique → recollect) → adjudicating → output
     │
     ▼ (State Mapping)
Analysis SubGraph: analyzing → synthesizing → internal_review → output
     │
     ▼ (State Mapping)
Parent Graph: hitl_review → composing → done
```

---

## 4. LangGraph 编排规约：Nested SubGraph + 角色门控

### 4.1 架构模式：Nested SubGraph (Parent + 2 SubGraphs)

```
Parent Graph (CollaborationState)
├── Research SubGraph (ResearchSubGraphState, 独立编译)
│   Internal: PI → Scouts(Send) → Critic ⇄ Scouts → Meta-Judge → PI Review
│   State Mapping: state_out → Parent.validated_brief
│
├── Analysis SubGraph (AnalysisSubGraphState, 独立编译)
│   Internal: Analyst Lead → Synthesizer → Internal Reviewer
│   State Mapping: state_in ← Parent.validated_brief, state_out → Parent.synthesis_report
│
├── HITL Gate (Parent 层)
└── Report Composer (Parent 层)
```

### 4.2 SubGraph 构建规范

**Research SubGraph 必须实现的节点**:
```python
nodes = [
    "pi_agent",          # PI — 规划 + Send API Fan-out + 审核裁决
    "data_scout",         # Worker — 并行采集 + 回应 Critic
    "critic_agent",       # Critic — 对抗式质疑 (Challenge JSON)
    "meta_judge",         # Judge — 独立裁决 (Ruling JSON)
    "pi_review",          # Gate — PI 审核裁决书 (批准/推翻)
    "error_handler",      # Fallback — error 字段上浮
]
```

**Analysis SubGraph 必须实现的节点**:
```python
nodes = [
    "analyst_lead",       # Supervisor — 调度分析流程
    "synthesizer",        # Analyst — 多维对比 + SWOT + 趋势 + 建议
    "internal_reviewer",  # Reviewer — 分析质量内审
]
```

### 4.3 State Mapping 规范 (生产级)

```python
# Research SubGraph → Parent
def map_research_to_parent(child_state: ResearchSubGraphState,
                           parent_state: CollaborationState) -> dict:
    return {
        "validated_brief": child_state.get("validated_brief"),
        "research_quality_score": child_state.get("research_quality_score"),
        "unresolved_issues": child_state.get("unresolved_issues", []),
        "research_error": child_state.get("error"),  # 子图异常上浮
    }

# Parent → Analysis SubGraph
def map_parent_to_analysis(parent_state: CollaborationState) -> dict:
    return {
        "validated_brief": parent_state.get("validated_brief"),
        "research_quality_score": parent_state.get("research_quality_score"),
        "unresolved_issues": parent_state.get("unresolved_issues", []),
    }
```

**关键规则**:
- State Mapping 是纯函数 (无副作用)
- 子图 State 严格投影 (不依赖父图其他字段)
- 子图异常通过 `error` 字段上浮 (父图条件边降级)
- 父子图共享同一 PostgresSaver (保证 checkpoint 一致性)
- 每 SubGraph 独立 `checkpoint_ns` (防并行碰撞)

### 4.4 角色门控治理

```python
ROLE_PERMISSIONS = {
    "pi_agent":    {"allowed": ["plan","dispatch","review","override_critic"],
                    "audit": ["override_critic"]},
    "data_scout":  {"allowed": ["search","fetch","respond_to_critic"],
                    "evidence": ["respond_to_critic"]},
    "critic_agent":{"allowed": ["challenge","read_data"],
                    "evidence": ["challenge"]},
    "meta_judge":  {"allowed": ["adjudicate","read_data","run_verification"],
                    "evidence": ["adjudicate"]},
}
```

在 `PermissionGuardMiddleware.before_tool_call()` 中检查：
1. 角色是否允许该操作 → 拒绝/放行
2. 操作是否需要附带证据 → 验证/拒绝
3. 操作是否需要审计日志 → 记录/跳过

### 4.5 LangGraph 2.0 API 使用规范

| 场景 | API | 注意事项 |
|------|-----|---------|
| SubGraph 挂载 | `parent.add_node("name", compiled_subgraph, state_in=fn, state_out=fn)` | 必须先 `.compile()` |
| 并行 Fan-out | `Send(node, arg)` | 返回 `list[Send]`，在 SubGraph 内部使用 |
| 动态路由 | `add_conditional_edges(src, router, path_map)` | SubGraph 内和 Parent 层都用 |
| 人类审批 | `interrupt(payload)` + `Command(resume=data)` | Parent 层, `interrupt_before` 语义 |
| 状态累加 | `Annotated[list, add]` reducer | scout_results 等累加字段 |
| Checkpoint | `PostgresSaver` (生产) | 父子图共享同一实例 |
| 命名空间 | `checkpoint_ns` | 每 SubGraph 独立，防碰撞 |
| 失败传播 | `error` 字段 + 条件边降级 | 子图异常不冒泡 |

---

## 5. 目录结构

### 5.1 新增文件清单

```
backend/packages/harness/deerflow/
├── collaboration/                        # 协作系统核心 (Harness 层)
│   ├── __init__.py
│   ├── graph.py                          # Parent Graph + Nested SubGraph 组装
│   ├── state.py                          # 三层 State 定义
│   ├── subgraphs/                        # SubGraph 构建
│   │   ├── __init__.py
│   │   ├── research_subgraph.py          # Research SubGraph
│   │   ├── analysis_subgraph.py          # Analysis SubGraph
│   │   └── state_mapping.py             # State Mapping 函数
│   ├── nodes/                            # 图节点 (8 个角色)
│   │   ├── __init__.py
│   │   ├── pi_agent.py                   # PI Agent
│   │   ├── data_scout.py                 # Data Scout
│   │   ├── critic_agent.py               # Critic Agent
│   │   ├── meta_judge.py                 # Meta-Judge
│   │   ├── analyst_lead.py               # Analyst Lead
│   │   ├── synthesizer.py                # Synthesizer
│   │   ├── internal_reviewer.py          # Internal Reviewer
│   │   ├── hitl_gate.py                  # HITL Gate
│   │   ├── report_composer.py            # Report Composer
│   │   └── error_handler.py              # 全局错误处理
│   ├── prompts/                          # 角色提示词 (8 个)
│   ├── permissions/                      # 角色门控
│   │   ├── role_definition.py            # RolePermission 定义
│   │   └── permission_guard.py           # PermissionGuardMiddleware
│   ├── protocols/                        # 协作协议
│   │   ├── messages.py                   # Challenge/Rebuttal/Ruling
│   │   └── debate.py                     # 对抗式批判状态机
│   ├── events.py                         # 流式事件
│   └── router.py                         # 条件路由
├── agents/
│   └── middlewares/
│       └── collaboration_middleware.py    # 协作上下文注入 + 角色标记
└── config/
    └── collaboration_config.py           # 协作配置 (含 RoleGateConfig)

backend/app/gateway/routers/
└── collaboration.py                      # HITL 恢复 API (App 层)

backend/tests/
├── test_collaboration_graph.py           # Parent Graph + SubGraph 挂载
├── test_collaboration_subgraphs.py       # SubGraph 独立编译 + State Mapping
├── test_collaboration_nodes.py           # 8 角色节点单元测试
├── test_collaboration_critic_judge.py    # Critic+Judge 对抗式批判集成
├── test_collaboration_permissions.py     # 角色门控测试
├── test_collaboration_hitl.py            # HITL 全场景
├── test_collaboration_debate.py          # 质疑-回应协议
└── test_collaboration_e2e.py             # 端到端
```

### 5.2 禁止修改的文件

以下 DeerFlow 核心文件**只读**，不允许任何修改:
- `backend/packages/harness/deerflow/sandbox/sandbox.py`
- `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`
- `backend/packages/harness/deerflow/sandbox/tools.py`
- `backend/packages/harness/deerflow/subagents/executor.py`
- `backend/packages/harness/deerflow/tools/tools.py`
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py` (仅可增加协作图入口路由)

---

## 6. 技术 USP 实现要求

### 6.1 USP #1: 对抗式批判验证循环 (Adversarial Critique Loop)

**核心机制**: Scouts 采集 → Critic 对抗式质疑 → Scouts 定向补采 → Meta-Judge 独立裁决 → PI 审核

**vs v1.0 自纠正循环的关键升级**:
- v1.0: Cross-Validator 单节点"自己质疑自己裁决" → 结构性公正缺陷
- v2.0: Critic(检察官) + Meta-Judge(法官) 分离 → 四权分立

**实现要点**:
- Critic 每条质疑必须附带证据 (引用具体数据点、来源对比)
- Meta-Judge 裁决基于计算工具输出，不基于"多数意见"
- 最多 2 轮质疑-补采循环，不可修复数据标记 `unresolved_issues`
- PI 可推翻裁决，但必须在 `pi_override_log` 中记录理由

**对标**: ClawdLab (arXiv 2602.19810) 对抗式批判前置 + Bioptic Agent (F1=79.7%)

### 6.2 USP #2: 人类在环协作审批门 (HITL Collaboration Gate)

**核心机制**: Synthesizer 完成后 → `interrupt()` 暂停 → 结构化审批界面 → 人类决策 → 恢复执行

**实现要点**:
- `interrupt_before` 语义（审批在动作执行前）
- 审批包包含：数据点数、质量分、关键发现、未解决问题
- 三个选项：approve / modify (重新合成) / replan (重新规划)
- Stale State 检测：超过 30 分钟未响应 → 提示过期
- 幂等性：检查 thread 是否已有 `review_decision`
- PostgresSaver 持久化，支持长时间暂停

### 6.3 USP #3 (候选，Phase 3 Sprint 4 评估): 协作记忆

- 来源可信度档案（基于历史验证结果的数据源评分）
- 领域知识图谱（商品-属性-来源-时间网络）
- 分析模板库（复用成功分析结构）

---

## 7. 配置规约

### 7.1 config.yaml 扩展

```yaml
collaboration:
  enabled: true
  default_workflow: "competitive_analysis"

  roles:
    orchestrator:
      model: "claude-opus-4-7"
      thinking_enabled: true
      max_turns: 15
    data_scout:
      model: "inherit"
      max_scouts: 3
      max_turns: 30
      timeout_seconds: 600
      tools: [web_search, web_fetch, firecrawl, python, write_file]
      skills: [data-normalizer, sentiment-analyzer]
    cross_validator:
      model: "claude-opus-4-7"
      thinking_enabled: true
      max_debate_rounds: 2
      quality_threshold: 0.7
      max_turns: 40
    synthesizer:
      model: "claude-opus-4-7"
      thinking_enabled: true
      max_turns: 50
      skills: [spec-comparator, price-elasticity, market-share-calc, trend-detector]
    report_composer:
      model: "inherit"
      max_turns: 40

  # Skills (DF Skills 系统)
  skills:
    enabled: true
    load_path: "skills/public"

  # Memory (DF Memory 系统扩展)
  memory:
    source_credibility:
      enabled: true
      update_trigger: "post_validation"
    product_knowledge:
      enabled: true
      update_trigger: "post_synthesis"

  hitl:
    enabled: true
    gates:
      - post_synthesis
    stale_timeout_minutes: 30
    require_audit_log: true

  checkpointer:
    backend: "postgres"
    checkpoint_ttl_days: 7

  workflows:
    competitive_analysis:
      scouts: 3
      phases: [planning, collecting, validating, synthesizing, reviewing, composing]
    market_trend:
      scouts: 2
      skip_validation: true
    pricing_optimization:
      scouts: 2
    supply_chain_risk:
      scouts: 3
```

---



## 8. 开发流程与测试规约

### 8.1 TDD 强制要求

**每个新文件必须对应至少一个测试文件。不通过测试的代码不得进入 Sprint 完成状态。**

```bash
# 开发循环
PYTHONPATH=backend/packages/harness:. uv run pytest tests/test_<feature>.py -v

# 全量回归 (每个 Sprint 结束前必须通过)
cd backend && make test
```

### 8.2 测试覆盖要求

| 测试文件 | 覆盖范围 | 最低覆盖率 |
|---------|---------|-----------|
| `test_collaboration_graph.py` | 图结构、节点注册、边连接、路由逻辑 | 90% |
| `test_collaboration_nodes.py` | 各节点的输入/输出/状态转换 (mock SubagentExecutor) | 85% |
| `test_collaboration_hitl.py` | interrupt/暂停/恢复/幂等/过期/双重恢复 | 95% |
| `test_collaboration_debate.py` | Challenge/Rebuttal 消息格式、循环轮次限制 | 90% |
| `test_collaboration_e2e.py` | 3 个完整场景的端到端流程 | 80% |

### 8.3 编码规范

- Python 3.12+，类型注解强制
- 使用 `ruff` (line length: 240)
- 所有协作节点函数签名使用 `CollaborationState -> dict`
- 节点内部使用 `SubagentExecutor`，不允许直接调用 LLM API
- 错误处理：节点异常 → `error_handler` 节点，不静默吞掉

### 8.4 提交规范

- 每个 Sprint 内独立 Commit (最小可测试单元)
- Commit message 格式: `sprint<N>: <description>`
- 禁止在 Commit 中包含 `.env`、`config.yaml` (含密钥)、`.venv/`

---

## 9. Phase 3 实施计划 (6 Sprints)

### Sprint 1: SubGraph 骨架 + State 定义 (Week 1)

**目标**: Parent Graph 挂载两个 SubGraph 可编译通过

| 文件 | 说明 |
|------|------|
| `collaboration/state.py` | 三层 State (Parent + Research + Analysis) |
| `collaboration/subgraphs/research_subgraph.py` | Research SubGraph 骨架 |
| `collaboration/subgraphs/analysis_subgraph.py` | Analysis SubGraph 骨架 |
| `collaboration/subgraphs/state_mapping.py` | 4 个 State Mapping 纯函数 |
| `collaboration/graph.py` | Parent Graph 组装 + SubGraph 挂载 |
| `collaboration/router.py` | 条件路由 (含 error 字段上浮路由) |
| `tests/test_collaboration_graph.py` | Parent Graph 可编译验证 |
| `tests/test_collaboration_subgraphs.py` | SubGraph 独立编译 + State Mapping 正确性 |

**DoD**: Parent Graph 挂载两个 Mock SubGraph 可编译；State Mapping 纯函数单元测试通过

### Sprint 2: Research SubGraph 节点 (Week 2)

**目标**: Research SubGraph 内部 6 节点可走通完整流程

| 文件 | 说明 |
|------|------|
| `collaboration/nodes/pi_agent.py` | PI Agent |
| `collaboration/nodes/data_scout.py` | Data Scout |
| `collaboration/nodes/critic_agent.py` | Critic Agent (Challenge JSON) |
| `collaboration/nodes/meta_judge.py` | Meta-Judge (Ruling JSON) |
| `collaboration/prompts/{pi_agent,data_scout,critic_agent,meta_judge}.py` | 4 个提示词 |
| `collaboration/protocols/messages.py` | Challenge/Rebuttal/Ruling 模型 |
| `collaboration/protocols/debate.py` | 对抗式批判状态机 |
| `tests/test_collaboration_nodes.py` | PI/Scout/Critic/Judge 单元测试 |

**DoD**: Critic 正确生成结构化 Challenge；Meta-Judge 正确生成裁决书；PI 审核流程走通

### Sprint 3: Analysis SubGraph + Report (Week 3)

**目标**: Analysis SubGraph + Report Composer 可独立运行

| 文件 | 说明 |
|------|------|
| `collaboration/nodes/analyst_lead.py` | Analyst Lead |
| `collaboration/nodes/synthesizer.py` | Synthesizer |
| `collaboration/nodes/internal_reviewer.py` | Internal Reviewer |
| `collaboration/nodes/report_composer.py` | Report Composer |
| `collaboration/prompts/{analyst_lead,synthesizer,internal_reviewer,report_composer}.py` | 4 个提示词 |
| `tests/test_collaboration_nodes.py` | Analysis 节点测试 (追加) |

**DoD**: Synthesizer 正确生成对比矩阵+SWOT+趋势；Internal Reviewer 正确审查

### Sprint 4: 角色门控 + HITL + 流式 (Week 4)

**目标**: 权限硬编码生效，HITL 全链路可用

| 文件 | 说明 |
|------|------|
| `collaboration/permissions/role_definition.py` | ROLE_PERMISSIONS |
| `collaboration/permissions/permission_guard.py` | PermissionGuardMiddleware |
| `collaboration/nodes/hitl_gate.py` | HITL Gate |
| `collaboration/nodes/error_handler.py` | 全局错误处理 |
| `collaboration/events.py` | 流式事件 |
| `collaboration/middleware.py` | 上下文注入 + agent_role 标记 |
| `app/gateway/routers/collaboration.py` | HITL 恢复 API |
| `tests/test_collaboration_permissions.py` | 门控测试 |
| `tests/test_collaboration_hitl.py` | HITL 全场景 |
| `tests/test_collaboration_critic_judge.py` | Critic+Judge 集成 |

**DoD**: 角色门控正确拒绝越权；HITL 暂停/恢复/幂等/过期通过

### Sprint 5: 配置 + 集成 (Week 5) — ✅ 完成

**目标**: 配置热加载生效，Lead Agent 可路由到协作图

| 文件 | 说明 | 状态 |
|------|------|------|
| `config/collaboration_config.py` | Pydantic 配置模型 (含 Roles/HITL/Workflows) | ✅ |
| `config.yaml` | 协作段配置（10 角色 + Skills + Memory + HITL + 4 Workflows） | ✅ |
| `agents/lead_agent/agent.py` | 路由：collaboration 请求 → 协作图 | ✅ |
| `agents/middlewares/collaboration_middleware.py` | PermissionGuard 注册 | ✅ |

**DoD**: config.yaml 热加载生效；collaboration.enabled: true 后协作图正常启动 ✅

### Sprint 6: E2E + 文档 (Week 6) — ✅ 完成

**目标**: 3 个完整场景端到端通过

| 文件 | 说明 | 状态 |
|------|------|------|
| `tests/test_collaboration_e2e.py` | 端到端 (竞品拆解/趋势洞察/定价优化) | ✅ 11 tests |
| `collaboration/nodes/research_nodes.py` | _extract_json 增强 (数组解析) | ✅ |
| `collaboration/nodes/analysis_nodes.py` | _extract_json 增强 (数组解析) | ✅ |
| `collaboration/nodes/hitl_gate.py` | 幂等性修复 (modify/replan 循环后重新审批) | ✅ |
| `collaboration/subgraphs/research_subgraph.py` | route_after_critic 修复 (pending challenges 检查) | ✅ |
| `collaboration/graph.py` | error_handler_node 实际实现 | ✅ |

**DoD**:
- [x] 3 个 E2E 场景全部通过 (竞品拆解/趋势洞察/定价优化)
- [x] 180 个协作测试通过，harness boundary 通过
- [x] CLAUDE.md + PA-Agent-DF-architecture.md 更新至最终状态

---

## 9.7 Phase 4 计划: 生产就绪 (待实施)

> Phase 3（6 个 Sprint）完成了图结构、节点逻辑、权限门控、HITL Gate、
> 配置热加载、E2E 测试（180 个），全部用 mock SubagentExecutor。
> 以下缺口阻止系统在真实 DF 环境中运行。

### P0: Lead Agent 路由到协作图

**现状**: `agent.py` 注册了 `CollaborationMiddleware`，但 Lead Agent 仍是标准 ReAct。
**需要**: 在 `langgraph.json` 中注册协作图，或在 `make_lead_agent()` 中根据 `collaboration.enabled` 切换图。

| 文件 | 说明 |
|------|------|
| `langgraph.json` | 注册协作图为独立 graph |
| `agents/lead_agent/agent.py` | `collaboration.enabled` 时路由到 `build_collaboration_graph()` |

### P1: Checkpointer 集成

**现状**: `build_collaboration_graph()` 编译时未传 `checkpointer`。HITL 的 `interrupt()` 无持久化无法真正暂停/恢复。
**需要**: `SqliteSaver`（开发）或 `PostgresSaver`（生产）。

| 文件 | 说明 |
|------|------|
| `collaboration/graph.py` | `builder.compile(checkpointer=...)` |
| `config.yaml` | `collaboration.checkpointer` 配置段 |

### P1: Send API 并行 Fan-out

**现状**: `research_subgraph.py` import 了 `Send` 但未使用，Scout 采集是顺序流。
**需要**: PI 规划后 `Send(node, arg)` 并行启动 2-4 个 Scout，reducer 汇总结果。

| 文件 | 说明 |
|------|------|
| `collaboration/subgraphs/research_subgraph.py` | 实现 `fan_out_to_scouts()` |
| `collaboration/nodes/research_nodes.py` | PI 节点输出 task_plan 供 Send API 消费 |

### P2: 真实 LLM 集成验证

**现状**: 180 个测试全用 mock SubagentExecutor，prompt 模板未经真实 LLM 验证。
**需要**: 至少 1 个集成测试用真实 LLM 跑通最小流程。

| 文件 | 说明 |
|------|------|
| `tests/test_collaboration_live.py` | 真实 LLM 集成测试（需 API key，手动运行） |

### P2: Skills SKILL.md 创建

**现状**: 8 个 Skill 名在 `SubagentConfig.skills` 中引用，但 `skills/public/` 下无 `SKILL.md`。
**需要**: 每个 Skill 创建 `SKILL.md`（YAML frontmatter + 指令）。

| Skill | 文件 |
|------|------|
| `data-normalizer` | `skills/public/data-normalizer/SKILL.md` |
| `sentiment-analyzer` | `skills/public/sentiment-analyzer/SKILL.md` |
| `source-credibility` | `skills/public/source-credibility/SKILL.md` |
| `spec-comparator` | `skills/public/spec-comparator/SKILL.md` |
| `price-elasticity` | `skills/public/price-elasticity/SKILL.md` |
| `market-share-calc` | `skills/public/market-share-calc/SKILL.md` |
| `trend-detector` | `skills/public/trend-detector/SKILL.md` |
| `swot-generator` | `skills/public/swot-generator/SKILL.md` |

### P3: 协作 Memory 落地

**现状**: `collaboration_config.py` 有 `SourceCredibilityConfig`/`ProductKnowledgeConfig`，未实际调用 DF Memory API。
**需要**: Critic/Judge 验证后触发 Memory 更新。

| 文件 | 说明 |
|------|------|
| `collaboration/memory/source_credibility.py` | 基于验证结果更新数据源评分 |
| `collaboration/memory/product_knowledge.py` | 已验证数据点持久化 |

### P3: router.py 独立

**现状**: 路由逻辑分散在 `graph.py` (`route_after_research/analysis/hitl`) 和 subgraph 文件中。
**如果需要**: 可抽取为独立 `collaboration/router.py` 集中管理。

---

## 10. 业务场景与测试用例

### 10.1 场景 1: 竞品深度拆解 (Primary)

```
输入: "帮我做一份 iPhone 17 与华为 Mate 70 Pro、三星 S25 Ultra 的深度对比分析"
可选上传: iPhone_17_specs.xlsx, market_report_2026Q1.pdf (DF 自动转换为 Markdown)
预期流程: planning → collecting(3 scouts, 含 pandas 数据清洗 + firecrawl 抓取) → validating(Critic scipy 检验 + Judge 裁决) → synthesizing(Skills) → hitl → composing
预期输出: Markdown 报告 + 规格对比雷达图 + 价格趋势折线图 + SWOT 矩阵图
预期耗时: 15-25 分钟 | 预期 Token: 30-80 万
DF 特性: Sandbox计算, Skills×4, FileUpload+转换, firecrawl, Memory更新
```

### 10.2 场景 2: 市场趋势洞察

```
输入: "分析 2026 年 Q1 中国新能源汽车市场的竞争格局和趋势"
预期流程: planning → collecting(2 scouts) → synthesizing → hitl → composing (跳过硬体验证)
预期输出: Markdown 报告 + 市场份额饼图 + 趋势折线图
预期耗时: 10-15 分钟
```

### 10.3 场景 3: 商品定价优化

```
输入: "我们的新产品智能手表定价 2999 元，请分析竞品定价并给出优化建议"
预期流程: planning → collecting(2 scouts) → validating → synthesizing → hitl → composing
预期输出: Markdown 报告 + 价格对比矩阵 + 价格弹性分析
预期耗时: 12-18 分钟
```

---

## 11. DeerFlow 对接清单 (编码时逐项检查)

开发每个节点时，必须确认：

- [ ] 使用 `ensure_sandbox_initialized(runtime)` 而非直接操作文件系统
- [ ] 使用 `SubagentExecutor(config, tools, ...)` 而非直接调用 LangChain/LangGraph Agent
- [ ] 工具白名单通过 `SubagentConfig.tools` 控制
- [ ] 角色权限通过 `PermissionGuardMiddleware` 检查 (编码时必须在节点入口注入 agent_role)
- [ ] 文件操作走虚拟路径 (`/mnt/user-data/workspace/...`)
- [ ] SubGraph 节点返回 `dict` 更新各自的 SubGraphState，不直接修改 ParentState
- [ ] State Mapping 是纯函数，不产生副作用
- [ ] 子图异常通过 `error` 字段上浮，不抛异常到父图
- [ ] 不在 Harness 层 import `app.*` 任何模块
- [ ] **DF 基座最大化利用 (逐项核验)**:
  - [ ] 沙箱 Python 计算是否配置 (pandas/scipy/sklearn 在对应角色)
  - [ ] Skills 是否加载 (SubagentConfig.skills 白名单)
  - [ ] Memory 是否触发 (来源可信度 + 产品知识库双轨)
  - [ ] 文件上传转换是否提供入口 (UploadsMiddleware 感知)
  - [ ] Community Tools 是否全量启用 (firecrawl, image_search, jina_ai)
  - [ ] MCP 服务是否接入 (电商 API / 金融数据 / 社交媒体)

---

## 12. 关键参考

### 学术/行业
- [ClawdLab: Adversarial Critique + Role-Gated Governance (arXiv 2026.02)](https://arxiv.org/abs/2602.19810) — PI/Critic/Judge 四权分立架构
- [HieraMAS: Hierarchical Mixture-of-Agents (arXiv 2026.02)](https://arxiv.org/abs/2602.20229v1) — 超节点 propose-synthesis 结构
- [Bioptic Agent: Wide Search (arXiv 2026.02)](https://arxiv.org/html/2602.15019v4) — F1=79.7%，完整性搜索验证
- [AgenticPay: Multi-Agent Negotiation (arXiv 2026.02)](https://arxiv.org/html/2602.06008v1) — Claude Opus 4.5 最优
- [OrgAgent: Company-Style Hierarchy (2026)](https://www.semanticscholar.org/paper/OrgAgent%3A-Organize-Your-Multi-Agent-System-like-a-Wang-Shen/ff1dbcfc02dc6b3c2048161753be00edf1668aea) — 公司式层级优于其他结构
- [Qualtrics: Agentic AI Market Research (May 2026)](https://www.qualtrics.com/articles/strategy-research/agentic-ai-market-research/)
- [Klue: AI in Competitive Intelligence 2026](https://klue.com/topics/how-ai-helps-with-competitive-intelligence)

### GitHub 对标项目
- [competitor-hunter](https://github.com/Duang777/competitor-hunter) — LangGraph + MCP + Playwright
- [Product-Research-Multi-Agent-System](https://github.com/To11-o11/Product-Research-Multi-Agent-System) — 中文 4 Agent 调研
- [Multi-Agent-BDS](https://github.com/aparaajita19/Multi-Agent-BDS) — 4 Agent 电商情报
- [e-commerce-agents](https://github.com/nitin27may/e-commerce-agents) — 6 Agent + A2A + PostgreSQL/pgvector

### LangGraph 2.0
- [LangGraph 2.0 Production Guide (2026)](https://dev.to/richard_dillon_b9c238186e/langgraph-20-the-definitive-guide-to-building-production-grade-ai-agents-in-2026-4j2b)
- [Supervisor Pattern](https://deepwiki.com/langchain-ai/langgraphjs/4.1-supervisor-pattern)
- [Swarm Pattern](https://deepwiki.com/langchain-ai/langgraphjs/4.2-swarm-pattern)
- [Hierarchical Teams](https://deepwiki.com/langchain-ai/langgraphjs/4.3-hierarchical-agent-teams)

### HITL 生产实践
- [HITL or HOTL? Three-Tier Framework (April 2026)](https://dev.to/waxell/human-in-the-loop-or-human-on-the-loop-most-teams-are-using-the-wrong-model-588p)
- [Production HITL Patterns (Feb 2026)](https://focused.io/lab/your-ai-just-emailed-a-customer-without-permission)
- [Building HITL Approval Gates (2026)](https://machinelearningmastery.com/building-a-human-in-the-loop-approval-gate-for-autonomous-agents/)

### 框架对比
- [LangGraph vs CrewAI in 2026 — Redwerk](https://redwerk.com/blog/langgraph-vs-crewai/)
- [LangGraph vs CrewAI vs AutoGen: 2026 Comparison](https://www.marsdevs.com/compare/langgraph-vs-crewai-vs-autogen)

---

> **Phase 2 完成。进入 Phase 3 编码实施，按 Sprint 1→2→3→4 顺序推进，严格遵守 DeerFlow-First 铁律。**
