# 02 — SubGraph 构建与编译隔离

> **日期**: 2026-05-14 | **Sprint**: 1 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py) | Research SubGraph 骨架（Sprint 2 填装逻辑） |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/analysis_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/analysis_subgraph.py) | Analysis SubGraph 骨架（Sprint 3 填装逻辑） |
| [`backend/packages/harness/deerflow/collaboration/state.py`](../backend/packages/harness/deerflow/collaboration/state.py) | SubGraph State Schema 定义 |

---

## Q1: `raise NotImplementedError` 是什么？ `📄 research_subgraph.py`

**A:** Sprint 1 的节点只是骨架占位，不执行任何逻辑。

```python
def pi_agent_node(state: ResearchSubGraphState) -> dict:
    """PI Agent — 规划研究任务 + Send API Fan-out 分发到 Scouts。"""
    raise NotImplementedError("pi_agent_node — Sprint 2 实现")
```

**为什么用 `raise` 而不是 `pass`？** 如果图不小心被 `invoke()` 走到了这些占位节点，`pass` 会静默返回 `None`（LangGraph 可能把它当成合法的状态更新），导致状态错乱且极难排查。`raise` 立即崩溃报错——**尽早暴露未完成部分**。

到 Sprint 2/3 实现节点真实逻辑时，`raise` 会被替换成 SubagentExecutor 调用、LLM 推理等。

---

## Q2: 为什么提前声明节点（骨架）？ `📄 research_subgraph.py`

**A:** 自顶向下的设计方法——先把结构和接口定好，编译验证通过，再填内部实现。

```
Sprint 1（现在）:          Sprint 2/3（将来）:
┌──────────────────┐       ┌──────────────────────┐
│ 节点签名 + 路由    │  →   │ 节点内部 SubagentExecutor │
│ 图结构 + 编译通过  │       │ 真实 LLM 推理 + 工具调用  │
│ State 定义正确     │       │ 对抗式批判协议实现       │
└──────────────────┘       └──────────────────────┘
   接口验证在前               逻辑实现在后
```

类似于先写 interface 再写实现类。好处是：
1. **Sprint 1 就有可编译的图**——能看到节点连接是否正确，路由是否可达
2. **接口即文档**——`pi_agent_node(state) -> dict` 这条签名比任何文字都精确地描述了"PI 做什么"
3. **并行开发**——Sprint 2 可以实现 PI 和 Data Scout 同时进行，因为接口已定

---

## Q3: `StateGraph` 是什么？ `📄 research_subgraph.py`

**A:** `StateGraph` 是 LangGraph 的核心工厂函数，来自 `langgraph.graph`。

```python
from langgraph.graph import StateGraph
from deerflow.collaboration.state import ResearchSubGraphState

builder = StateGraph(ResearchSubGraphState)   # ① 创建 Builder，绑定 State Schema
builder.add_node("pi_agent", pi_agent_node)   # ② 注册节点
builder.add_edge("pi_agent", "critic_agent")  # ③ 连接边
builder.set_entry_point("pi_agent")            # ④ 设置入口
graph = builder.compile()                      # ⑤ 编译成可执行图
```

**每一步做了什么：**

| 步骤 | API | 作用 |
|------|-----|------|
| ① | `StateGraph(Schema)` | 创建 Builder，LangGraph 为 Schema 的每个字段创建 channel（状态通道） |
| ② | `add_node(name, fn)` | 注册节点：名字是图的顶点，fn 是到达该顶点时执行的函数 |
| ③ | `add_edge(a, b)` | 固定边：a 执行完后无条件跳到 b |
| ④ | `set_entry_point(name)` | 图的起点：`invoke()` 时从哪个节点开始 |
| ⑤ | `compile()` | 编译：验证所有节点签名、边连接完整性、生成执行计划 |

**`StateGraph(Schema)` 的参数就是 State 类型**——它告诉 LangGraph："这个图的所有节点都读写这个类型的状态"。编译时 LangGraph 会：
- 为 Schema 的每个字段创建 channel
- 验证所有节点的返回 dict 的 key 都在 Schema 内
- 处理 `Annotated[list, add]` reducer（多分支并发时的合并策略）

