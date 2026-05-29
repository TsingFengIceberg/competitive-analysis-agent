# 01 — 三层 State 体系与 State Mapping

> **日期**: 2026-05-14 | **Sprint**: 1 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/state.py`](../backend/packages/harness/deerflow/collaboration/state.py) | 三层 State 定义 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/state_mapping.py) | 4 个 State Mapping 纯函数 |
| [`backend/packages/harness/deerflow/agents/thread_state.py`](../backend/packages/harness/deerflow/agents/thread_state.py) | DeerFlow 原生 ThreadState（对比参考） |

---

## Q1: 这三个 State 继承自哪里？ `📄 state.py`

**A:** 都继承自 `langchain.agents.AgentState`。

```python
from langchain.agents import AgentState

class CollaborationState(AgentState):      # 继承
class ResearchSubGraphState(AgentState):   # 继承
class AnalysisSubGraphState(AgentState):   # 继承
```

`AgentState` 是 LangChain 提供的基类，内部定义了 `messages: list[Any]` 字段。

**为什么必须继承它？** LangGraph 的 `StateGraph(StateSchema)` 要求 State Schema 包含 `messages` 字段。Agent 的所有对话交互——模型输出 AIMessage、工具返回 ToolMessage、人类输入 HumanMessage——都通过 `messages` 通道流转。没有它，LangGraph 无法将 LLM 响应正确地推入状态。

DeerFlow 原生的 `ThreadState` 也继承自 `AgentState`：

```python
# thread_state.py
class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    ...
```

**关键认知**：LangGraph 中任何"能够与 LLM 交互的图"都必须有一个包含 `messages` 的状态。AgentState 就是这个约定的标准化载体。

---

## Q2: 三个 State 后续在哪里使用？ `📄 state.py` `📄 graph.py`

**A:** 每个 State 绑定一个独立的图（Graph），通过 `StateGraph(StateSchema)` 编译：

```
CollaborationState  ──→ build_collaboration_graph()  [Parent Graph]
ResearchSubGraphState ──→ build_research_subgraph()   [Research SubGraph]
AnalysisSubGraphState ──→ build_analysis_subgraph()   [Analysis SubGraph]
```

具体绑定代码：

```python
# graph.py
builder = StateGraph(CollaborationState)       # Parent 使用自己的 Schema

# research_subgraph.py
builder = StateGraph(ResearchSubGraphState)    # Research 使用自己的 Schema

# analysis_subgraph.py
builder = StateGraph(AnalysisSubGraphState)    # Analysis 使用自己的 Schema
```

SubGraph 的挂载方式是通过 `add_node(name, compiled_subgraph, state_in=fn, state_out=fn)`：

```python
# graph.py — Parent 挂载 Research SubGraph
builder.add_node(
    "research_subgraph",
    build_research_subgraph(),           # 编译好的子图
    state_in=map_parent_to_research,     # Parent → Research 输入投影
    state_out=map_research_to_parent,    # Research → Parent 输出投影
)
```

**执行顺序**：`build_collaboration_graph()` 内部调用 `build_research_subgraph()` 和 `build_analysis_subgraph()`，三个 State Schema 各自独立编译，互不污染。

---

## Q3: 为什么"父子 State 严格隔离"？ `📄 state.py` `📄 state_mapping.py`

**A:** 设计文档中的这句话：

> 父子 State 严格隔离：SubGraph 不直接读取 ParentState，通过 state_in 投影传入

三个原因：

**1. 编译隔离** — LangGraph 要求每个 `StateGraph` 编译时有自己的 State Schema。子图编译时只知道自己的 State 字段（如 `challenges`、`debate_round`），不知道父图的 `review_decision`、`collaboration_error`。如果子图能直接访问父图字段，子图 Schema 就必须包含父图所有字段 → 编译绑死，无法复用。

**2. 并行安全** — 如果多个 SubGraph 节点同时运行（如 Send API 并行分发的多个 Scout），它们共享同一个 Parent State 的 `messages` 列表，各自的工具调用会互相覆盖。独立 State 保证每个子图有自己的 `messages` 列表。

**3. 可测试性** — 子图独立 State，单元测试只需构造子图自己的 State：

```python
# ✅ 独立 State：测试 Research 只需构造 ResearchSubGraphState
state: ResearchSubGraphState = {"messages": [], "challenges": [...]}
graph.invoke(state)

