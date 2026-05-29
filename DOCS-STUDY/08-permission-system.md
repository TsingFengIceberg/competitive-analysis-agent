# 08 — 角色权限体系：Action 映射 + PermissionGuardMiddleware

> **日期**: 2026-05-15 | **Sprint**: 4 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/permissions/role_definition.py`](../backend/packages/harness/deerflow/collaboration/permissions/role_definition.py) | Action 枚举、RoleDefinition、ROLES 矩阵、Action→Tool 映射 |
| [`backend/packages/harness/deerflow/collaboration/permissions/permission_guard.py`](../backend/packages/harness/deerflow/collaboration/permissions/permission_guard.py) | AgentMiddleware 子类，before_tool_call 拦截 |

---

# Part A: role_definition.py

## Q1: 独立角色定义文件 + 这一系列类的解耦好处是什么？ `📄 role_definition.py`

**A:** 三层关注点分离：

```
role_definition.py        permission_guard.py       SubagentConfig
   (数据定义)                (执行逻辑)              (Agent 配置)
       │                        │                        │
  Action 枚举            before_tool_call()         tools 白名单
  RoleDefinition         检查 role→action→tool      system_prompt
  ACTION_TOOL_MAP                                  model/max_turns
```

具体好处：

- **数据与逻辑分离**：`permission_guard.py` 不需要知道有哪些角色、每个角色能做什么——它只需要调 `get_role(name)` 然后 `role.can(action)`。新增角色不改 guard 代码。
- **可独立测试**：角色定义是否正确（比如 Critic 确实没有 `SEARCH_WEB` 权限）可以直接在 `ROLES` 字典上做数据断言，不需要起 middleware。
- **可读性**：`ROLES` 字典本身就是一份可读的权限矩阵文档，所有角色和权限在一个文件里一览无余。
- **复用**：`find_action_for_tool()` 和 `get_role()` 不仅给 guard 用，node 函数里也可以用来校验自己的行为是否符合角色约束。

---

## Q2: 空的 `ACTION_TOOL_MAP` 项是遗漏还是正常的？ `📄 role_definition.py`

**A:** 正常——这些是"认知型操作"，发生在 LLM 推理过程中，不通过工具调用。

```python
Action.PLAN_RESEARCH: [],      # 纯 LLM 推理（在响应里规划，不调工具）
Action.CHALLENGE: [],          # 纯 LLM 推理（在响应里生成 Challenge JSON）
Action.ADJUDICATE: [],         # 纯 LLM 推理（在响应里生成 Ruling JSON）
Action.REVIEW_RULING: [],      # 纯 LLM 推理（阅读+判断）
Action.OVERRIDE_RULING: [],    # 纯 LLM 推理（推翻+输出审计日志）
Action.PLAN_ANALYSIS: [],     # 纯 LLM 推理（规划分析维度）
```

**关键区分**：

```
SEARCH_WEB  → Agent 调用 web_search 工具 → before_tool_call 能拦截 ✓
CHALLENGE   → Agent 在思考中判断"数据不可靠，来源A和B冲突"
              → 输出文本 → 没有工具调用 → middleware 拦截不到 ✗
```

空列表不是"还没加"，而是"这种操作本质上不经过工具调用层"。

但空列表仍有价值：
1. **文档价值**：完整刻画角色的职责边界
2. **未来可用**：如果以后为某些认知型操作封装专门工具（比如 `write_challenge` 工具），填上映射即可让权限立即生效

---

## Q3: `class Action(str, Enum)` 的枚举值（如 `"plan_research"`）是 DeerFlow 定义的吗？ `📄 role_definition.py`

**A: 全部是我们自定义的。** DeerFlow 不提供"角色权限"这个概念。

这里有两层映射关系：

```
我们定义的（抽象层）              DeerFlow 的（具体层）
     Action                          Tool Name
    "plan_research"        ──→     （不映射到任何工具）
    "search_web"           ──→     "web_search", "tavily_search", "firecrawl_search"
    "fetch_web"            ──→     "web_fetch", "firecrawl_scrape", "jina_reader"
    "python_compute"       ──→     "python", "bash"
    "write_output"         ──→     "write_file", "present_files"
```

**设计意图**：权限系统不应该和具体工具名耦合。如果直接在 guard 里写 `if tool_name == "web_search"`，换一个搜索引擎工具就得改 guard 代码。通过 Action 抽象层，只需改 `ACTION_TOOL_MAP` 即可。

---

## Q4: 反向索引 `TOOL_TO_ACTION` 的用处是什么？具体在什么场景下用到？ `📄 role_definition.py`

**A:** 给 `PermissionGuardMiddleware.before_tool_call()` 做 O(1) 查询。

**具体场景**——Data Scout 想调用 `web_search`：

```python
# permission_guard.py:98-99
tool_name = str(tool_call.get("name", ""))   # → "web_search"
action = find_action_for_tool(tool_name)      # → Action.SEARCH_WEB
```

然后：
```python
# Data Scout 调 web_search
role.can(Action.SEARCH_WEB) → True ✓ → 工具正常执行