**`builder.compile()` 的产物**是 `CompiledStateGraph`——这个对象可以直接传给 `add_node(name, compiled_graph, state_in=fn, state_out=fn)` 挂载到父图。

---

## Q4: Research 子图的输入/输出在哪体现？ `📄 research_subgraph.py` `📄 state_mapping.py`

**A:** 分两个层面。

**图内层面** — 节点函数签名决定每个节点读写什么：

```python
def pi_agent_node(state: ResearchSubGraphState) -> dict:
    #      ↑ 输入: LangGraph 自动传入当前图状态       ↑ 输出: 要更新的字段 dict
```

- `state` — LangGraph 在调用节点时自动从 channel 组装出当前 `ResearchSubGraphState` 并传入
- `-> dict` — 返回的 dict 包含要更新的字段，LangGraph 自动 merge 回状态的对应 channel

**挂载层面** — `state_in` / `state_out` 控制子图与外部的数据交换（在 `graph.py` 中配置）：

```python
# graph.py
builder.add_node(
    "research_subgraph",
    build_research_subgraph(),          # ← 编译好的子图
    state_in=map_parent_to_research,    # ← 入口投影: Parent → Research
    state_out=map_research_to_parent,   # ← 出口投影: Research → Parent
)
```

```
调用子图时:
  Parent.validated_brief ──[state_in]──→ ResearchSubGraphState  ← 节点看到的 state
  Parent.workflow_type   ──[state_in]──→ ResearchSubGraphState

子图结束时:
  ResearchSubGraphState ──[state_out]──→ Parent.validated_brief
  ResearchSubGraphState ──[state_out]──→ Parent.collaboration_error
```

**关键**：子图内部完全不知道 Parent 的存在。它只认自己的 `ResearchSubGraphState`。数据进出由 `state_in`/`state_out` 两个纯函数代理。这就是 Q3 中"父子隔离"的具体实现。

---

## Q5: `add_conditional_edges` 和 `add_edge` 的区别？ `📄 research_subgraph.py`

**A:** 两种边的语义：

| | `add_edge` | `add_conditional_edges` |
|---|---|---|
| 路由方式 | 固定：A 完成 → 无条件跳到 B | 动态：A 完成 → 执行 router 函数 → 跳到对应节点 |
| 典型场景 | `pi_agent → critic_agent`（顺序） | `critic → scout 或 judge`（根据质疑结果决定） |
| 返回值 | 无 | router 函数返回字符串，匹配 path_map |

```python
# 固定边: Scout 补采完一定回到 Critic 重新审查
builder.add_edge("data_scout", "critic_agent")

# 条件边: Critic 审查后根据结果决定下一步
builder.add_conditional_edges("critic_agent", route_after_critic, {
    "data_scout": "data_scout",    # 还有质疑 → 补采
    "meta_judge": "meta_judge",    # 质疑解决 → 裁决
})

def route_after_critic(state) -> Literal["data_scout", "meta_judge"]:
    if state.get("challenges") and state.get("debate_round", 0) < 2:
        return "data_scout"   # 有质疑且未满2轮 → 继续补采
    return "meta_judge"        # 否则 → 进入裁决
```

`path_map` 的 key 是 router 函数的返回值，value 是目标节点名。`"__end__"` 映射到 `END` 表示图结束。

---

## Q6: "DeerFlow-First: 不直接调用 LLM API，全部通过 SubagentExecutor"是什么意思？ `📄 research_nodes.py`

**A:** 每个节点内部不写 `chat_model.invoke()` 这样的原始 LLM 调用，而是使用 DF 框架封装的 `SubagentExecutor`。