# ❌ 共享 State：测试 Research 还需要知道 Parent 的完整字段
state: CollaborationState = {"messages": [], "review_decision": None, ...}
```

**类比**：`state_in` 相当于函数参数列表——子图明确声明"我需要这些字段"，父图负责传入。这是一种控制反转：不是子图去找父图拿数据，而是父图主动把数据传给子图。

---

## Q4: `NotRequired` 是什么？ `📄 state.py`

**A:** `NotRequired` 是 Python 3.12+ `typing` 模块中 `TypedDict` 的修饰符，标记某个 key 为"可选"。

```python
from typing import NotRequired, TypedDict

class Example(TypedDict):
    required_field: str           # 必须提供
    optional_field: NotRequired[str | None]  # 可以不提供
```

**在这里的用途**：标记"流程中间才产生"的字段。

- 图刚启动时，`validated_brief`、`synthesis_report` 等还不存在
- 只有 `messages` 是一定存在的（来自 `AgentState`）
- `NotRequired` 让初始 State 通过类型检查

对比例子：

```python
# ✅ 使用 NotRequired — 启动 State 只需 messages
class State(TypedDict):
    validated_brief: NotRequired[dict | None]
    messages: list

state: State = {"messages": []}  # OK

# ❌ 无 NotRequired — 类型检查报错
class State(TypedDict):
    validated_brief: dict | None  # 非 NotRequired，初始化时必须提供！
    messages: list

state: State = {"messages": []}  # mypy/pyright 报错：缺少 'validated_brief'
```

**与 `NotRequired[dict | None]` 中 `| None` 的关系**：`NotRequired` 控制的是 key 是否存在，`| None` 控制的是 key 存在时值可以是 None。两者正交：

```python
state1: State = {"messages": []}                         # key 不存在（NotRequired）
state2: State = {"messages": [], "validated_brief": None}  # key 存在但值为 None
```

---

## Q5: `class CollaborationState(AgentState)` 是什么意思？ `📄 state.py` `📄 thread_state.py`

**A:** 是的，`CollaborationState` 继承自 `AgentState`。这条语法等价于：

```python
# 这条语句：
class CollaborationState(AgentState):
    validated_brief: NotRequired[dict | None]
    ...

# 等价于同时拥有以下字段的 TypedDict：
# messages           ← 来自 AgentState
# validated_brief    ← CollaborationState 新增
# ...
```

TypedDict 支持继承——子类自动合并父类的所有字段定义。

**四个 State 的对比：**

```
AgentState (LangChain)
├── messages: list[Any]                          ← 唯一公共字段
│
├── ThreadState (DeerFlow 原生)
│   └── + sandbox, thread_data, title, artifacts, todos, ...
│   └── 用途: Lead Agent 的单 Agent ReAct 循环
│
├── CollaborationState (Parent Graph — 我们新增)
│   └── + validated_brief, research_quality_score, unresolved_issues,
│        synthesis_report, review_decision, collaboration_error, ...
│   └── 用途: 8 角色协作流全生命周期管理
│
├── ResearchSubGraphState (Research SubGraph — 我们新增)
│   └── + research_plan, scout_results, challenges, rebuttals,
│        debate_round, ruling, pi_override_log, validated_brief, error
│   └── 用途: PI → Scouts → Critic ⇄ Scouts → Judge → PI Review
│
└── AnalysisSubGraphState (Analysis SubGraph — 我们新增)
    └── + analysis_plan, analysis_results, synthesis_report,
         internal_review_passed, review_feedback, error, ...
    └── 用途: Analyst Lead → Synthesizer → Internal Reviewer