# Critic 调 web_search
role.can(Action.SEARCH_WEB) → False ✗ → 返回 ToolMessage({"error": "permission_denied"})
```

**为什么需要反向索引（性能）**：`before_tool_call` 对**每一次**工具调用都触发。一次协作任务可能调用 200+ 次工具：

```
无反向索引：每次遍历 16 个 Action × N 个工具 → 200×16 = 3200 次循环
有反向索引：TOOL_TO_ACTION.get("web_search")  → O(1) 字典查询
```

另外还支持**前缀匹配** fallback（如 `firecrawl_search_v2` 匹配 `firecrawl_search`），精确匹配失败时执行一次。

---

# Part B: permission_guard.py

## Q5: 为什么把 PermissionGuardMiddleware 定义在这里而不是 DF 的 middlewares 目录？ `📄 permission_guard.py`

**A:** 两个原因都对，但主次不同。

**主要原因：它是业务层中间件，不是框架层中间件。**

DF 的 18 个中间件（SandboxMiddleware、MemoryMiddleware 等）是**通用基础设施**——任何 Agent、任何一次运行都需要它们。是"横切关注点"。

PermissionGuardMiddleware 不同——它只在协作图里生效，依赖 `role_definition.py` 里的角色数据，是**协作协议专属的业务逻辑**。

层级对比：

```
agents/middlewares/          ← 框架层：服务所有 Agent
    SandboxMiddleware        "每次 agent 运行都要沙箱"
    MemoryMiddleware         "每次 agent 运行都要记忆"
    ...

collaboration/permissions/   ← 业务层：仅服务协作图
    PermissionGuardMiddleware  "只有协作图里的角色需要权限门控"
```

**次要原因**才是"不改 DF 代码"——如果需求合理，DF 允许我们在 `_build_middlewares()` 里**注册**新中间件（不是修改已有中间件）。所以即使放在 `collaboration/` 下，最终也会在 lead_agent 里注册它。

**结论**：就算没有"不改 DF"的约束，这个中间件也天然属于 `collaboration/`——它不是通用框架能力，而是协作协议的组成部分。

---

## Q6: `_get_current_role` 里的 `runtime` 参数和 `get_current_agent_role` 用了 Python 什么机制？ `📄 permission_guard.py`

**A: 核心机制是 `contextvars`**——Python 标准库提供的"异步安全的线程局部变量"。

```python
# DF 内部（Sprint 5 需要实现）
from contextvars import ContextVar

agent_role: ContextVar[str] = ContextVar("agent_role", default="")

# SubagentExecutor 创建子代理时设置
token = agent_role.set("critic_agent")
try:
    executor.execute(task)  # 整个 ReAct 循环内 agent_role = "critic_agent"
finally:
    agent_role.reset(token)
```

Guard 读取它：
```python
def get_current_agent_role() -> str:
    return agent_role.get()  # → "critic_agent"
```

**为什么需要 contextvars 而不是全局变量？** 协作图里有多个角色并行运行（Send API fan-out 出 3 个 Scout），全局变量会互相覆盖。contextvars 保证每个异步任务读到自己被赋予的角色。

**`runtime` 参数**：LangGraph 在触发 `before_tool_call` 钩子时自动传入，类型是 `langgraph.runtime.Runtime`，携带当前图的执行上下文（config、checkpointer、状态等）。第一种获取方式（`runtime.context.get("agent_role")`）是兜底 fallback——把角色名挂在 config 上传进来。

**现状**：`get_current_agent_role` 还不存在（代码里有 `# type: ignore[attr-defined]` 和 `ImportError` 兜底），这是 Sprint 5 要补的。

---

## Q7: `_has_evidence` 函数能给哪些地方派上用场？ `📄 permission_guard.py`

**A:** 只在 `before_tool_call()` 第 124 行调用，两个角色的两个操作会触发检查：

| 角色 | 操作 | 为什么需要证据 |
|------|------|--------------|
| **Critic** | `CHALLENGE` → 调 `python` 工具做数据校验 | 质疑必须引用具体数据点，不能空口说"我觉得有问题" |
| **Data Scout** | `RESPOND_TO_CRITIC` → 调 `web_search`/`web_fetch` 补采 | 回应质疑必须带新数据，不能只是辩解 |

举例——Critic 想调 `python` 工具检验数据一致性：

```python
# ❌ 没有证据 → 拒绝
tool_call = {"name": "python", "args": {"code": "import scipy; scipy.ttest_ind(...)"}}
_has_evidence(tool_call["args"])  # → False → 返回 ToolMessage 拒绝

# ✅ 工具参数里带了 source → 放行
tool_call = {"name": "python", "args": {"code": "...", "source": "scout_result[2].data"}}
_has_evidence(tool_call["args"])  # → True
```

**注意**：`_has_evidence` 检查的是工具调用的参数里有没有证据标记（`evidence`、`source`、`url` 等字段），不是 LLM 的推理内容。LLM 负责在工具调用时把证据放进参数里（通过 system prompt 约束），guard 负责验证它确实放了。