```python
# ❌ 直接调用 LLM（违反 DF-First）
from langchain_openai import ChatOpenAI
model = ChatOpenAI(model="gpt-4")
response = model.invoke("请分析这些数据...")

# ✅ 通过 DF 的 SubagentExecutor（DF-First）
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.executor import SubagentExecutor
from deerflow.tools import get_available_tools

config = SubagentConfig(
    name="critic_agent",
    system_prompt=CRITIC_AGENT_PROMPT,   # 角色提示词
    tools=["read_file", "python"],        # 工具白名单
    model="claude-opus-4-7",              # 指定模型
    max_turns=30,                         # 最大执行轮次
)
tools = get_available_tools()             # DF 统一加载工具
executor = SubagentExecutor(config, tools)
result = executor.execute(task)           # result 是完整的 Agent 输出字符串
```

**SubagentExecutor 替我们做了什么**：
1. 创建子 Agent（内部调用 `create_agent()`）
2. 加载工具并注入沙箱
3. 运行 Agent 循环（ReAct：思考→调工具→观察结果→再思考）
4. 处理超时、取消、异常
5. 返回最终文本输出

**为什么必须这样**：
- 沙箱路径转换才会生效（虚拟路径 `/mnt/user-data/workspace/` ↔ 物理路径）
- 中间件链才会执行（SandboxMiddleware、ToolErrorHandlingMiddleware 等）
- 工具白名单控制才生效（`tools=["read_file", "python"]` 精确限制每个角色的能力）
- 符合 CLAUDE.md Section 2.1 的"DF 原生实现 > 外围封装 > 外部框架 > 从零自建"优先级

---

## Q7: 节点通过什么输入输出？ `📄 research_nodes.py`

**A:** 所有节点遵循统一的函数签名：

```python
def xxx_node(state: ResearchSubGraphState) -> dict:
    #           ↑ 输入                   ↑ 输出
```

**输入** — `state` 是 LangGraph 在调用节点前自动从 State Channels 组装的当前 `ResearchSubGraphState`。节点只读自己需要的字段：

```python
# PI Agent 读用户请求（在 messages 里）
def pi_agent_node(state: ResearchSubGraphState) -> dict:
    # 不需要 scout_results、challenges 等——PI 是入口节点

# Critic Agent 只读 scout_results
def critic_agent_node(state: ResearchSubGraphState) -> dict:
    scout_results = state.get("scout_results", [])   # 读采集结果
    debate_round = state.get("debate_round", 0)       # 读当前轮次
    # 不需要 research_plan、ruling——Critic 不关心这些
```

**输出** — `dict` 包含要更新的字段。LangGraph 自动将 dict 的 key-value 写回对应的 State Channel：

```python
# Critic 审查完
return {
    "challenges": [challenge_data],      # → 写入 state.challenges (Annotated[list, add])
    "debate_round": new_round,           # → 覆盖 state.debate_round
}
# 注意：scout_results 没有被返回 → 保持不变
```

**输入来自 state_in，输出经过 state_out**：

```
Parent Graph 调用 Research SubGraph 时:
  state_in(map_parent_to_research) → 投影 Parent 字段到 ResearchSubGraphState
    ↓
  Research 内部节点读写 ResearchSubGraphState
    ↓
  state_out(map_research_to_parent) → 投影 ResearchSubGraphState 到 Parent
```

---

## Q8: 当 error 发生后，系统流转状态怎么走？ `📄 research_nodes.py` `📄 graph.py`

**A:** 分四步，从子图内部传递到父图降级处理。

**第一步：节点内捕获异常**

```python
def critic_agent_node(state: ResearchSubGraphState) -> dict:
    try:
        ...
    except Exception as e:
        logger.exception("critic_agent_node failed")
        return {"error": f"Critic Agent: {e}"}
```

节点不抛异常，而是把错误信息写入 `state.error` 字段（返回 dict）。

**第二步：Research SubGraph 结束，state_out 映射**

```python
# state_mapping.py
def map_research_to_parent(child_state, parent_state) -> dict:
    error = child_state.get("error")
    if error is not None:
        result["collaboration_error"] = error  # ← 子图 error → 父图 collaboration_error
    return result
```

**第三步：Parent Graph 条件路由检测**

```python
# graph.py
def route_after_research(state: CollaborationState) -> Literal[...]:
    if state.get("collaboration_error"):
        return "error_handler"        # ← 跳到错误处理
    return "analysis_subgraph"        # ← 正常流程
```