```

**关键设计区别**：

| | ThreadState | CollaborationState | ResearchSubGraphState | AnalysisSubGraphState |
|---|---|---|---|---|
| 作用域 | 单 Agent 对话 | 多 Agent 协作全局 | Research 阶段内部 | Analysis 阶段内部 |
| 并发执行分支数 | 1（串行 ReAct） | 1（Parent 层串行） | N（Send API Fan-out ×2-4 Scout + Critic） | 1（顺序流水线） |
| 复用性 | Lead Agent 专用 | 协作流专用 | 可被其他图复用 | 可替换为其他分析图 |
| 字段可见性 | 对外暴露 | 跨子图共享 | SubGraph 内部 | SubGraph 内部 |

> **关于"并发执行分支数"**：这里不是 OS 线程。LangGraph 图执行是单线程的（一个 event loop），但通过 `Send()` API 可以在逻辑上同时分发多个节点到不同的执行分支。每个分支有自己独立的 `messages` 状态通道，不会互相覆盖。这类似于 Go 的 goroutine——不是真正的 OS 线程，而是并发的逻辑执行单元。ResearchSubGraphState 的 N 是因为 PI 通过 `Send()` 同时启动 2-4 个 Scout 节点 + Critic，这些节点的状态更新会通过 `Annotated[list, add]` reducer 合并回主状态。

---

## Q6: 三个 State 的关联？ `📄 state.py` `📄 state_mapping.py`

**A:** 数据单向流动——Research → Parent → Analysis，子图之间不直接通信。

```
CollaborationState (Parent)
    │
    ├── validated_brief    ← Research 写入 → Analysis 读取
    ├── synthesis_report   ← Analysis 写入 → HITL/Composer 读取
    ├── collaboration_error ← 任一子图异常上浮 → Parent 降级路由
    │
    ├─[挂载]── ResearchSubGraphState (namespace: "research")
    │           state_in:  map_parent_to_research()
    │           state_out: map_research_to_parent()
    │
    └─[挂载]── AnalysisSubGraphState (namespace: "analysis")
                state_in:  map_parent_to_analysis()
                state_out: map_analysis_to_parent()
```

**桥接字段**（三个 State 都有的字段，负责跨边界传递）：

| 字段 | 方向 | 含义 |
|------|------|------|
| `validated_brief` | Research → Parent → Analysis | 精炼后的研究简报 |
| `research_quality_score` | Research → Parent → Analysis | 研究质量评分 |
| `unresolved_issues` | Research → Parent → Analysis | 遗留未解决问题 |
| `error` → `collaboration_error` | SubGraph → Parent | 异常上浮（字段名不同） |

**Research 和 Analysis 为什么不能直接通信？**

如果允许直接通信，就会发生：

```
Research.output → Analysis.input   （直接读写）
```

这会：
1. 打破编译隔离——Analysis 编译时依赖 Research 的输出 schema
2. 无法替换——如果要把 Research SubGraph 换成更快的轻量版本，Analysis 也得改
3. 测试耦合——测试 Analysis 必须启动完整的 Research

通过 Parent 中转后：

```
Research → Parent.validated_brief → Analysis
```

Analysis 只依赖 Parent 的 `validated_brief` 字段，不关心它来自哪个 SubGraph。这是经典的**依赖倒置**在状态管理中的应用。

---

## Q7: SubGraph 内部字段对外封闭有什么好处？ `📄 state.py` `📄 state_mapping.py`

**A:** ResearchSubGraphState 的 `challenges`、`rebuttals`、`debate_round`，AnalysisSubGraphState 的 `analysis_plan`、`analysis_results`——这些字段只有 SubGraph 自己能读写，Parent 和其他 SubGraph 根本看不到。三个好处：

**1. 可替换（最重要的收益）**

Parent 只认得 `validated_brief`，不关心是哪个 SubGraph 产出的。将来可以把 Research SubGraph 换成轻量版、人工驱动版、甚至远程服务版，只要产出的 `validated_brief` 结构不变，Analysis 和 Parent 一行不改。

```
现在:  ResearchSubGraph → validated_brief → AnalysisSubGraph
将来:  FastResearchSubGraph → validated_brief → AnalysisSubGraph   ✅ 直接替换
       ManualResearchSubGraph → validated_brief → AnalysisSubGraph  ✅ 一样可用
```

**2. 可独立测试**

测试 Research 只需要构造 `ResearchSubGraphState`（6 个相关字段），不需要知道 Parent 的 `review_decision`、`synthesis_report` 这些无关字段。测试 Parent 同理，不需要关心 Research 内部怎么运作。

```python
# ✅ 隔离后：独立测试，State 只需 2 个字段
state: ResearchSubGraphState = {"messages": [], "research_plan": {...}}
graph.invoke(state)