---

## Q8: permission_guard.py 触及调用了哪些 DF 封装的东西？ `📄 permission_guard.py`

**A: 只有一个——而且还不存在：**

```python
# 第 66 行 — 唯一触及 DF 的地方
from deerflow.runtime.user_context import get_current_agent_role  # type: ignore[attr-defined]
```

其余全部是 LangChain/LangGraph/我们自己的代码：

| 导入 | 来源 | 层级 |
|------|------|------|
| `AgentMiddleware` | `langchain.agents.middleware` | LangChain 框架 |
| `ToolMessage` | `langchain_core.messages` | LangChain 核心 |
| `AgentState` | `langchain.agents` (TYPE_CHECKING) | LangChain 框架 |
| `Runtime` | `langgraph.runtime` (TYPE_CHECKING) | LangGraph 框架 |
| `get_role`, `find_action_for_tool` | `deerflow.collaboration.permissions.role_definition` | **我们的代码** |

这说明权限门控系统几乎不依赖 DeerFlow 的具体实现。`AgentMiddleware` 是 LangChain 的标准抽象，只要是 LangGraph agent 就能用。唯一的 DF 触点（`get_current_agent_role`）是"如何知道当前 agent 是什么角色"这一信息传递问题，而不是权限检查逻辑本身。

---

## Q9: `_get_current_role` 为什么有 contextvars + runtime.context 两层 fallback？ `📄 permission_guard.py` `📄 context.py`

**A:** 两个路径，一个目标 — 拿到当前角色名才能做权限检查：

```
主路径（contextvars）          兜底路径（runtime.context）
───────────────────          ──────────────────────────
with current_role("pi"):     config = {"configurable":
    executor.execute(task)      {"agent_role": "pi"}}
    │                           │
    └─ get_current_agent_role() └─ runtime.context.get("agent_role")
       → 读 ContextVar             → 读 config 字典
```

**主路径**：`context.py` 的 `ContextVar`——节点函数里用 `with current_role("pi_agent")` 包裹 SubagentExecutor，整个 ReAct 循环内 context var 都是 `"pi_agent"`。

**兜底路径**的存在原因：

1. **还没人 set context var**：如果某个节点忘了用 `with current_role(...)`，主路径拿到空字符串，去 config 字典里碰。但如果两边都没设，两路都走不通——不是"碰运气"能猜中，而是给可能的集成路径留口子。

2. **多线程边界**：`contextvars` 在 Python 标准线程中默认不传播。DF 的 SubagentExecutor 用双线程池，如果子代理在新线程中执行，context var 可能丢失。`runtime.context` 是跟着 `RunnableConfig` 走的 dict，跨线程不丢。

3. **架构预留**：LangGraph 生态里把 `agent_role` 这类元数据挂 `config.context` 上是惯例。如果将来 DF 的 SubagentExecutor 升级后在 spawn 子代理时自动从 `SubagentConfig.name` 写入 `context["agent_role"]`，这条兜底路径自动生效，不需要改 guard 代码。

坦白讲：当前这个 fallback 更像是"架构预留"而非"有效保障"。`get_current_agent_role()` 返回空字符串 → 两路都空 → 跳过权限检查（放行）。

---

## Q10: `context.py` 的实现用了 Python 什么机制？怎么用？ `📄 context.py`

**A:** `contextvars.ContextVar`——Python 3.7+ 标准库，async 安全的"任务局部变量"。

```python
# context.py
from contextvars import ContextVar

_agent_role: ContextVar[str] = ContextVar("agent_role", default="")

def get_current_agent_role() -> str:
    return _agent_role.get()  # 读取当前任务的角色

@contextmanager
def current_role(role_name: str):
    token = _agent_role.set(role_name)   # 设置
    try:
        yield
    finally:
        _agent_role.reset(token)         # 恢复旧值
```

**为什么需要 contextvars 而不是全局变量？**

协作图里有多个角色并行运行（Send API fan-out 出 3 个 Scout），全局变量会被互相覆盖：

```
时间线：
  Scout A: agent_role = "scout_A"    ← 全局变量被覆盖！
  Scout B: agent_role = "scout_B"    ← 又覆盖！
  Scout A 调 web_search → guard 读到 "scout_B" → 错！

contextvars 下：
  Scout A 的 task: agent_role = "scout_A"  ← 各自独立
  Scout B 的 task: agent_role = "scout_B"  ← 互不干扰
```

**vs threading.local**：`threading.local` 只在多线程场景下隔离，`asyncio` 单线程多协程场景会串。`contextvars` 在 `asyncio.Task` 之间也是隔离的，适合 LangGraph 的 async 执行模型。

**节点函数里的用法**：
```python
def critic_agent_node(state: ResearchSubGraphState) -> dict:
    config = SubagentConfig(name="critic_agent", ...)
    executor = SubagentExecutor(config, tools)

    with current_role("critic_agent"):
        result = executor.execute(task)
    # 离开 with 块后 agent_role 自动恢复为空

    return {"challenges": challenges}
```