**第四步：Parent 层 error_handler 记录并终止**

```python
# graph.py
builder.add_edge("error_handler", END)  # 错误处理后直接结束图
```

**完整流转路径**：

```
Research SubGraph 内部:
  critic_agent_node 抛出异常
    → return {"error": "Critic Agent: LLM timeout"}
    → ResearchSubGraphState.error = "Critic Agent: LLM timeout"

Research SubGraph 结束:
  → state_out: map_research_to_parent()
    → CollaborationState.collaboration_error = "Critic Agent: LLM timeout"

Parent Graph 路由:
  → route_after_research(state)
    → collaboration_error 不为空 → return "error_handler"
    → 跳过 Analysis SubGraph（不浪费资源在坏数据上）
    → 跳过 HITL Gate（没有可审核的内容）

Parent 层 error_handler:
  → 记录日志 → END
```

**关键设计意图**：错误不抛异常跨越图边界，而是通过 state 字段传递。这样 Parent 的 `add_conditional_edges` 可以优雅地跳过整个 Analysis 阶段，而不是崩溃。用户最终得到的是"研究阶段失败"的状态，而不是一个 500 错误。

---

## Q9: 我们是不是在 DF 的 SubagentExecutor 上面又叠了一层状态循环？ `📄 research_nodes.py` `📄 graph.py`

**A:** 是的——这是完全正常的分层设计，两层循环在不同的抽象层级和时间尺度上运作。

```
我们的协作图（分钟~小时级循环）
  ┌─ Research SubGraph ──────────────────────────┐
  │  PI → Scout → Critic → Scout → Judge → PI    │  ← 角色间流转（外层）
  │    ↓        ↓         ↓        ↓       ↓      │
  │  [SubagentExecutor 内部 ReAct]  ×6 次          │  ← 每个角色内部循环（内层）
  │    "搜一下价格" → "读结果" → "不够再搜" → ...   │      (秒~分钟级)
  └──────────────────────────────────────────────┘
```

类比：建筑项目经理 vs 工人——项目经理决定"谁做哪一步"（外层），工人接到任务后自己决定"用什么工具怎么干"（内层）。

**两层解决不同问题**：

| | 外层：Graph 循环 | 内层：SubagentExecutor ReAct |
|---|---|---|
| 决策者 | LangGraph 条件路由 | 单个 Agent 的 LLM |
| 循环内容 | 选择"谁做下一步" | 选择"用什么工具" |
| 周期 | 角色间流转，分钟~小时 | 单次工具调用，秒~分钟 |
| 状态 | CollaborationState 全生命周期 | Subagent 内部 messages（用完即弃） |

**这不是 DF-First 造成的冗余**。即使不用 DF，用原生 LangGraph 手写节点，仍然需要两层——critic_agent_node 内部你要自己写 Agent 循环（调 LLM → 解析 → 调工具 → 再调 LLM）。DF 的 SubagentExecutor 只是帮你封装了内层循环，你不必手写 100 行 ReAct 代码。DF-First 意味着"内层不重复造轮子，专注外层多角色编排"。

---

## Q10: error_handler 终止后会自动重试吗？ `📄 research_nodes.py` `📄 graph.py`

**A:** 不会。`error_handler → END` 是图执行的终态，不会自动重试。

**当前设计逻辑**：
- 错误即终态——Research 失败意味着没有可靠数据，Analysis 继续没有意义
- 状态已持久化——checkpointer 保存了失败时刻的完整 State，用户可以看到"哪个阶段失败了"
- 重试需要外部触发——用户（或上层调用者）重新 `invoke()` 同一个 thread_id，从最后一个成功 checkpoint 恢复

**不是 DF 内置功能**——DF 的 SubagentExecutor 内部有超时和取消机制，但没有跨节点自动重试。如果我们后续需要（如网络超时自动重试 3 次），要在节点内部自己加 try/retry 逻辑，属于 Sprint 4 错误处理的增强项，不是当前 Sprint 2 的范围。

> **下一主题**: [03 — Parent Graph 组装与条件路由](03-graph-orchestration.md) *(待编码)*