# ❌ 不隔离：耦合测试，State 需要填满无关字段
state: CollaborationState = {
    "messages": [],
    "validated_brief": None,    # Research 不需要但必须提供
    "synthesis_report": None,   # Research 不需要但必须提供
    "review_decision": None,    # Research 不需要但必须提供
    ...
}
```

**3. 防止隐式耦合**

如果 Analysis 节点能读到 `debate_round`（Research 的质问轮次），某天有个开发者可能写：

```python
# ❌ 隐式耦合——Analysis 悄悄依赖 Research 内部实现
if debate_round == 0:
    skip_deep_analysis()  # "只质问了一轮，数据不可靠，跳过深分析"
```

这段代码会让 Analysis 依赖 Research 的内部实现细节。之后改 Research 的轮次逻辑，Analysis 静默崩溃——连编译器都帮不了你，因为 TypedDict 只管字段类型不管业务逻辑。

隔离直接切断了这种可能性——Analysis 根本不知道 `debate_round` 存在。

**本质**：这是软件工程里**封装**原则在 Agent 状态管理上的体现。对外只暴露契约字段（`validated_brief`、`synthesis_report`），内部实现随意演化。与 REST API 不同——你只通过 JSON 契约通信，不关心对方内部数据库 schema。

---

## Q8: `research_quality_score` 和 `validated_brief` 由谁产出？ `📄 state.py`

**A:** 两个字段都来自 Research SubGraph 内部，但由不同角色在不同阶段产出。

**`research_quality_score` — Meta-Judge 给出**

裁决阶段，Meta-Judge 不看身份只看证据，基于计算工具输出（如 `scipy.stats` 统计检验 p-value、数据覆盖率、来源交叉验证结果）给研究质量打 0.0-1.0 的分数。这是**客观计算分**，不是主观意见——来自计算验证而非 LLM 的"我觉得数据还行"。

**`validated_brief` — PI 审核后打包产出**

它是整个 Research SubGraph 的最终输出物，一个结构化 dict，承载经过对抗式批判验证的精炼数据：

```python
{
    "topic": "iPhone 17 vs 华为 Mate 70 Pro 对比",
    "verified_data_points": [
        {"data": "iPhone 17 起售价 6999", "source": "apple.com", "confidence": 0.95},
        {"data": "华为 Mate 70 Pro 出货量 1200 万", "source": "IDC 2026Q1", "confidence": 0.80},
    ],
    "rejected_claims": [
        {"claim": "三星 S25 销量第一", "reason": "Critic 发现数据源冲突，Judge 裁决排除"},
    ],
    "quality_score": 0.85,
    "unresolved": ["折叠屏市场份额数据无法交叉验证"]
}
```

**两者的时序关系**：

```
Research SubGraph 内部流程:
  Scouts 采集 → Critic 质疑 ⇄ Scouts 补采 (最多2轮)
      ↓
  Meta-Judge → ruling { verdict, quality_score, resolved, unresolved }
      ↓
  PI Review → 审核裁决书
      ├── 批准: 把 quality_score + 验证数据 + 遗留问题 打包成 validated_brief
      └── 推翻: 记录 pi_override_log，重新裁决
      ↓
  validated_brief (含 quality_score) → State Mapping → Parent → Analysis
```

**为什么是 Analysis 的契约接口**：Analysis 只看 `validated_brief` 和 `quality_score`，不看 Research 内部的 `challenges`、`rebuttals`、`debate_round`。这两个字段构成了 Research 和 Analysis 之间的**唯一数据契约**——Research 怎么采集、怎么质疑、怎么裁决，Analysis 完全不关心，只认最终产出。

---

## 扩展阅读：DeerFlow ThreadState 的设计思路

DF 的 `ThreadState` 扩展 `AgentState` 但没有拆成多个 SubGraph State——因为 Lead Agent 是单 Agent 模式，所有字段都在一个作用域。

我们的 `CollaborationState` 拆成三层是因为 Nested SubGraph 架构需要隔离：
- **Parent State** 管理跨阶段全局状态（审批决定、异常信息）
- **SubGraph State** 管理阶段内部状态（采集结果、质疑列表、分析中间数据）

这种拆分体现了**关注点分离**——每个 State 只关注自己阶段的数据，子图内部细节不污染父图。

---

> **下一主题**: [02 — SubGraph 构建与编译隔离](02-subgraph-design.md) *(待编码)*
