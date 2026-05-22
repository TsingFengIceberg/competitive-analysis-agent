# PA-Agent-DF 商品协同分析系统 — 架构与需求文档

> **版本**: v2.1 | **日期**: 2026-05-15 | **阶段**: Phase 3 完成，Phase 4 待实施

---

## 目录

1. [GitHub 生态调研与竞品分析](#1-github-生态调研与竞品分析)
2. [DeerFlow 底座深度分析](#2-deerflow-底座深度分析)
3. [业务场景设计：泛商品协同分析](#3-业务场景设计泛商品协同分析)
4. [多智能体协作模型：数字调研小组](#4-多智能体协作模型数字调研小组)
5. [LangGraph 工作流编排设计](#5-langgraph-工作流编排设计)
6. [技术 USP 设计](#6-技术-usp-设计)
7. [工程质量与生产考量](#7-工程质量与生产考量)
8. [目录结构与模块规划](#8-目录结构与模块规划)
9. [实施路线图](#9-实施路线图)
10. [附录](#10-附录)

---

## 1. GitHub 生态调研与竞品分析

### 1.1 直接可比的 GitHub 开源项目

在 2026 年的 GitHub 生态中，以下项目与我们的目标场景直接可比：

| 项目 | Stars | 技术栈 | 核心亮点 | 我们的差异化 |
|------|-------|--------|---------|-------------|
| [competitor-hunter](https://github.com/Duang777/competitor-hunter) | 新项目 | LangGraph + MCP + Playwright | SaaS 竞品抓取分析，六边形架构（CLI/MCP/Python Lib） | 我们增加多角色协作 + HITL |
| [Product-Research-Multi-Agent-System](https://github.com/To11-o11/Product-Research-Multi-Agent-System) | 新项目 | 多 Agent + LLM | Planner → Search → Review → Writer 四阶段，中文场景，约 20 分钟完成任务 | 我们增加 Cross-Validation 自纠正循环 |
| [Multi-Agent-BDS](https://github.com/aparaajita19/Multi-Agent-BDS) | 新项目 | Grok + Pandas + Streamlit | 4 Agent 电商情报平台，跨平台对比（Amazon/Meesho/Flipkart/Myntra） | 我们增加 LangGraph 图编排 + 动态重规划 |
| [e-commerce-agents](https://github.com/nitin27may/e-commerce-agents) | - | Python + Microsoft Agent Framework + A2A | 6 Agent 全功能电商平台，PostgreSQL/pgvector + Redis + OpenTelemetry | 我们专注分析场景而非交易场景 |
| [Research_agents](https://github.com/towardsforever/Research_agents) | - | LangGraph StateGraph + SubGraph | 分层架构，Data/Chart/Paper/FAQ Agent，ChromaDB/FAISS + Gradio | 我们增加 HITL + 自纠正循环 |
| [DeepShop](https://github.com/youganglyu/DeepShop) | - | - | 深度购物 Agent 基准测试，5 大品类，两阶段查询演化 | 可作为我们的评估基准 |
| [AgenticPay](https://github.com/SafeRL-Lab/AgenticPay) | - | Claude Opus 4.5 | 多 Agent 买卖谈判，110+ 任务 | 定价优化场景的参考基准 |

### 1.2 2026 年主流框架格局与我们的定位

| 框架 | Stars | 架构范式 | 生产就绪度 | 定位 |
|------|-------|----------|-----------|------|
| **LangGraph** | 25K+ | 图状态机 (StateGraph) | ⭐⭐⭐⭐⭐ | **我们的编排层** — 复杂有状态工作流 |
| **CrewAI** | 44.6K+ | 角色化团队 | ⭐⭐⭐⭐ | 快速原型参考，但缺少图式状态管理 |
| **AutoGen (AG2)** | 36.8K+ | 对话式多 Agent | ⭐⭐ (维护模式) | 学术参考 |
| **OpenAI Agents SDK** | 19.1K+ | Handoff 链 | ⭐⭐⭐⭐ | OpenAI 生态内的轻量方案 |

**我们的定位**: LangGraph（执行层）+ DeerFlow（工具/沙箱/中间件底座）+ 自定义协作协议（差异化层）。这一定位避免了与 CrewAI 的角色化模式的同质化竞争，同时利用了 LangGraph 在生产环境的验证优势（已被 Uber、LinkedIn、Klarna、Replit 等企业验证）。

### 1.3 2026 年三大技术共识

1. **MCP 协议** — 模型上下文管理的事实标准，Agent 与外部工具/数据源的标准接口
2. **A2A 协议** — Agent-to-Agent 通信标准，推动从单体 Agent 走向分布式协作
3. **多框架混合架构** — 主流方案：LangGraph（执行编排）+ 专用工具框架（MCP/A2A）+ 业务逻辑层（自定义）

---

## 2. DeerFlow 底座深度分析

### 2.1 核心架构全景

DeerFlow 是一个基于 **LangChain + LangGraph** 的 AI Super Agent 系统，采用 **Harness/App 分层架构**：

```
backend/
├── packages/harness/deerflow/   ← 可发布的 Agent 框架 (import: deerflow.*)
│   ├── agents/          # Lead Agent 工厂 + 18 个中间件
│   ├── sandbox/         # 沙箱抽象层 (Sandbox ABC, SandboxProvider ABC)
│   ├── subagents/       # 子代理执行引擎
│   ├── tools/           # 工具系统 (沙箱工具 + 内置工具 + MCP)
│   ├── models/          # 模型工厂 (多Provider, thinking/vision 支持)
│   ├── mcp/             # MCP 多服务器客户端
│   ├── skills/          # 技能系统
│   ├── memory/          # 长短期记忆 (per-user, per-agent)
│   ├── config/          # 配置系统 (热加载)
│   └── runtime/         # 运行时 (checkpointer, store, stream_bridge)
└── app/                  ← 应用层 (import: app.*)
    ├── gateway/          # FastAPI Gateway (REST + LangGraph Runtime)
    └── channels/         # IM 平台集成 (飞书/Slack/Telegram/DingTalk)
```

**关键设计原则**: Harness 层绝不 import App 层，由 `test_harness_boundary.py` 在 CI 中强制执行。

### 2.2 Agent 系统核心

#### Lead Agent 工厂 (`agents/lead_agent/agent.py`)

```python
def make_lead_agent(config: RunnableConfig):
    """LangGraph graph factory — 注册在 langgraph.json 中"""
    # → create_agent(model, tools, middleware, system_prompt, state_schema=ThreadState)
```

**关键参数** (通过 `config.configurable` 传入):

| 参数 | 说明 |
|------|------|
| `thinking_enabled` | 启用模型扩展思考 |
| `model_name` | 指定 LLM 模型 |
| `is_plan_mode` | 启用 TodoList 中间件 |
| `subagent_enabled` | 启用 task 委托工具 |
| `max_concurrent_subagents` | 并发子代理上限 (默认 3) |
| `agent_name` | 自定义 Agent 名称 |

#### ThreadState 状态结构 (`agents/thread_state.py`)

```python
class ThreadState(AgentState):
    sandbox: SandboxState | None           # sandbox_id
    thread_data: ThreadDataState | None     # workspace/uploads/outputs 路径
    title: str | None                      # 自动生成的线程标题
    artifacts: list[str]                   # 输出文件列表 (merge_artifacts reducer)
    todos: list | None                     # 计划模式任务列表
    uploaded_files: list[dict] | None      # 上传文件信息
    viewed_images: dict[str, ViewedImageData]  # 已查看的图像
```

### 2.3 中间件链 (18 个中间件，严格顺序)

```
 1. ThreadDataMiddleware      ← 创建 per-thread 隔离目录
 2. UploadsMiddleware          ← 追踪上传文件
 3. SandboxMiddleware          ← 获取沙箱，存储 sandbox_id
 4. DanglingToolCallMiddleware ← 修复孤儿 ToolMessage
 5. LLMErrorHandlingMiddleware ← 标准化 Provider 错误
 6. GuardrailMiddleware        ← 工具调用前授权
 7. SandboxAuditMiddleware     ← 沙箱操作安全审计
 8. ToolErrorHandlingMiddleware← 工具异常 → 错误 ToolMessage
 9. SummarizationMiddleware    ← 上下文压缩 (可选)
10. TodoListMiddleware         ← write_todos 工具 (plan_mode)
11. TokenUsageMiddleware       ← Token 用量追踪
12. TitleMiddleware            ← 自动生成标题
13. MemoryMiddleware           ← 记忆队列 (user + AI 消息)
14. ViewImageMiddleware        ← 图像注入 (vision 模型)
15. DeferredToolFilterMiddleware ← 延迟工具搜索 (可选)
16. SubagentLimitMiddleware    ← 截断超额 task 调用 (max 3)
17. LoopDetectionMiddleware    ← 检测并中断工具调用循环
18. ClarificationMiddleware    ← 拦截 ask_clarification，中断流程
```

**关键洞察**: 中间件链为 Multi-Agent 扩展提供了天然注入点。我们可以在中间件链中插入 **CollaborationMiddleware** 实现协作上下文感知。

### 2.4 沙箱系统 — 核心安全边界

#### 抽象接口 (Sandbox ABC)

```python
class Sandbox(ABC):
    def execute_command(self, command: str) -> str: ...
    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str, append: bool = False) -> None: ...
    def list_dir(self, path: str, max_depth=2) -> list[str]: ...
    def glob(self, path: str, pattern: str, ...) -> tuple[list[str], bool]: ...
    def grep(self, path: str, pattern: str, ...) -> tuple[list[GrepMatch], bool]: ...
    def update_file(self, path: str, content: bytes) -> None: ...
```

#### 提供者模式 (SandboxProvider ABC)

```python
class SandboxProvider(ABC):
    def acquire(self, thread_id: str | None) -> str: ...  # 获取沙箱 → 返回 sandbox_id
    def get(self, sandbox_id: str) -> Sandbox | None: ...  # 按 ID 获取
    def release(self, sandbox_id: str) -> None: ...         # 释放沙箱
```

#### 两种实现

| 实现 | 位置 | 特点 |
|------|------|------|
| `LocalSandboxProvider` | `sandbox/local/` | 单例，路径映射 (虚拟→物理)，安全验证 |
| `AioSandboxProvider` | `community/aio_sandbox/` | Docker 隔离，HTTP API 通信 |

#### 虚拟路径系统 (LocalSandbox 核心机制)

```
Agent 视角                     物理路径
/mnt/user-data/workspace  →  {base}/users/{uid}/threads/{tid}/user-data/workspace
/mnt/user-data/uploads    →  {base}/users/{uid}/threads/{tid}/user-data/uploads
/mnt/user-data/outputs    →  {base}/users/{uid}/threads/{tid}/user-data/outputs
/mnt/skills               →  {project}/skills/
/mnt/acp-workspace        →  {base}/threads/{tid}/acp-workspace/
```

**安全验证层** (5 层纵深防御):
- `validate_local_tool_path()` — 只允许 `/mnt/user-data/*`, `/mnt/skills/*` (只读), `/mnt/acp-workspace/*` (只读), 自定义挂载
- `validate_local_bash_command_paths()` — 拦截绝对路径逃逸、`..` 遍历、`file://` URL
- `_reject_path_traversal()` — 拒绝包含 `..` 段的路径
- `mask_local_paths_in_output()` — 输出路径掩码，物理路径还原为虚拟路径
- `validate_resolved_user_data_path()` — 解析后路径必须在允许根目录内

### 2.5 子代理执行引擎 (`subagents/executor.py`)

这是实现 Multi-Agent 协作的关键组件：

```python
class SubagentExecutor:
    def __init__(self, config: SubagentConfig, tools, app_config,
                 parent_model, sandbox_state, thread_data, thread_id, trace_id): ...

    def execute(self, task: str) -> SubagentResult: ...       # 同步执行
    def execute_async(self, task: str) -> str: ...            # 异步后台执行
    def _aexecute(self, task: str) -> SubagentResult: ...     # 核心异步执行
```

**子代理配置 (SubagentConfig)**:
```python
@dataclass
class SubagentConfig:
    name: str                    # 唯一标识
    description: str             # 何时使用此子代理
    system_prompt: str | None    # 角色提示词
    tools: list[str] | None      # 允许的工具白名单
    disallowed_tools: list[str]  # 禁止的工具 (默认禁用 task 防止递归)
    skills: list[str] | None     # 加载的技能
    model: str                   # 模型选择 ("inherit" = 使用父代理模型)
    max_turns: int = 50          # 最大轮次
    timeout_seconds: int = 900   # 超时 (15 分钟)
```

**并发控制**:
- `MAX_CONCURRENT_SUBAGENTS = 3`
- `_scheduler_pool` (ThreadPoolExecutor, 3 workers)
- 持久化隔离事件循环 (`_isolated_subagent_loop`)
- 合作式取消 (`cancel_event`)

**关键洞察**: `SubagentExecutor` 已经是成熟的子代理执行引擎，支持独立的 tools/skills/model 配置。我们的 Multi-Agent 协作系统应该**包装 SubagentExecutor**，而非替换它。每个协作者（Data Scout, Cross-Validator 等）本质上是一个配置了特定 system_prompt、tools 和 skills 的 SubagentExecutor。

### 2.6 工具系统全景

#### 沙箱工具 (7 个)
`bash`, `ls`, `read_file`, `write_file`, `str_replace`, `glob`, `grep`

#### 内置工具
`present_files`, `ask_clarification`, `view_image`, `setup_agent`, `update_agent`, `task` (子代理委托), `tool_search`

#### 社区工具 (数据采集关键)
| 工具 | 来源 | 功能 |
|------|------|------|
| `web_search` | Tavily | 网页搜索 (5 条结果) |
| `web_fetch` | Tavily / Jina AI | 网页内容抓取 (4KB) |
| `firecrawl` | Firecrawl | 高级网页抓取 |
| `ddg_search` | DuckDuckGo | 搜索 |
| `image_search` | DuckDuckGo | 图片搜索 |

#### MCP 工具
通过 `langchain-mcp-adapters` 集成外部 MCP 服务器，支持 stdio/SSE/HTTP 传输。**MCP 是 2026 年 Agent-工具交互的事实标准**，我们应优先以 MCP 形式封装数据采集能力。

### 2.7 记忆系统

```
MemoryMiddleware → 过滤消息 (user + AI) → Queue (debounce 30s)
→ Background Thread → LLM 提取 Facts/Context → 原子写入 memory.json
→ 下次对话注入 <memory> 标签 (top 15 facts)
```

**数据结构**:
- User Context: `workContext`, `personalContext`, `topOfMind`
- History: `recentMonths`, `earlierContext`, `longTermBackground`
- Facts: `{id, content, category, confidence, source}`

### 2.8 底座能力复用矩阵

| 能力 | DeerFlow 原生 | 我们的策略 |
|------|---------------|-----------|
| Agent 创建 | `create_agent()` | **复用** — 每个协作者基于此创建 |
| 沙箱隔离 | `LocalSandbox` + 虚拟路径 | **复用** — 文件操作全部走沙箱 |
| 子代理执行 | `SubagentExecutor` | **包装复用** — 封装为图节点 |
| 工具链 | 沙箱 + 社区 + MCP 工具 | **复用** — 数据采集直接使用 |
| 中间件 | 18 个中间件 | **复用** — 插入自定义 CollaborationMiddleware |
| 记忆 | Memory 系统 | **扩展复用** — 增加协作记忆维度 |
| 配置 | YAML 热加载 | **扩展** — 增加协作图配置段 |
| 流式 | Stream Bridge | **复用** — 图执行事件流式输出 |
| Checkpoint | LangGraph Checkpointer | **复用** — HITL 暂停/恢复依赖此机制 |

---

### 2.9 DF 基座深度利用设计 (CRITICAL)

> **设计原则**: 不仅用 DF 的"壳"（Agent 框架），更要用 DF 的"核"——沙箱计算、Skills 复用、Memory 积累、文件上传转换、MCP 外部工具链。

#### 2.9.1 沙箱：从"文件存储"升级为"数据计算引擎"

当前设计中沙箱仅用于 JSON 文件读写和 Report Composer 的图表生成。这严重低用了 DF 沙箱的完整 Linux + Python 能力。

**升级方案 — 每个角色都配 Python 沙箱计算能力**:

| 角色 | 沙箱计算任务 | 使用的库 | 产物 |
|------|-------------|---------|------|
| **Data Scout** | 数据清洗 + 格式化 + 去重合并 | `pandas`, `json` | `cleaned_dataset_{dimension}.csv` |
| **Data Scout** | 网页批量抓取脚本 | `requests`, `beautifulsoup4` | `raw_scraped_{source}.json` |
| **Critic Agent** | 数据一致性计算 (差异百分比、异常值检测) | `pandas`, `numpy`, `scipy.stats` | `consistency_report.json` |
| **Meta-Judge** | 证据量化评估 (置信度加权计算) | `pandas`, `numpy` | `evidence_scoring.json` |
| **Synthesizer** | 对比矩阵计算 + 趋势回归 + SWOT 量化 | `pandas`, `scipy.stats`, `sklearn` | `analysis_dataset.csv` |
| **Report Composer** | 可视化生成 + 统计图表 | `matplotlib`, `plotly`, `seaborn` | 雷达图/趋势图/饼图/SWOT 矩阵 PNG |

**具体场景示例**:

```
Scout 使用 pandas 在沙箱中:
  1. 从 3 个来源采集到 iPhone 17 的价格数据 (JSON)
  2. 使用 pandas 合并、去重、检测缺失值
  3. 计算均值、中位数、标准差
  4. 输出 cleaned_dataset_pricing.csv 到 workspace

Critic 使用 scipy 在沙箱中:
  1. 读取 cleaned_dataset_pricing.csv
  2. 对多源价格数据做 t-test，检测是否有显著差异
  3. 输出 "来源A与来源B的价格差异显著 (p < 0.01)，可能为不同 SKU"
  4. 将统计结果写入 consistency_report.json

Synthesizer 使用 sklearn 在沙箱中:
  1. 读取完整分析数据集
  2. 做价格-评分线性回归，识别性价比异常产品
  3. 输出 "华为 Mate 70 Pro 的价格-评分比显著优于其他竞品 (残差 > 1.5σ)"
```

#### 2.9.2 文件上传 + 文档自动转换：用户的私域数据入口

DF 的 UploadsMiddleware + markitdown 文档转换（PDF/PPT/Excel/Word → Markdown）是我们的独有优势。这是 GitHub 上同类项目（competitor-hunter、Product-Research-Multi-Agent）**完全不具备**的能力。

**场景设计**:

| 上传文件类型 | 自动转换 | 协作用途 |
|-------------|---------|---------|
| 竞品规格表 (Excel) | → Markdown 表格 | Scout 的数据源之一，与网页采集数据合并验证 |
| 内部市场报告 (PDF) | → Markdown 文本 | Synthesizer 的背景知识，与实时采集数据互补 |
| 历史价格数据 (CSV) | → 结构化数据 | Critic 验证时的基准数据，检测趋势异常 |
| 产品发布会 PPT | → Markdown | Scout 提取最新规格参数 |
| 供应链合同 (Word) | → Markdown | 供应链风险评估的输入 |

**流程**:
```
用户上传 iPhone_17_specs.xlsx + market_report_2026Q1.pdf
  → DF UploadsMiddleware 自动转换为 Markdown
    → 注入到 ThreadState.uploaded_files
      → PI Agent 感知到附加数据源
        → Scout 采集时将上传文件作为 "high-confidence" 源
          → Critic 验证时优先使用上传文件数据作为基准
```

#### 2.9.3 Skills 系统：可复用的分析技能包

DF 的 Skills 系统（`SKILL.md` + `allowed-tools`）允许打包可复用的专业能力。我们的系统应提供以下协作专用 Skills：

| Skill 名称 | 功能 | 使用的工具 | 适用角色 |
|-----------|------|-----------|---------|
| `price-elasticity` | 价格弹性分析：输入多产品价格-销量数据，输出弹性系数和定价建议 | `python` (pandas, scipy) | Synthesizer |
| `sentiment-analyzer` | 用户评论情感分析：输入评论文本，输出情感分数和关键词提取 | `python` (nltk, textblob) | Data Scout |
| `market-share-calc` | 市场份额估算：基于多源销量数据加权计算市场份额区间 | `python` (pandas, numpy) | Synthesizer |
| `source-credibility` | 来源可信度评分：基于历史验证结果给数据源打分 | `read_file`, `python` | Critic Agent |
| `spec-comparator` | 规格对比矩阵生成：输入多产品规格 JSON，输出结构化对比表 | `python` (pandas) | Synthesizer |
| `trend-detector` | 趋势检测：时间序列数据的趋势识别和异常检测 | `python` (scipy, statsmodels) | Synthesizer |
| `data-normalizer` | 数据标准化：不同来源的数值统一单位、货币、格式 | `python` (pandas) | Data Scout |
| `swot-generator` | SWOT 结构化生成：基于分析数据自动填充 SWOT 矩阵 | `python`, `write_file` | Report Composer |

**Skills 在 SubGraph 中的加载**:
```python
# Data Scout 配置 — 加载数据采集相关 Skills
SubagentConfig(
    name="data_scout",
    skills=["data-normalizer", "sentiment-analyzer"],  # DF Skills 白名单
    tools=["web_search", "web_fetch", "python", "write_file"],
)

# Synthesizer 配置 — 加载分析相关 Skills
SubagentConfig(
    name="synthesizer",
    skills=["spec-comparator", "price-elasticity", "market-share-calc", "trend-detector"],
    tools=["read_file", "python", "write_file"],
)
```

#### 2.9.4 Memory 系统：跨会话智能积累

当前设计中 Memory 仅列为 USP #3 候选。基于 DF 的 per-user per-agent Memory 系统，我们可以实现两种协作记忆：

**A. 来源可信度档案 (Source Credibility Profile)**

每次分析结束后，基于 Cross-Validator 和 Meta-Judge 的验证结果，自动更新数据源评分：

```
Critic 发现: 来源 X (第三方 reseller) 的价格数据与 Apple 官网偏差 10%
Meta-Judge 裁决: 来源 X 可信度降低
  → 自动写入 Memory: 
    fact: "来源 X 的价格数据历史准确率 72%"
    category: "knowledge"
    confidence: 0.88
    source: "Meta-Judge Ruling #2026-05-14-001"

下次分析:
  → MemoryMiddleware 注入: "已知来源 X 的价格数据历史准确率 72%，建议交叉验证"
  → Scout 自动使用 3+ 来源验证来自 X 的数据
```

**B. 产品知识库 (Product Fact Database)**

```
Synthesizer 输出: iPhone 17 起售价 $999 (8+ 来源验证, 可信度 0.95)
  → 自动写入 Memory:
    fact: "iPhone 17 起售价: $999 (2026-05 验证)"
    category: "knowledge"
    confidence: 0.95

下次分析问及 iPhone 17:
  → MemoryMiddleware 注入: "已知 iPhone 17 起售价 $999 (5月验证, 可信度 0.95)"
  → Scout 无需重新搜索，直接使用已验证数据 (节省 30% Token)
  → 仅搜索"是否有变动"
```

#### 2.9.5 社区工具 + MCP：扩展数据采集维度

当前仅用 `web_search` + `web_fetch`。DF 社区工具体系中未利用的能力：

| 工具 | 当前使用 | 应使用场景 |
|------|---------|-----------|
| `firecrawl` | 未使用 | 电商商品页深度抓取（价格、规格、评价） |
| `image_search` | 未使用 | 商品外观对比、包装识别 |
| `jina_ai` (readability) | 未使用 | 长文评测/报告的正文提取 |

**MCP 扩展方向** (通过 DF MCP 系统接入):
- 电商 API MCP Server（Amazon Product Advertising / 淘宝联盟 API）
- 金融数据 MCP Server（Yahoo Finance / Alpha Vantage）
- 社交媒体监听 MCP Server（Reddit / Twitter API）

#### 2.9.6 DF 基座利用率提升总结

| 维度 | 优化前利用率 | 优化后利用率 | 关键变化 |
|------|------------|------------|---------|
| Sandbox 计算 | ~20% | **85%** | 每个角色有具体 Python/pandas 计算任务 |
| Skills 系统 | 0% | **60%** | 8 个协作专用 Skills |
| Memory 系统 | 0% | **70%** | 来源可信度 + 产品知识库双轨积累 |
| File Upload | 0% | **50%** | 用户私域数据作为高置信度源 |
| Community Tools | 25% | **70%** | firecrawl/image_search/jina_ai 全启用 |
| MCP 协议 | 5% | **50%** | 电商/金融/社交媒体 3 个 domain server |
| Middleware | 10% | **55%** | Guardrail(角色门控) + Audit(来源审计) + LoopDetection(辩论轮次) |
| **综合利用率** | **~20%** | **~65%** | **提升 3 倍以上** |

---

## 3. 业务场景设计：泛商品协同分析

### 3.1 场景定位

**泛商品分析 (Pan-Product Analysis)** — 围绕商品/电商数据展开的复杂分析任务，核心场景：

| 场景 | 描述 | 协作复杂度 | 典型 Token 消耗 |
|------|------|-----------|-----------------|
| **竞品深度拆解** | 选取目标商品，从多源采集竞品信息，交叉验证后输出多维对比报告 | ★★★★★ | 30-80 万 tokens |
| **市场趋势洞察** | 并行扫描多个市场/品类，识别新兴趋势、价格波动、需求变化 | ★★★★ | 20-40 万 tokens |
| **商品定价优化** | 监控竞品价格、分析需求弹性、考虑供应链成本 | ★★★★ | 25-50 万 tokens |
| **供应链风险评估** | 多源风险扫描 → 依赖链分析 → 风险评分 → 缓解建议 | ★★★★★ | 30-60 万 tokens |
| **新品上市可行性** | 市场容量评估 + 竞品格局 + 定价敏感度 + 渠道分析 | ★★★★★ | 40-80 万 tokens |

### 3.2 参考基准：2026 年同类系统的性能数据

来自 [Product-Research-Multi-Agent-System](https://github.com/To11-o11/Product-Research-Multi-Agent-System) 的真实数据：
- 将通常需要 **1-2 天** 的人工调研缩短至约 **20 分钟**
- 单次任务消耗约 **30-80 万 tokens**

来自 Qualtrics 2026 年 5 月的行业数据：
- Navy Federal Credit Union: 研究从 **5 天 → 4 小时**，误差 ±5%
- Booking.com: 合成面板产出与人类样本**相同程度方差**
- 行业预测: Agentic 研究系统采用率将从 15% → 44%（未来 6-12 个月）

### 3.3 核心业务场景详解：竞品深度拆解 (Primary Scenario)

以 **"iPhone 17 vs 竞品深度对比分析"** 为例，展示完整协作链路：

```
用户输入: "帮我做一份 iPhone 17 与主要竞品（华为 Mate 70 Pro、三星 S25 Ultra）的深度对比分析报告"

系统响应:
  1. 用户可选择上传内部资料 (Excel规格表 / PDF市场报告) → DF 自动转换为 Markdown
  2. PI Agent 拆解任务 → 生成 3 路并行采集计划 + 标记上传文件为"high-confidence 源"
  3. 3 个 Data Scouts 并行采集 (使用 web_search + firecrawl 深度抓取 + Python 数据清洗)
  4. Scouts 在沙箱中用 pandas 合并多源数据、去重、标准化格式
  5. PI 汇总 → Critic 使用 scipy 统计检验检测数据矛盾
  6. [如发现矛盾] → 定向补采 → Critic 再次统计验证 (最多 2 轮)
  7. Meta-Judge 基于量化证据裁决 → PI 审核
  8. ValidatedBrief → Analysis SubGraph
  9. Synthesizer 使用 sklearn 回归分析 + price-elasticity Skill 生成定价建议
 10. ⚡ HITL Gate → 用户审核交互式分析结果 (含图表)
 11. Report Composer 生成 Markdown 报告 + matplotlib/plotly 可视化
 12. 分析结束后 Memory 自动更新来源可信度档案 + 产品知识库
```

**数据采集维度**:
- **规格参数**: 芯片、屏幕、摄像头、电池、存储、材质
- **价格数据**: 官方价、渠道价、二手残值、历史价格趋势
- **用户口碑**: 评分、评价情感分析、常见问题、NPS
- **市场表现**: 销量数据、市场份额、增长趋势、区域分布
- **专业评测**: 科技媒体评测要点、跑分数据、影像对比
- **供应链信息**: 核心供应商、零部件成本估算、产能信息

**协作的必要性**: 单一 Agent 无法同时做到"广度采集 + 深度验证 + 多维分析"。参照 2026 年 Bioptic Agent 论文的发现——专门化的搜索控制 + 领域专家验证可达到 79.7% F1，远超通用方案（GPT-5.2 Pro 仅 46.6%）。

---

## 4. 多智能体协作模型：ClawdLab 对抗式批判 + Nested SubGraph

### 4.1 架构选型：DF + ClawdLab + Nested SubGraph (三位一体)

本系统采用 **三层融合架构**：

| 层级 | 来源 | 角色 | 核心机制 |
|------|------|------|---------|
| **底座层** | DeerFlow | — | Sandbox、SubagentExecutor、Tools、Middleware、Checkpointer |
| **协作协议层** | ClawdLab (arXiv 2602.19810) | PI、Critic、Meta-Judge | 对抗式批判前置、四权分立、角色门控、计算验证接地 |
| **工程结构层** | LangGraph Nested SubGraph | Parent Graph + 2 SubGraphs | State 隔离、命名空间隔离、独立编译、失败隔离 |

**选型理由**: 纯粹的 Supervisor 模式（如 CrewAI、competitor-hunter）在架构层面无法与同类项目拉开差距。ClawdLab 的对抗式批判协议 + 角色门控治理是 2026 年前沿论文中验证过的差异化机制，而 Nested SubGraph 提供了 LangGraph 原生的工程落地支撑。

### 4.2 整体架构：双层 SubGraph + 对抗式验证核心

```
┌──────────────────────────────────────────────────────────────┐
│                      Parent Graph                             │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │         Research SubGraph (独立编译, 独立 State)        │    │
│  │                                                       │    │
│  │  ┌──────────────────────────────────────────────┐     │    │
│  │  │         ClawdLab 对抗式批判协议 (内嵌)          │     │    │
│  │  │                                              │     │    │
│  │  │  PI Agent (首席研究员, SubGraph Supervisor)     │     │    │
│  │  │    │                                         │     │    │
│  │  │    ├──→ Scout A (规格+价格)  ──┐               │     │    │
│  │  │    ├──→ Scout B (口碑+评测)  ──┤ Send API 并行  │     │    │
│  │  │    └──→ Scout C (市场+供应链) ──┘               │     │    │
│  │  │         │                                     │     │    │
│  │  │         ▼ (采集结果汇总到 workspace JSON)        │     │    │
│  │  │         │                                     │     │    │
│  │  │    ┌────▼──────────────────────────┐          │     │    │
│  │  │    │  Critic Agent (对抗式质疑)      │          │     │    │
│  │  │    │  - 在合成/投票之前提出质疑       │          │     │    │
│  │  │    │  - 每条质疑必须附带证据          │          │     │    │
│  │  │    │  - 不能自行采集数据 (角色门控)    │          │     │    │
│  │  │    └────┬──────────────────────────┘          │     │    │
│  │  │         │                                     │     │    │
│  │  │    ┌────▼──────────────────────────┐          │     │    │
│  │  │    │ [条件路由]                      │          │     │    │
│  │  │    │ issues + round < 2 → Scouts   │          │     │    │
│  │  │    │ clean → Meta-Judge            │          │     │    │
│  │  │    └────┬──────────────────────────┘          │     │    │
│  │  │         │                                     │     │    │
│  │  │    ┌────▼──────────────────────────┐          │     │    │
│  │  │    │  Meta-Judge Agent (独立裁决)    │          │     │    │
│  │  │    │  - 只看证据链, 不参与采集/分析   │          │     │    │
│  │  │    │  - 裁决基于计算工具输出          │          │     │    │
│  │  │    │  - 输出结构化裁决书             │          │     │    │
│  │  │    └────┬──────────────────────────┘          │     │    │
│  │  │         │                                     │     │    │
│  │  │         ▼                                     │     │    │
│  │  │    PI 最终审核 (可推翻裁决, 必须记录审计日志)    │     │    │
│  │  │         │                                     │     │    │
│  │  │         ▼                                     │     │    │
│  │  │    ValidatedBrief (State Mapping 输出)         │     │    │
│  │  └──────────────────────────────────────────────┘     │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │ (State Mapping: 只传精炼结果)        │
│  ┌──────────────────────▼───────────────────────────────┐    │
│  │        Analysis SubGraph (独立编译, 独立 State)        │    │
│  │                                                       │    │
│  │  Analyst Lead (Analysis Supervisor)                    │    │
│  │    │                                                  │    │
│  │    ├──→ Synthesizer (多维对比 + 趋势 + SWOT + 建议)     │    │
│  │    │      │                                           │    │
│  │    │      ▼                                           │    │
│  │    └──→ Internal Reviewer (内部质量审查)                │    │
│  │           │                                           │    │
│  │           ▼                                           │    │
│  │    SynthesisReport (State Mapping 输出)                │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                    │
│              ┌──────────▼──────────┐                          │
│              │     HITL Gate       │  (Parent 层)              │
│              │ LangGraph interrupt()│                          │
│              └──────────┬──────────┘                          │
│              ┌──────────▼──────────┐                          │
│              │  Report Composer    │  (Parent 层)              │
│              └─────────────────────┘                          │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  角色门控 (DF Config 层 + PermissionGuard 中间件)       │    │
│  │  PI:     can_plan, can_override_critic(需审计日志)     │    │
│  │  Scout:  can_search, can_fetch, can_respond_to_critic │    │
│  │  Critic: can_challenge(必须附证据), cannot_collect     │    │
│  │  Judge:  can_adjudicate, cannot_collect, cannot_synth │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**关键设计决策**:

| 决策 | 选择 | 理由 |
|------|------|------|
| SubGraph 粒度 | 2 个 (Research + Analysis) | 5-15 节点/SubGraph 最佳实践；两层不超 3 层限制 |
| State 通信 | State Mapping (`state_in`/`state_out`) | 生产级隔离，子图不依赖父图字段 |
| Checkpoint | 父子图共享同一 PostgresSaver | 保证回退一致性 |
| 失败传播 | 状态字段上浮 (`error` 字段 + 条件边降级) | 子图异常不冒泡到父图 |
| 命名空间 | 每 SubGraph 独立 `checkpoint_ns` | 防并行子图状态碰撞 |

### 4.3 七角色定义 (含 ClawdLab 四权分立)

#### 4.3.1 PI Agent (首席研究员 — Research SubGraph Supervisor)

```yaml
name: pi_agent
pattern: SubGraph Supervisor + ClawdLab PI Role
location: Research SubGraph 内部
description: >
  研究团队的主管。负责任务拆解、Scout 调度、Critic 质疑的最终仲裁、
  Meta-Judge 裁决的审核批准。拥有最高权限但需要审计日志。
system_prompt: |
  你是一位首席研究分析师 (Principal Investigator)。你的职责：

  1. 任务规划: 将用户的分析需求拆解为 2-4 个并行的数据采集子任务
  2. 团队调度: 通过 Send API 将子任务分发给 Scout 团队
  3. 结果汇总: 收集 Scout 采集结果，写入 workspace JSON
  4. 质疑仲裁: 当 Critic 提出质疑后，审核质疑的合理性
  5. 裁决审核: 审核 Meta-Judge 的裁决书，可批准或推翻
     - 推翻裁决时必须在审计日志中记录理由
     - 推翻后的新指令需明确范围和预期

  权限边界:
  - 可以: 规划、调度、审核、推翻裁决 (需审计日志)
  - 不可以: 直接采集数据、直接修改 Critic 质疑、代替 Judge 裁决

  输出格式:
  {
    "phase": "planning|dispatching|reviewing|adjudicating",
    "scout_tasks": [...],
    "review_decision": "approve|override",
    "override_reason": "推翻理由 (如适用)",
    "audit_trail": ["关键决策记录"]
  }
model: claude-opus-4-7
thinking_enabled: true
tools: []  # PI 只做规划与决策，不直接采集
max_turns: 15
role_gate:
  permissions: [can_plan, can_dispatch, can_override_critic]
  constraints: [override_requires_audit_log, cannot_collect_data]
```

#### 4.3.2 Data Scout (数据侦察员 — Worker)

```yaml
name: data_scout
pattern: Worker Agent (被 PI 通过 Send API 并行调度)
location: Research SubGraph 内部
description: >
  专业的数据采集 Agent。根据 PI 下发的任务描述从多个在线数据源采集商品信息。
  支持并行部署 2-4 个实例。当 Critic 提出质疑时，执行定向补采。
system_prompt: |
  你是一位专业的数据侦察员。你的职责:

  工作原则:
  1. 多源交叉验证: 同一数据点从 2+ 来源确认
  2. 标注来源: 每条数据附带来源 URL 和采集时间
  3. 区分事实与观点: 明确标注客观 vs 主观
  4. 结构化输出: JSON 格式组织
  5. 数据质量自评: 标注置信度 (high/medium/low)
  6. 回应质疑: 收到 Critic 的 Challenge 后，定向补采并返回 Rebuttal

  权限边界:
  - 可以: 搜索、抓取网页、读取文件、回应 Critic 质疑
  - 不可以: 质疑其他 Scout 的数据、裁决争议、直接生成最终报告

  输出格式:
  {
    "scout_id": "scout_1",
    "dimension": "规格与价格",
    "data_points": [
      {
        "category": "规格参数|价格|口碑|市场|供应链",
        "attribute": "属性名称",
        "value": "属性值",
        "sources": [{"url": "...", "date": "2026-05-14"}],
        "confidence": "high|medium|low",
        "fact_or_opinion": "fact|opinion"
      }
    ],
    "collection_summary": "采集概况",
    "gaps": ["未采集到的数据点"],
    "self_assessment_score": 0.85
  }
model: inherit
tools: [web_search, web_fetch, firecrawl, python, write_file]
skills: [data-normalizer, sentiment-analyzer]
max_turns: 30
timeout_seconds: 600
role_gate:
  permissions: [can_search, can_fetch, can_scrape, can_compute, can_respond_to_critic]
  constraints: [cannot_challenge, cannot_adjudicate, cannot_synthesize]
```

#### 4.3.3 Critic Agent (对抗式批判员 — ClawdLab 核心角色)

```yaml
name: critic_agent
pattern: ClawdLab Adversarial Critic (对抗式批判)
location: Research SubGraph 内部 (在 Scouts 采集完成后、Meta-Judge 裁决前)
description: >
  对抗式批判专家。在数据进入合成阶段之前，主动寻找矛盾、逻辑漏洞和低质量数据。
  这是 ClawdLab 的核心创新——批判发生在投票/决策之前，而非事后审查。
system_prompt: |
  你是一位严谨的对抗式数据审查员 (Adversarial Critic)。你的职责:

  1. 主动寻找矛盾:
     - 比对多个 Scout 对同一数据点的采集结果
     - 发现数值不一致、来源冲突、时效性问题
  2. 识别逻辑漏洞:
     - 数据是否符合行业常识和物理规律
     - 是否存在因果倒置、相关性不等于因果等谬误
  3. 质疑来源质量:
     - 来源权威性: 官方 > 权威媒体 > 自媒体 > 论坛 > 未知
     - 来源时效性: <1月 > <3月 > <6月 > <1年
  4. 提出结构化质疑 (Challenge):
     - 每条质疑必须附带: 证据 (引用具体数据)、严重程度、建议的补采方向

  权限边界:
  - 可以: 提出质疑 (必须附证据)、建议补采方向
  - 不可以: 自行采集数据、裁决争议、修改 Scout 数据

  Challenge 输出格式:
  {
    "critic_id": "critic_round_1",
    "challenges": [
      {
        "challenge_id": "CH-001",
        "data_point": "iPhone 17 起售价",
        "conflicting_sources": [
          {"source": "来源A", "value": "$999", "authority": "medium"},
          {"source": "来源B", "value": "$1099", "authority": "high"}
        ],
        "evidence": "来源B 为 Apple 官网，权威性高于第三方 reseller 来源A",
        "severity": "critical|major|minor",
        "suggested_recollection": {
          "target_scout": "scout_1",
          "search_keywords": ["iPhone 17 official price", "Apple Store price"],
          "priority_sources": ["apple.com", "authorized retailers"]
        }
      }
    ],
    "overall_critique_summary": "本次审查的整体评价",
    "recommended_action": "recollect|proceed_to_judge"
  }
model: claude-opus-4-7
thinking_enabled: true
tools: [read_file, python]  # 可读取 Scout 结果和运行验证脚本，但不能搜索
max_turns: 30
role_gate:
  permissions: [can_challenge, can_read_data]
  constraints: [cannot_collect_data, cannot_adjudicate, cannot_synthesize,
                challenge_requires_evidence]
```

#### 4.3.4 Meta-Judge Agent (独立裁决员 — ClawdLab 核心角色)

```yaml
name: meta_judge_agent
pattern: ClawdLab Meta-Judge (独立裁决)
location: Research SubGraph 内部 (在 Critic 质疑 + Scout 补采完成后)
description: >
  独立裁决者。对 Critic 提出的质疑和 Scout 的回应进行最终裁决。
  核心原则: 只看证据，不参与数据采集或分析，保持裁决独立性。
system_prompt: |
  你是一位独立的证据裁决员 (Meta-Judge)。你的职责:

  1. 审阅质疑与回应:
     - Critic 的 Challenge (质疑 + 证据)
     - Scout 的 Rebuttal (补采数据 + 回应)
  2. 证据评估:
     - 来源权威性权重: 官方(0.95) > 授权经销商(0.85) > 科技媒体(0.80) > 第三方(0.60) > 论坛(0.45)
     - 多源一致性: 3+来源一致(0.95) > 2来源一致(0.80) > 单一来源(0.50)
     - 时效性: <1月(1.0) > <3月(0.85) > <6月(0.65) > <1年(0.40)
  3. 裁决:
     - 对每个争议点给出裁决结论和置信度
     - 裁决必须引用具体证据 (计算工具输出、API 返回数据等)
     - 不基于"多数意见"裁决，只看证据质量
  4. 生成裁决书:
     - 每个争议的裁决结论
     - 不可解决的争议标记为 unresolved
     - 整体数据质量评分

  权限边界:
  - 可以: 裁决争议、评估证据质量、给出置信度评分
  - 不可以: 采集数据、提出新的质疑 (那是 Critic 的工作)、直接修改 Scout 数据

  裁决书输出格式:
  {
    "judge_id": "judge_round_1",
    "rulings": [
      {
        "challenge_id": "CH-001",
        "verdict": "sustained|overruled|compromised",
        "adopted_value": "$999",
        "confidence": 0.93,
        "evidence_basis": [
          "Apple 官网证实 $999 (权威性 0.95)",
          "2家授权经销商证实 $999 ± $1 (权威性 0.85)",
          "来源B的 $1099 可能为含税价格"
        ],
        "unresolved": false
      }
    ],
    "overall_quality_score": 0.88,
    "unresolved_issues": [],
    "judge_summary": "裁决总结"
  }
model: claude-opus-4-7
thinking_enabled: true
tools: [read_file, python]  # 可读取数据和运行验证脚本，不搜索
max_turns: 25
role_gate:
  permissions: [can_adjudicate, can_read_data, can_run_verification]
  constraints: [cannot_collect_data, cannot_challenge, cannot_synthesize,
                rulings_must_cite_evidence, cannot_vote_on_consensus]
```

#### 4.3.5 Analyst Lead (分析主管 — Analysis SubGraph Supervisor)

```yaml
name: analyst_lead
pattern: SubGraph Supervisor
location: Analysis SubGraph 内部
description: >
  分析团队的主管。接收 Research SubGraph 输出的 ValidatedBrief，
  调度 Synthesizer 进行多维分析，再由 Internal Reviewer 审查后输出 SynthesisReport。
system_prompt: |
  你是一位资深分析主管。你的职责:
  1. 接收 ValidatedBrief，确认数据质量达标
  2. 调度 Synthesizer 进行多维对比分析
  3. 调度 Internal Reviewer 进行内部质量审查
  4. 审核最终 SynthesisReport

  权限边界:
  - 可以: 调度分析流程、审核分析质量
  - 不可以: 修改验证数据、推翻 Meta-Judge 裁决
model: claude-opus-4-7
thinking_enabled: true
tools: [read_file]
max_turns: 15
```

#### 4.3.6 Synthesizer (综合分析员)

```yaml
name: synthesizer
location: Analysis SubGraph 内部
description: >
  多维度分析专家。将验证后的数据转化为深度洞察。
system_prompt: |
  基于 ValidatedBrief 中的验证数据，进行:
  1. 多维对比分析: 规格对比矩阵、价格/价值分析、用户体验对比、市场定位
  2. 趋势识别: 技术演进、定价变化、消费者偏好迁移
  3. SWOT 分析: 每个产品独立
  4. 战略建议: 按优先级排列，附带置信度
model: claude-opus-4-7
thinking_enabled: true
tools: [read_file, python, write_file]
skills: [spec-comparator, price-elasticity, market-share-calc, trend-detector]
max_turns: 50
```

#### 4.3.7 Internal Reviewer (内部审查员)

```yaml
name: internal_reviewer
location: Analysis SubGraph 内部 (Synthesizer 之后)
description: >
  分析质量内部审查。在分析结果进入 HITL Gate 之前进行最后一轮质量把关。
  关注分析的逻辑完整性、数据引用准确性、建议的可行性。
system_prompt: |
  审查 Synthesizer 的输出:
  1. 所有数据引用是否来自 ValidatedBrief (非捏造)
  2. 分析逻辑是否自洽
  3. SWOT 是否有证据支撑
  4. 战略建议是否可执行
  输出: 通过 / 需修改 (具体修改点)
model: inherit
tools: [read_file]
max_turns: 15
```

#### 4.3.8 Report Composer (报告撰写员 — Parent Graph 层)

```yaml
name: report_composer
location: Parent Graph 层 (HITL Gate 审批通过后)
description: >
  专业报告撰写。将 SynthesisReport 转化为结构化 Markdown 报告 + 可视化图表。
system_prompt: |
  报告结构: 执行摘要 → 分析范围 → 竞品概览 → 深度对比 → 市场格局 → SWOT → 战略建议 → 附录
  使用 Python (matplotlib/plotly) 生成: 雷达图、趋势图、饼图、SWOT矩阵图
model: inherit
tools: [write_file, python, bash, present_files]
max_turns: 40
```

### 4.4 角色模型配置总表

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

### 4.5 四个协作协议

#### 协议 1: 任务分发与采集 (PI → Send API Fan-out → Scouts)

```
PI Agent 拆解任务 → 生成 N 个 scout_task
  → Send API 并行 Fan-out → [Scout A, Scout B, Scout C]
    → 各 Scout 独立采集 → 返回结构化 JSON
      → PI 汇总 → 写入 workspace JSON → 触发 Critic
```

#### 协议 2: 对抗式批判协议 (ClawdLab 核心 — Critic → Scouts ⇄ Meta-Judge)

```
┌─────────────────────────────────────────────────────┐
│              ClawdLab 对抗式批判协议                    │
│                                                      │
│  PI 汇总数据完成                                       │
│       │                                              │
│       ▼                                              │
│  Critic 审查 → 生成 Challenge[] (每条必须附证据)        │
│       │                                              │
│       ├── 无问题 → 直接进入 Meta-Judge                  │
│       │                                              │
│       ▼ (有问题)                                      │
│  Critic 指定目标 Scout + 补采方向                       │
│       │                                              │
│       ▼                                              │
│  Scout 定向补采 → 返回 Rebuttal (附带新证据)            │
│       │                                              │
│       ▼                                              │
│  Critic 重新评估                                       │
│       │                                              │
│       ├── 仍有问题 + round < 2 → 继续循环               │
│       ├── 不可修复 → 标记为 unresolved                  │
│       │                                              │
│       ▼                                              │
│  Meta-Judge 独立裁决                                   │
│       │                                              │
│       ▼                                              │
│  PI 审核裁决书 → 批准 / 推翻 (需审计日志)                │
│       │                                              │
│       ▼                                              │
│  ValidatedBrief → State Mapping 到 Parent Graph       │
└─────────────────────────────────────────────────────┘
```

**为什么 Critic 和 Meta-Judge 必须分离**:
- Critic 是"检察官"——主动找问题，天然有倾向性
- Meta-Judge 是"法官"——被动裁决，只看证据不站队
- 同一 Agent 既当检察官又当法官 → 无法保证裁决公正性
- 这直接解决了我们 v1.0 中 Cross-Validator "自己质疑自己裁决"的结构性问题

#### 协议 3: SubGraph 间通信 (State Mapping)

```
Research SubGraph 输出:
  ChildState (私有)                ParentState (接收)
  ┌──────────────────┐            ┌──────────────────────┐
  │ scout_data_json   │            │ validated_brief       │
  │ challenge_history │ ──映射──→  │ quality_score         │
  │ judge_rulings     │            │ unresolved_issues     │
  │ quality_score     │            │ data_summary          │
  │ error (如有)      │            │ research_error        │
  └──────────────────┘            └──────────────────────┘

Analysis SubGraph 输入 (反向映射):
  ParentState                     ChildState (私有)
  ┌──────────────────────┐        ┌──────────────────────┐
  │ validated_brief       │ ──→   │ input_brief            │
  │ quality_score         │        │ quality_threshold      │
  │ unresolved_issues     │        │ known_gaps             │
  └──────────────────────┘        └──────────────────────┘
```

**关键规则**:
- State Mapping 函数是纯函数 (输入 → 输出，无副作用)
- 子图 State 只包含自己需要的字段 (严格投影，不依赖父图其他字段)
- 子图内部异常通过 `error` 字段上浮到父图 (父图通过条件边降级处理)
- 父子图共享同一 `PostgresSaver` 实例 (保证 checkpoint 一致性)

#### 协议 4: 人类审批门 (HITL Gate — Parent Graph 层)

```
Analysis SubGraph 输出 SynthesisReport
      │
      ▼
  HITL Gate (interrupt_before node, Parent Graph 层)
      │
      ├── 批准 → Command(resume={"action": "approve"}) → Report Composer
      ├── 修改 → Command(resume={"action": "modify", "changes": {...}}) → Analysis SubGraph
      └── 重来 → Command(resume={"action": "replan"}) → Research SubGraph

```

---

## 5. LangGraph 工作流编排设计：Nested SubGraph + 角色门控

### 5.1 核心设计原则：DF 底座 + Nested SubGraph + ClawdLab 协议

```
┌──────────────────────────────────────────────────────────┐
│                   LangGraph 2.0                           │
│                                                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Parent Graph (顶层编排)                          │    │
│  │                                                  │    │
│  │  ┌──────────────────┐   ┌──────────────────┐    │    │
│  │  │ Research SubGraph │   │ Analysis SubGraph │    │    │
│  │  │ (独立编译+独立State)│   │ (独立编译+独立State)│    │    │
│  │  │                   │   │                   │    │    │
│  │  │ PI → Scouts       │   │ Analyst Lead →    │    │    │
│  │  │   → Critic        │   │   Synthesizer →   │    │    │
│  │  │   → Meta-Judge    │   │   Int. Reviewer   │    │    │
│  │  │   → PI (审核)     │   │                   │    │    │
│  │  │                   │   │                   │    │    │
│  │  │ State Mapping     │   │ State Mapping     │    │    │
│  │  │ (state_in/out)    │   │ (state_in/out)    │    │    │
│  │  └────────┬─────────┘   └────────┬─────────┘    │    │
│  │           │                      │               │    │
│  │           ▼                      ▼               │    │
│  │  ┌──────────────────────────────────────────┐   │    │
│  │  │         HITL Gate (Parent 层)              │   │    │
│  │  └──────────────────────────────────────────┘   │    │
│  │  ┌──────────────────────────────────────────┐   │    │
│  │  │       Report Composer (Parent 层)          │   │    │
│  │  └──────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │  DeerFlow 底座 (每个节点 = SubagentExecutor)       │    │
│  │  - Sandbox · Tools · Middlewares · Memory         │    │
│  │  - Checkpointer (PostgresSaver, 父子图共享)        │    │
│  │  - Config (collaboration 段, 热加载)               │    │
│  └─────────────────────────────────────────────────┘    │
│                                                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ClawdLab 协议层 (嵌入 Research SubGraph)          │    │
│  │  - 对抗式批判前置 (Critic BEFORE Judge)            │    │
│  │  - 四权分立 (PI/Critic/Judge/Scout 角色门控)       │    │
│  │  - 计算验证接地 (Evidence-based, not consensus)    │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

**与 v1.0 架构的关键区别**:

| 维度 | v1.0 (Supervisor + Swarm) | v2.0 (Nested SubGraph + ClawdLab) |
|------|--------------------------|-----------------------------------|
| 图结构 | 单层 StateGraph, 7 节点 | 双层: Parent Graph + 2 SubGraphs |
| 验证机制 | Cross-Validator 单节点 (自质疑自裁决) | Critic + Meta-Judge 双节点 (检察官/法官分离) |
| 团队隔离 | 无 (所有节点在同一图) | SubGraph 独立 State + 独立 Checkpoint |
| 状态通信 | 共享 State (隐式) | State Mapping (`state_in`/`state_out`, 显式) |
| 权限控制 | Prompt 约束 (软) | 角色门控 + PermissionGuard 中间件 (硬) |
| 失败隔离 | 节点级 try/except | SubGraph 级 `error` 字段上浮 + 条件边降级 |

### 5.2 三层状态定义

#### Parent Graph State (CollaborationState)

```python
class CollaborationState(TypedDict):
    """父图状态 — 只包含跨团队共享的精炼结果，不包含子图内部细节"""
    # 消息与基础
    messages: Annotated[list[BaseMessage], add_messages]
    user_request: str
    current_phase: str  # researching|analyzing|reviewing|composing|failed

    # Research SubGraph 输出 (通过 state_out 映射)
    validated_brief: dict | None       # 验证后的数据摘要
    research_quality_score: float | None
    unresolved_issues: list[dict]
    research_error: str | None         # 子图异常上浮

    # Analysis SubGraph 输出 (通过 state_out 映射)
    synthesis_report: dict | None
    analysis_error: str | None

    # HITL
    hitl_status: str
    hitl_feedback: str | None
    hitl_timestamp: str | None

    # 最终输出
    report_artifacts: list[str]
    final_report: str | None

    # 审计
    execution_trace: list[dict]
    error_log: list[str]

    # DeerFlow 透传
    sandbox: dict | None
    thread_data: dict | None
```

#### Research SubGraph State (独立编译)

```python
class ResearchSubGraphState(TypedDict):
    """Research SubGraph 私有状态 — 父图不可见内部细节"""
    # 输入 (从 Parent State 映射)
    user_request: str

    # PI 规划
    task_plan: list[dict]
    active_scout_count: int

    # Scout 采集 (add reducer 累加)
    scout_results: Annotated[list[ScoutResult], add]
    collection_round: int

    # ClawdLab 对抗式批判
    critic_challenges: list[dict]      # Critic 提出的质疑列表
    scout_rebuttals: list[dict]        # Scout 对质疑的回应
    judge_rulings: list[dict]          # Meta-Judge 裁决
    debate_round: int                  # 当前质疑轮次 (0-2)
    pi_override_log: list[dict]        # PI 推翻裁决的审计日志

    # 输出 (映射到 Parent State)
    validated_brief: dict | None
    research_quality_score: float | None
    unresolved_issues: list[dict]

    # 错误处理 (上浮到父图)
    error: str | None

    # DeerFlow 透传
    sandbox: dict | None
    thread_data: dict | None
```

#### Analysis SubGraph State (独立编译)

```python
class AnalysisSubGraphState(TypedDict):
    """Analysis SubGraph 私有状态 — 父图不可见内部细节"""
    # 输入 (从 Parent State 映射)
    validated_brief: dict | None
    research_quality_score: float | None
    unresolved_issues: list[dict]

    # Synthesizer 输出
    comparison_matrix: dict | None
    swot_analysis: dict | None
    trends: list[dict]
    strategic_recommendations: list[str]

    # Internal Reviewer
    review_passed: bool
    review_comments: list[str]

    # 输出 (映射到 Parent State)
    synthesis_report: dict | None

    # 错误处理
    error: str | None

    # DeerFlow 透传
    sandbox: dict | None
    thread_data: dict | None
```

### 5.3 Nested SubGraph 图结构定义

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import interrupt, Command, Send

# ============================================================
# Step 1: 构建 Research SubGraph (独立编译)
# ============================================================
def build_research_subgraph() -> CompiledStateGraph:
    research = StateGraph(ResearchSubGraphState)

    research.add_node("pi_agent", pi_agent_node)
    research.add_node("data_scout", data_scout_node)
    research.add_node("critic_agent", critic_agent_node)
    research.add_node("meta_judge", meta_judge_node)
    research.add_node("pi_review", pi_review_node)   # PI 审核裁决
    research.add_node("error_handler", error_handler_node)

    research.set_entry_point("pi_agent")

    # PI → Send API 并行 Fan-out Scouts
    research.add_conditional_edges(
        "pi_agent", fan_out_to_scouts, path_map=["data_scout"]
    )
    research.add_edge("data_scout", "pi_agent")

    # PI 汇总 → Critic
    research.add_conditional_edges(
        "pi_agent", route_to_critic,
        {"critique": "critic_agent", "skip_to_judge": "meta_judge"}
    )

    # Critic → 补采 or Meta-Judge
    research.add_conditional_edges(
        "critic_agent", route_after_critique,
        {"recollect": "data_scout", "adjudicate": "meta_judge"}
    )

    # Meta-Judge → PI 审核
    research.add_edge("meta_judge", "pi_review")

    # PI 审核 → output or override loop
    research.add_conditional_edges(
        "pi_review", route_after_pi_review,
        {"output": END, "override": "pi_agent"}  # 推翻裁决 → 重新规划
    )
    research.add_edge("error_handler", END)

    return research.compile()


# ============================================================
# Step 2: 构建 Analysis SubGraph (独立编译)
# ============================================================
def build_analysis_subgraph() -> CompiledStateGraph:
    analysis = StateGraph(AnalysisSubGraphState)

    analysis.add_node("analyst_lead", analyst_lead_node)
    analysis.add_node("synthesizer", synthesizer_node)
    analysis.add_node("internal_reviewer", internal_reviewer_node)

    analysis.set_entry_point("analyst_lead")
    analysis.add_edge("analyst_lead", "synthesizer")
    analysis.add_edge("synthesizer", "internal_reviewer")

    # Reviewer → pass or revise
    analysis.add_conditional_edges(
        "internal_reviewer", route_after_review,
        {"output": END, "revise": "synthesizer"}
    )

    return analysis.compile()


# ============================================================
# Step 3: 构建 Parent Graph (挂载两个 SubGraph)
# ============================================================
def build_collaboration_graph() -> StateGraph:
    parent = StateGraph(CollaborationState)

    research_subgraph = build_research_subgraph()
    analysis_subgraph = build_analysis_subgraph()

    # --- State Mapping 函数 ---
    def map_parent_to_research(parent_state: CollaborationState) -> dict:
        return {"user_request": parent_state["user_request"]}

    def map_research_to_parent(
        child_state: ResearchSubGraphState, parent_state: CollaborationState
    ) -> dict:
        return {
            "validated_brief": child_state.get("validated_brief"),
            "research_quality_score": child_state.get("research_quality_score"),
            "unresolved_issues": child_state.get("unresolved_issues", []),
            "research_error": child_state.get("error"),
        }

    def map_parent_to_analysis(parent_state: CollaborationState) -> dict:
        return {
            "validated_brief": parent_state.get("validated_brief"),
            "research_quality_score": parent_state.get("research_quality_score"),
            "unresolved_issues": parent_state.get("unresolved_issues", []),
        }

    def map_analysis_to_parent(
        child_state: AnalysisSubGraphState, parent_state: CollaborationState
    ) -> dict:
        return {
            "synthesis_report": child_state.get("synthesis_report"),
            "analysis_error": child_state.get("error"),
        }

    # --- 挂载 SubGraph ---
    parent.add_node(
        "research_team",
        research_subgraph,
        state_in=map_parent_to_research,
        state_out=map_research_to_parent,
    )
    parent.add_node(
        "analysis_team",
        analysis_subgraph,
        state_in=map_parent_to_analysis,
        state_out=map_analysis_to_parent,
    )

    # --- Parent 层节点 ---
    parent.add_node("hitl_gate", hitl_gate_node)
    parent.add_node("report_composer", report_composer_node)
    parent.add_node("error_handler", error_handler_node)

    # --- Parent 层路由 ---
    parent.set_entry_point("research_team")

    # Research → Analysis (if no error) or Error Handler
    parent.add_conditional_edges(
        "research_team",
        lambda s: "error_handler" if s.get("research_error") else "analysis_team",
        {"analysis_team": "analysis_team", "error_handler": "error_handler"}
    )

    # Analysis → HITL Gate (if no error) or Error Handler
    parent.add_conditional_edges(
        "analysis_team",
        lambda s: "error_handler" if s.get("analysis_error") else "hitl_gate",
        {"hitl_gate": "hitl_gate", "error_handler": "error_handler"}
    )

    # HITL → Report Composer / Research / Analysis
    parent.add_conditional_edges(
        "hitl_gate",
        route_after_hitl,
        {
            "compose": "report_composer",
            "replan": "research_team",
            "resynthesize": "analysis_team",
        }
    )

    parent.add_edge("report_composer", END)
    parent.add_edge("error_handler", END)

    # 父子图共享同一 checkpointer
    checkpointer = PostgresSaver.from_conn_string(os.getenv("POSTGRES_URI"))
    return parent.compile(checkpointer=checkpointer)
```

### 5.4 LangGraph Send API — 并行 Fan-out 实现

这是 2026 年 LangGraph 推荐的多 Agent 并行执行方式：

```python
from langgraph.types import Send

def fan_out_to_scouts(state: CollaborationState) -> list[Send]:
    """Orchestrator 规划完成后，使用 Send API 并行启动多个 Data Scouts"""
    task_plan = state.get("task_plan", [])
    if not task_plan:
        return []  # 无采集任务，跳过

    sends = []
    for i, task in enumerate(task_plan):
        sends.append(
            Send(
                node="data_scout",
                arg={
                    "task": task,
                    "scout_index": i,
                    "collection_round": state.get("collection_round", 0),
                }
            )
        )
    return sends
```

### 5.5 HITL Gate — LangGraph 2.0 interrupt_before 模式

基于 2026 年 LangGraph 2.0 的最新实践：

```python
def hitl_gate_node(state: CollaborationState) -> dict:
    """
    人类审批门 — 使用 LangGraph 2.0 interrupt() + Command(resume=...)

    重要设计决策：
    - 使用 interrupt_before 而非 interrupt_after
      → 审批发生在进入节点之前，确保人类批准后动作才执行
    - 每次只在 interrupt() 中放一个审批点
      → 避免多个 interrupt() 的重新排序问题
    - 附加 created_at 时间戳
      → 恢复时可以检测 stale state
    """
    from langgraph.types import interrupt
    from datetime import datetime, timezone

    # 构建审批包
    review_package = {
        "type": "hitl_review",
        "phase": "post_synthesis",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_summary": {
            "total_data_points": len(state["scout_results"]),
            "overall_quality": state["validation_report"]["overall_score"],
            "key_findings": state["synthesis_result"]["strategic_recommendations"][:5],
            "unresolved_issues": len(state.get("unresolved_issues", [])),
        },
        "preview": state["synthesis_result"],  # 完整的分析结果
    }

    # interrupt() 暂停图执行
    human_decision = interrupt(review_package)

    # 恢复后的处理
    action = human_decision.get("action", "approve")

    if action == "approve":
        return {
            "hitl_status": "approved",
            "hitl_feedback": human_decision.get("comments", ""),
            "current_phase": "composing",
        }
    elif action == "modify":
        return {
            "hitl_status": "modified",
            "hitl_feedback": human_decision.get("changes", ""),
            "current_phase": "synthesizing",  # 重新合成
        }
    else:  # reject
        return {
            "hitl_status": "rejected",
            "hitl_feedback": human_decision.get("reason", ""),
            "current_phase": "planning",  # 重新规划
        }


# === Gateway API 端：恢复执行 ===
# POST /api/collaboration/threads/{thread_id}/resume
async def resume_after_hitl(thread_id: str, decision: dict):
    """接收人类决策，恢复图执行"""
    graph = build_collaboration_graph()

    # 检查 stale state (可选)
    current_state = graph.get_state(config={"configurable": {"thread_id": thread_id}})
    hitl_created = current_state.values.get("hitl_timestamp")
    if hitl_created and is_stale(hitl_created, ttl_minutes=30):
        raise StaleStateError("HITL review has expired. Please restart the analysis.")

    async for event in graph.astream(
        Command(resume=decision),
        config={"configurable": {"thread_id": thread_id}},
        stream_mode=["custom", "values"],
    ):
        yield event
```

### 5.6 条件路由逻辑

```python
def route_after_planning(state: CollaborationState) -> str:
    """Orchestrator 规划完成后决定下一步"""
    task_plan = state.get("task_plan", [])
    if not task_plan:
        return "validate"  # 无需采集，直接进入验证
    return "collect"

def route_after_collection(state: CollaborationState) -> str:
    """Orchestrator 汇总 Scout 结果后决定下一步"""
    collection_round = state.get("collection_round", 0)
    max_rounds = 3

    if collection_round >= max_rounds:
        return "validate"

    scout_results = state.get("scout_results", [])
    all_high_confidence = all(
        r.get("confidence_self_assessment", 0) > 0.7
        for r in scout_results
    )
    return "validate" if all_high_confidence else "recollect"

def route_after_validation(state: CollaborationState) -> str:
    """Cross-Validator 审查后决定下一步"""
    validation = state.get("validation_report", {})
    debate_round = state.get("debate_round", 0)

    if validation.get("requires_recollection") and debate_round < 2:
        return "recollect"
    elif validation.get("overall_score", 0) < 0.4:
        return "failed"
    return "synthesize"

def route_after_hitl(state: CollaborationState) -> str:
    """人类审批后决定下一步"""
    status = state.get("hitl_status", "approve")
    return {
        "approved": "compose",
        "modified": "resynthesize",
        "rejected": "replan",
    }.get(status, "compose")
```

### 5.7 流式事件设计

通过 `stream_mode=["custom", "values"]` 向前端推送实时进度：

```python
COLLABORATION_EVENTS = {
    # 阶段事件
    "phase:change":        "阶段切换 {from_phase} → {to_phase}",
    # Scout 事件
    "scout:start":         "Scout {scout_id} 开始采集 [{dimension}]",
    "scout:progress":      "Scout {scout_id} 已采集 {count} 个数据点",
    "scout:complete":      "Scout {scout_id} 完成，置信度 {score}",
    # 验证事件
    "validation:issue":    "发现矛盾: {description}",
    "validation:debate":   "第 {round} 轮质疑-回应",
    "validation:complete": "验证完成，整体质量 {score}",
    # HITL 事件
    "hitl:required":       "需要人类审批 {review_package}",
    # 报告事件
    "report:section":      "正在生成 {section_name}",
    "report:complete":     "报告生成完成 {artifacts}",
}

# 在节点中使用 StreamWriter
def data_scout_node(state: CollaborationState) -> dict:
    writer = get_stream_writer()
    for task in tasks:
        writer({"event": "scout:start", "scout_id": task["id"], "dimension": task["dimension"]})
        result = scout.execute(task["instruction"])
        writer({"event": "scout:complete", "scout_id": task["id"], "data_points": len(result.data)})
    return {...}
```

---

### 5.8 角色门控治理 (Role-Gated Governance)

基于 ClawdLab 论文的角色门控设计，在 DF Config 层硬编码权限控制：

#### PermissionGuard 中间件

```python
from dataclasses import dataclass

@dataclass
class RolePermission:
    role: str
    allowed_actions: set[str]      # 允许的操作
    requires_audit: set[str]       # 需要审计日志的操作
    requires_evidence: set[str]    # 需要附带证据的操作

ROLE_PERMISSIONS: dict[str, RolePermission] = {
    "pi_agent": RolePermission(
        role="pi_agent",
        allowed_actions={"plan", "dispatch", "review", "override_critic"},
        requires_audit={"override_critic"},     # 推翻裁决必须记录
        requires_evidence=set(),
    ),
    "data_scout": RolePermission(
        role="data_scout",
        allowed_actions={"search", "fetch", "respond_to_critic"},
        requires_audit=set(),
        requires_evidence={"respond_to_critic"},  # 回应质疑必须附证据
    ),
    "critic_agent": RolePermission(
        role="critic_agent",
        allowed_actions={"challenge", "read_data"},
        requires_audit=set(),
        requires_evidence={"challenge"},           # 质疑必须附证据
    ),
    "meta_judge": RolePermission(
        role="meta_judge",
        allowed_actions={"adjudicate", "read_data", "run_verification"},
        requires_audit=set(),
        requires_evidence={"adjudicate"},           # 裁决必须引用证据
    ),
}

class PermissionGuardMiddleware(AgentMiddleware):
    """角色门控中间件 — 在每次工具调用前检查权限"""

    def before_tool_call(self, state, tool_call, runtime):
        agent_role = runtime.context.get("agent_role")
        if agent_role is None:
            return  # 非协作模式，跳过

        permissions = ROLE_PERMISSIONS.get(agent_role)
        if permissions is None:
            raise PermissionError(f"Unknown agent role: {agent_role}")

        action = tool_call.get("name")

        if action not in permissions.allowed_actions:
            raise PermissionError(
                f"Role '{agent_role}' is not allowed to perform '{action}'. "
                f"Allowed: {permissions.allowed_actions}"
            )

        if action in permissions.requires_evidence:
            # 验证工具调用是否附带了必要的证据参数
            if not _has_evidence(tool_call):
                raise PermissionError(
                    f"Role '{agent_role}' must provide evidence for '{action}'"
                )
```

#### 配置层角色门控 (config.yaml)

```yaml
collaboration:
  role_gates:
    enabled: true
    enforcement: "hard"  # hard = 拒绝执行; soft = 警告但允许

    roles:
      pi_agent:
        permissions: [plan, dispatch, review, override_critic]
        audit_actions: [override_critic]
        model: "claude-opus-4-7"

      data_scout:
        permissions: [search, fetch, respond_to_critic]
        evidence_required_for: [respond_to_critic]
        model: "inherit"
        max_parallel: 3

      critic_agent:
        permissions: [challenge, read_data]
        evidence_required_for: [challenge]
        model: "claude-opus-4-7"
        max_debate_rounds: 2

      meta_judge:
        permissions: [adjudicate, read_data, run_verification]
        evidence_required_for: [adjudicate]
        model: "claude-opus-4-7"

    # 门控违规处理
    violation_policy:
      permission_denied: "reject"    # 直接拒绝
      evidence_missing: "reject"     # 直接拒绝
      audit_log: true                # 记录所有违规尝试
```

#### 四权分立对照

```
┌─────────────────────────────────────────────────────────────┐
│                    四权分立 vs 传统模式                        │
│                                                              │
│  权力          │ 传统 (Cross-Validator) │ ClawdLab 四权分立    │
│  ──────────────┼────────────────────────┼───────────────────  │
│  质疑权        │ Cross-Validator (单)   │ Critic (独立)        │
│  执行权        │ Data Scout             │ Data Scout           │
│  裁决权        │ Cross-Validator (兼)   │ Meta-Judge (独立)    │
│  监督权        │ 无                     │ PI Agent + HITL      │
│                                                              │
│  问题: 质疑者兼裁决者 → 无法保证公正                             │
│  解决: 四权分属四个不同角色，互相制衡                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 技术 USP 设计

### 6.1 USP #1: 自纠正研究循环 (Self-Correcting Research Loop)

#### 差异化

传统 Agent 系统是"直线型"的：搜索 → 读取 → 总结。一旦数据被采集，即使存在错误或矛盾，后续分析也会基于错误数据进行。

我们的 **自纠正研究循环** 是 2026 年 Bioptic Agent 论文思路（F1=79.7% vs GPT-5.2 Pro 46.6%）在商品分析领域的落地：

- **矛盾检测**: Cross-Validator 自动检测多源数据矛盾（结构化对比，非模糊判断）
- **结构化质疑**: 生成具体、可执行的质疑指令（含建议搜索关键词和优先数据源）
- **定向补采**: Data Scouts 根据质疑进行定向重新采集（非全量重新搜索）
- **收敛保证**: 最多 2 轮质疑-回应，避免无限辩论（成本上限可控）
- **可信度追踪**: 每个数据点附带置信度评分和证据链（可审计）

```
传统 ReAct (线性):
  Search → Read → Summarize → Done
  ❌ 错误数据被静默传播到最终报告

我们的自纠正循环 (DAG with feedback edge):
  Collect → Validate → [矛盾?] → Challenge → Recollect → Re-Validate → Synthesize
                ↑                         │
                └─── 质疑-回应循环 ───────┘
  ✅ 数据在进入分析前经过质量把关
  ✅ 每一轮循环都有质量提升记录 (可计量)
  ✅ 不可修复的低质量数据被标记而非隐藏
```

#### 对标参考

| 系统 | F1 Score | 方法 |
|------|----------|------|
| **Bioptic Agent (2026)** | 79.7% | 完整性搜索控制 + 专家验证 |
| Gemini 3.1 Deep Think | 59.2% | 通用深度搜索 |
| Claude Opus 4.6 | 56.2% | 通用推理 |
| GPT-5.2 Pro | 46.6% | 通用深度研究 |
| Exa Websets | 26.9% | 纯搜索 |

来源: [Vinogradov et al., "Hunt Globally: Wide Search AI Agents", arXiv 2026](https://arxiv.org/html/2602.15019v4)

### 6.2 USP #2: 人类在环协作审批门 (HITL Collaboration Gate)

#### 差异化

大多数 Agent 系统是"黑盒"的——用户提出问题，系统几分钟后返回结果。对于商业分析这种高风险决策场景（一份错误的市场分析可能导致数百万的决策失误），这绝对不够。

我们的 **HITL 协作审批门** 基于 LangGraph 2.0 的 `interrupt()` + `Command(resume=...)` 机制：

- **战略性暂停**: 在关键决策点（分析完成后、报告生成前）自动暂停
- **结构化审批界面**: 人类看到的不只是文本，而是结构化的分析数据包（数据点数、质量分、关键发现、未解决问题）
- **多选项决策**: 批准 / 修改参数（指定维度调整后重新合成）/ 要求重新分析
- **Stale State 检测**: 超过 30 分钟未响应 → 提示过期
- **状态持久化**: 基于 PostgresSaver，暂停期间状态不丢失
- **恢复执行**: `Command(resume=decision)` 从断点无缝恢复

#### 2026 年共识：三层风险框架

我们基于 2026 年行业共识设计了分层管控模型：

| 层级 | 管控模式 | 适用场景 | 实现方式 |
|------|---------|---------|---------|
| **Tier 1 — 自由运行** | 无阻断，仅日志 | 数据读取、内部摘要、草稿生成 | 直接通过 |
| **Tier 2 — 监控标记 (HOTL)** | Agent 执行，人类观察 | 非关键分析、可逆操作 | Dashboard 通知 |
| **Tier 3 — 阻断审批 (HITL)** | `interrupt()` 门，人类必须批准 | 关键决策建议、外部输出、最终报告 | **本项目核心实现** |

来源: [Dev.to: HITL or HOTL? (April 2026)](https://dev.to/waxell/human-in-the-loop-or-human-on-the-loop-most-teams-are-using-the-wrong-model-588p), [Focused.io: Production HITL Patterns (Feb 2026)](https://focused.io/lab/your-ai-just-emailed-a-customer-without-permission)

### 6.3 USP #3 (候选 Phase 2): 协作记忆与来源可信度档案

随着系统处理越来越多的分析任务：

- **来源可信度档案**: 基于历史验证结果的数据源评分（如：官网=0.95, 科技媒体=0.80, 论坛=0.45）
- **领域知识图谱**: 商品-属性-来源-时间的知识网络
- **分析模板库**: 常见分析场景的模板化工作流（复用成功的分析结构）

---

## 7. 工程质量与生产考量

### 7.1 Checkpointer 选型

| Backend | 适用阶段 | 说明 |
|---------|---------|------|
| `MemorySaver` | 开发阶段 | 进程重启丢失，不可用于生产 |
| `SqliteSaver` | 单机生产 | 轻量级，适合单服务器部署 |
| `PostgresSaver` | 多实例生产 | **推荐** — 支持多实例、长期审计历史 |

LangGraph 2.0 要求 **checkpointer 在图编译时注入**，非运行时可选。

### 7.2 State 膨胀控制

2026 年生产经验：3MB 的 State 对象会导致 600ms 的 checkpoint 写入延迟。

**我们的策略**:
- 不在 State 中存储原始 LLM 响应
- Scout 采集的完整数据写入沙箱 workspace 的 JSON 文件，State 中只保留摘要和路径
- 设置 TTL 清理旧 checkpoint: `DELETE WHERE created_at < now() - INTERVAL '7 days'`
- 使用 `Annotated[list, add]` reducer 而非每次全量替换

### 7.3 幂等性与错误恢复

| 问题 | 解决方案 |
|------|---------|
| **双重恢复** | 检查 thread 是否已有 `review_decision`，有则拒绝重复恢复 |
| **Stale State** | 在 interrupt payload 中附加 `created_at`，恢复时检查 TTL |
| **Interrupt 重排序** | 每个节点只放一个 `interrupt()`，LangGraph 按位置匹配 resume 值 |
| **部分失败** | Scout 失败不阻塞整体流程，失败的维度标记后继续 |
| **超时处理** | SubagentExecutor 自带 600s 超时，超时后该 Scout 结果标记为 incomplete |

### 7.4 审计与可观测性

```
execution_trace: [
  {"phase": "planning",   "start": "...", "end": "...", "decision": "3 scouts"},
  {"phase": "collecting", "start": "...", "end": "...", "rounds": 1, "data_points": 47},
  {"phase": "validating", "start": "...", "end": "...", "score": 0.82, "debates": 0},
  {"phase": "synthesizing","start": "...", "end": "...", "recommendations": 5},
  {"phase": "hitl",       "start": "...", "end": "...", "decision": "approved"},
  {"phase": "composing",  "start": "...", "end": "...", "artifacts": ["report.md", "chart.png"]},
]
```

每条 trace 记录：决策人/Agent、时间戳、输入摘要、输出摘要、耗时 —— 满足 2026 年 AI 治理对可审计性的要求。

---

## 8. 目录结构与模块规划

### 8.1 新增目录结构

```
backend/packages/harness/deerflow/
├── collaboration/                        # 协作系统核心 (Harness 层)
│   ├── __init__.py
│   ├── graph.py                          # Parent Graph + Nested SubGraph 组装
│   ├── state.py                          # 三层 State 定义 (Parent/Research/Analysis)
│   ├── subgraphs/                        # SubGraph 构建
│   │   ├── __init__.py
│   │   ├── research_subgraph.py          # Research SubGraph (PI+Scouts+Critic+Judge)
│   │   ├── analysis_subgraph.py          # Analysis SubGraph (Lead+Synthesizer+Reviewer)
│   │   └── state_mapping.py             # State Mapping 函数 (state_in/state_out)
│   ├── nodes/                            # 图节点实现
│   │   ├── __init__.py
│   │   ├── pi_agent.py                   # PI Agent (Research SubGraph Supervisor)
│   │   ├── data_scout.py                 # Data Scout (Send API 并行)
│   │   ├── critic_agent.py               # Critic Agent (对抗式质疑)
│   │   ├── meta_judge.py                 # Meta-Judge Agent (独立裁决)
│   │   ├── analyst_lead.py               # Analyst Lead (Analysis SubGraph Supervisor)
│   │   ├── synthesizer.py                # Synthesizer (多维分析)
│   │   ├── internal_reviewer.py          # Internal Reviewer (分析质量内审)
│   │   ├── hitl_gate.py                  # HITL Gate (LangGraph interrupt)
│   │   ├── report_composer.py            # Report Composer (报告+图表)
│   │   └── error_handler.py              # 全局错误处理
│   ├── prompts/                          # 角色提示词模板
│   │   ├── __init__.py
│   │   ├── pi_agent.py
│   │   ├── data_scout.py
│   │   ├── critic_agent.py
│   │   ├── meta_judge.py
│   │   ├── analyst_lead.py
│   │   ├── synthesizer.py
│   │   ├── internal_reviewer.py
│   │   └── report_composer.py
│   ├── permissions/                      # 角色门控治理
│   │   ├── __init__.py
│   │   ├── role_definition.py            # RolePermission 定义 + ROLE_PERMISSIONS
│   │   └── permission_guard.py           # PermissionGuardMiddleware
│   ├── protocols/                        # 协作协议定义
│   │   ├── __init__.py
│   │   ├── messages.py                   # Challenge/Rebuttal/Ruling 消息格式
│   │   └── debate.py                     # 对抗式批判协议状态机
│   ├── events.py                         # 协作流式事件类型定义
│   ├── router.py                         # 条件路由函数 (含 SubGraph 间路由)
│   └── memory/                           # 协作记忆
│       ├── __init__.py
│       ├── source_credibility.py         # 来源可信度档案更新
│       └── product_knowledge.py          # 产品知识库管理
├── agents/
│   ├── lead_agent/
│   │   └── agent.py                      # ← 修改：增加 collaboration 图入口
│   └── middlewares/
│       └── collaboration_middleware.py    # ← 新增：协作上下文注入 + 角色标记
└── config/
    └── collaboration_config.py           # ← 新增：协作配置 Pydantic 模型

backend/app/gateway/routers/
└── collaboration.py                      # ← 新增：协作 HITL 恢复 API

# === Skills (DF Skills 系统, 放置在 skills/public/) ===
skills/public/
├── price-elasticity/                     # 价格弹性分析 Skill
│   └── SKILL.md
├── sentiment-analyzer/                   # 情感分析 Skill
│   └── SKILL.md
├── market-share-calc/                    # 市场份额估算 Skill
│   └── SKILL.md
├── source-credibility/                   # 来源可信度评分 Skill
│   └── SKILL.md
├── spec-comparator/                      # 规格对比矩阵 Skill
│   └── SKILL.md
├── trend-detector/                       # 趋势检测 Skill
│   └── SKILL.md
├── data-normalizer/                      # 数据标准化 Skill
│   └── SKILL.md
└── swot-generator/                       # SWOT 生成 Skill
    └── SKILL.md

backend/tests/
├── test_collaboration_graph.py           # Parent Graph + SubGraph 挂载测试
├── test_collaboration_subgraphs.py       # SubGraph 独立编译 + State Mapping 测试
├── test_collaboration_nodes.py           # 各节点单元测试 (8 个角色)
├── test_collaboration_critic_judge.py    # Critic+Meta-Judge 对抗式批判协议测试
├── test_collaboration_hitl.py            # HITL 暂停/恢复/幂等/过期
├── test_collaboration_permissions.py     # 角色门控 PermissionGuard 测试
├── test_collaboration_debate.py          # 质疑-回应协议测试
├── test_collaboration_skills.py          # Skills 加载 + 工具过滤测试
└── test_collaboration_e2e.py             # 端到端协作流程测试
```

### 8.2 配置扩展 (config.yaml)

```yaml
# === 协作系统配置 ===
collaboration:
  enabled: true

  # 默认工作流
  default_workflow: "competitive_analysis"

  # === 角色模型配置 ===
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
    report_composer:
      model: "inherit"
      max_turns: 40

  # === 角色门控配置 ===
  role_gates:
    enabled: true
    enforcement: "hard"

    roles:
      pi_agent:
        permissions: [plan, dispatch, review, override_critic]
        audit_actions: [override_critic]
        model: "claude-opus-4-7"
      data_scout:
        permissions: [search, fetch, respond_to_critic]
        evidence_required_for: [respond_to_critic]
        model: "inherit"
        max_parallel: 3
      critic_agent:
        permissions: [challenge, read_data]
        evidence_required_for: [challenge]
        model: "claude-opus-4-7"
        max_debate_rounds: 2
      meta_judge:
        permissions: [adjudicate, read_data, run_verification]
        evidence_required_for: [adjudicate]
        model: "claude-opus-4-7"

    violation_policy:
      permission_denied: "reject"
      evidence_missing: "reject"
      audit_log: true

  # === HITL 配置 ===
  hitl:
    enabled: true
    gates:
      - post_synthesis    # 分析完成后暂停，人类审批
    stale_timeout_minutes: 30
    require_audit_log: true

  # === Checkpointer 配置 ===
  checkpointer:
    backend: "postgres"   # memory | sqlite | postgres
    checkpoint_ttl_days: 7

  # === 预定义工作流 ===
  workflows:
    competitive_analysis:
      description: "竞品深度对比分析"
      phases: [planning, collecting, validating, synthesizing, reviewing, composing]
      scouts: 3

    market_trend:
      description: "市场趋势洞察"
      phases: [planning, collecting, synthesizing, reviewing, composing]
      scouts: 2
      skip_validation: true

    pricing_optimization:
      description: "商品定价优化"
      phases: [planning, collecting, validating, synthesizing, reviewing, composing]
      scouts: 2

    supply_chain_risk:
      description: "供应链风险评估"
      phases: [planning, collecting, validating, synthesizing, reviewing, composing]
      scouts: 3
```

---

## 9. 实施路线图

### Phase 2: 规则重塑 (已完成)
- [x] 重写 CLAUDE.md：固化业务逻辑、协作流程、目录结构、技术选型
- [x] 将架构文档核心约束写入 CLAUDE.md

### Phase 3: 编码实施 (6 个 Sprint — ✅ 全部完成)

> 2026-05-15: 6 个 Sprint 全部完成。180 个测试通过。详见 CLAUDE.md Section 9。

| Sprint | 内容 | 核心交付 | 差异说明 |
|--------|------|---------|---------|
| 1 | SubGraph 骨架 + State 定义 | 三层 State、2 个 SubGraph、4 个 State Mapping、Parent Graph 组装 | `router.py` 未独立（路由在 graph.py + subgraph 中） |
| 2 | Research SubGraph 节点 | 5 角色节点（合并为 research_nodes.py）、4 提示词、对抗式批判协议 | 节点文件合并，非每角色独立文件 |
| 3 | Analysis SubGraph + Report | 3 角色节点（合并为 analysis_nodes.py）、4 提示词、Report Composer | 同上；8 个 Skills SKILL.md 未创建 |
| 4 | 角色门控 + HITL + 流式 | RoleDefinition、PermissionGuard、HITL Gate、EventType 枚举、HITL API | `error_handler.py` 未独立（实现在 subgraph 中）；`middleware.py` 拆为 context.py + collaboration_middleware.py |
| 5 | 配置 + 集成 | Pydantic 配置模型、config.example.yaml、CollaborationMiddleware 注册 | **Lead Agent 路由未实现**；Memory 系统未落地；Skills 未创建 |
| 6 | E2E + 文档 | 11 个 E2E 测试、_extract_json 修复、route_after_critic 修复、hitl_gate 幂等修复 | — |

### Phase 4: 生产就绪 (待实施)

> Phase 3 完成了图结构、节点逻辑、权限门控、HITL、配置热加载和 E2E 测试。
> 以下缺口阻止系统在真实环境中运行。按优先级排列。

#### P0: Lead Agent 路由到协作图

**现状**: `agent.py:316-318` 注册了 CollaborationMiddleware，但 Lead Agent 本身仍是标准 ReAct。
**需要**: 当 `collaboration.enabled: true` 时，Lead Agent 应调用 `build_collaboration_graph()` 而非标准 `make_lead_agent()`。或者在 `langgraph.json` 中注册协作图为独立 graph。

| 文件 | 说明 |
|------|------|
| `langgraph.json` | 注册协作图为独立 graph，或增加路由逻辑 |
| `agents/lead_agent/agent.py` | 实现 `collaboration.enabled` 时的图切换逻辑 |

#### P1: Checkpointer 集成

**现状**: `build_collaboration_graph()` 编译时未传 `checkpointer`。HITL 的 `interrupt()` 依赖 checkpoint 持久化才能暂停/恢复。
**需要**: 编译时注入 `SqliteSaver`（开发）或 `PostgresSaver`（生产）。

| 文件 | 说明 |
|------|------|
| `collaboration/graph.py` | `builder.compile(checkpointer=...)` |
| `config.yaml` | `collaboration.checkpointer.backend` 配置项 |

#### P1: Send API 并行 Fan-out

**现状**: `research_subgraph.py` import 了 `Send` 但未使用。Scout 采集是顺序的 `pi_agent → critic_agent → data_scout → critic_agent`。
**需要**: PI 规划后通过 `Send(node, arg)` 并行启动 2-4 个 Scout，Scout 完成后通过 reducer 汇总结果。

| 文件 | 说明 |
|------|------|
| `collaboration/subgraphs/research_subgraph.py` | 实现 `fan_out_to_scouts()` → `list[Send]` |
| `collaboration/nodes/research_nodes.py` | PI 节点改为输出 task_plan 供 Send API 消费 |

#### P2: 真实 LLM 验证

**现状**: 所有 180 个测试使用 mock SubagentExecutor，未验证真实 LLM 调用下的 prompt 效果。
**需要**: 至少 1 个集成测试用真实 LLM 跑通最小流程，验证 prompt 模板和 JSON 输出格式。

| 文件 | 说明 |
|------|------|
| `tests/test_collaboration_live.py` | 真实 LLM 集成测试（需要 API key，手动运行） |

#### P2: Skills 创建

**现状**: 8 个 Skill 名在代码中引用（`SubagentConfig.skills=[...]`），但 `skills/public/` 下无对应 `SKILL.md` 文件。
**需要**: 为每个 Skill 创建 `SKILL.md`（YAML frontmatter + 指令）。

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

#### P3: 协作 Memory 落地

**现状**: `collaboration_config.py` 定义了 `SourceCredibilityConfig` 和 `ProductKnowledgeConfig`，但未实际调用 DF Memory 系统。
**需要**: 在 Critic/Meta-Judge 验证完成后触发 Memory 更新。

| 文件 | 说明 |
|------|------|
| `collaboration/memory/source_credibility.py` | 基于验证结果更新数据源可信度评分 |
| `collaboration/memory/product_knowledge.py` | 已验证数据点的持久化存储 |

---

## 10. 附录

### 附录 A: DeerFlow 底座约束检查清单

| 约束 | 状态 | 说明 |
|------|------|------|
| 使用 DeerFlow 原生 Sandbox | ✅ | 所有文件操作通过 `ensure_sandbox_initialized()` |
| 使用 DeerFlow 原生 SubagentExecutor | ✅ | 每个协作节点封装 SubagentExecutor |
| 使用 DeerFlow 原生中间件链 | ✅ | 图执行复用已有中间件 |
| 使用 DeerFlow 原生 Checkpointer | ✅ | 扩展为 PostgresSaver，HITL 依赖此机制 |
| 使用 DeerFlow 原生配置系统 | ✅ | 扩展 config.yaml 而非替换 |
| 不破坏 Harness/App 边界 | ✅ | 新增代码在 deerflow.* 和 app.* 中合理分布 |
| 不破坏现有测试 | ✅ | 纯增量开发 |
| 遵循 LangGraph 2.0 API | ✅ | interrupt() + Command(resume=...) + Send API |

### 附录 B: 关键参考资源 (2026 年优先)

**GitHub 直接可比项目**:
- [competitor-hunter](https://github.com/Duang777/competitor-hunter) — SaaS 竞品分析，LangGraph + MCP + Playwright
- [Product-Research-Multi-Agent-System](https://github.com/To11-o11/Product-Research-Multi-Agent-System) — 中文多 Agent 产品调研
- [Multi-Agent-BDS](https://github.com/aparaajita19/Multi-Agent-BDS) — 4 Agent 电商情报平台
- [e-commerce-agents](https://github.com/nitin27may/e-commerce-agents) — 6 Agent 电商平台，A2A 协议
- [Research_agents](https://github.com/towardsforever/Research_agents) — LangGraph StateGraph + SubGraph 分层
- [DeepShop](https://github.com/youganglyu/DeepShop) — 深度购物 Agent 基准

**LangGraph 编排模式**:
- [Supervisor Pattern (LangGraph 2026)](https://deepwiki.com/langchain-ai/langgraphjs/4.1-supervisor-pattern)
- [Swarm Pattern (LangGraph 2026)](https://deepwiki.com/langchain-ai/langgraphjs/4.2-swarm-pattern)
- [Hierarchical Agent Teams (LangGraph 2026)](https://deepwiki.com/langchain-ai/langgraphjs/4.3-hierarchical-agent-teams)
- [LangGraph 2.0 Definitive Guide (2026)](https://dev.to/richard_dillon_b9c238186e/langgraph-20-the-definitive-guide-to-building-production-grade-ai-agents-in-2026-4j2b)

**HITL 生产实践**:
- [Building HITL Approval Gates (2026)](https://machinelearningmastery.com/building-a-human-in-the-loop-approval-gate-for-autonomous-agents/)
- [HITL or HOTL? Three-Tier Framework (April 2026)](https://dev.to/waxell/human-in-the-loop-or-human-on-the-loop-most-teams-are-using-the-wrong-model-588p)
- [Production HITL Patterns (Feb 2026)](https://focused.io/lab/your-ai-just-emailed-a-customer-without-permission)
- [Transactional Agentic AI with LangGraph (Dec 2025)](https://www.marktechpost.com/2025/12/31/how-to-design-transactional-agentic-ai-systems-with-langgraph-using-two-phase-commit-human-interrupts-and-safe-rollbacks/)

**学术/行业参考**:
- [Bioptic Agent: Wide Search for Drug Scouting (arXiv 2026)](https://arxiv.org/html/2602.15019v4) — F1=79.7%, 完整性搜索的验证
- [AgenticPay: Multi-Agent Negotiation (arXiv 2026)](https://arxiv.org/html/2602.06008v1) — Claude Opus 4.5 最优
- [AI in Competitive Intelligence 2026 — Klue](https://klue.com/topics/how-ai-helps-with-competitive-intelligence)
- [Agentic AI Market Research 2026 — Qualtrics](https://www.qualtrics.com/articles/strategy-research/agentic-ai-market-research/)
- [LangGraph vs CrewAI in 2026 — Redwerk](https://redwerk.com/blog/langgraph-vs-crewai/)

### 附录 C: 与 CrewAI 方案的对比 (为什么选择 LangGraph)

| 维度 | CrewAI | LangGraph (我们的选择) |
|------|--------|----------------------|
| 状态管理 | 隐式 (对话历史) | **显式 (TypedDict State)** — 可持久化、可审计 |
| 流程控制 | 顺序/条件 (有限) | **图式 (StateGraph + Conditional Edges)** — 灵活路由 |
| HITL 支持 | 有限 | **原生 interrupt() + Command(resume=...)** |
| Checkpointer | 无 | **MemorySaver / SqliteSaver / PostgresSaver** |
| 并行执行 | 有限 | **Send API Fan-out** |
| 可观测性 | 弱 | **LangSmith 集成** — 时间旅行调试 |
| 企业验证 | 有限 | **Uber, LinkedIn, Klarna, Replit** |
| 学习曲线 | 低 | 中高 — 但回报更高 |

---

## 附录 D: 文档修订记录

### v2.1 (2026-05-15) — Phase 3 完成 + Phase 4 规划

**修订内容**:
- 更新 Phase 3 6 个 Sprint 完成状态（180 测试通过）
- 记录计划与实际的差异（节点文件合并、Skills 未创建、Lead Agent 路由未实现等）
- 新增 Phase 4 生产就绪计划（P0/P1/P2/P3 优先级）
- 版本号更新至 v2.1

### v2.0 (2026-05-14) — Phase 1 修订版

**修订触发**: 用户要求 (1) 文档移至项目根目录；(2) 搜索 GitHub 类似项目并提供参考链接；(3) 自检文档完整性/正确性/前沿性；(4) 搜索以 2026 年优先。

**修订内容**:

| 修订项 | 详细说明 |
|--------|---------|
| **文档位置** | 从 `docs/plans/PA-Agent-DF-architecture.md` 移至 `PA-Agent-DF-architecture.md`（项目根目录），避免与 DeerFlow 原生文档混放 |
| **新增第 1 节** | GitHub 生态调研与竞品分析 — 收录 7 个直接可比的开源项目（competitor-hunter、Product-Research-Multi-Agent-System、Multi-Agent-BDS、e-commerce-agents、Research_agents、DeepShop、AgenticPay）及 2026 年框架格局分析（LangGraph vs CrewAI vs AutoGen vs OpenAI Agents SDK）、三大技术共识（MCP/A2A/多框架混合） |
| **HITL 升级** | 从旧版 `NodeInterrupt` 异常模式全面升级为 LangGraph 2.0 的 `interrupt()` + `Command(resume=...)` 显式 API；增加 `interrupt_before` vs `interrupt_after` 决策理由；增加 Stale State 检测机制 |
| **新增三层风险框架** | Tier 1 (自由运行) / Tier 2 (监控标记 HOTL) / Tier 3 (阻断审批 HITL)，基于 2026 年行业共识（Focused.io、SAP Community） |
| **编排模式明确化** | 明确采用 Supervisor + 受限 Swarm 混合模式；增加 LangGraph 三种编排模式（Supervisor/Swarm/Hierarchical Teams）对比表及选型理由 |
| **Send API 并行 Fan-out** | 使用 LangGraph 2.0 Send API 实现真正的并行 Data Scout 执行，替换 v1.0 中的顺序循环 |
| **新增第 7 节** | 工程质量与生产考量 — Checkpointer 三档选型（MemorySaver/SqliteSaver/PostgresSaver）、State 膨胀控制策略（3MB→600ms 问题）、幂等性与错误恢复矩阵（双重恢复/Stale State/Interrupt 重排序/部分失败/超时）、审计追踪设计 |
| **USP #1 深度强化** | 增加 Bioptic Agent 论文（arXiv 2026）的 F1 对标数据（79.7% vs GPT-5.2 Pro 46.6%），用学术证据支撑自纠正循环的设计合理性 |
| **USP #2 生产化** | 增加 `hitl_timestamp` 字段、`is_stale()` 检测逻辑、`review_decision` 幂等检查、`interrupt_before` 审批门语义 |
| **新增附录 C** | LangGraph vs CrewAI 全方位对比表（8 个维度），解释技术选型理由 |
| **参考资源全面更新** | 所有链接优先 2026 年来源，新增 15+ 引用：包括 LangGraph 2.0 Guide、HITL Production Patterns、Bioptic Agent、AgenticPay、Qualtrics/Klue 2026 报告、Supervisor/Swarm/Hierarchical Teams 模式文档 |
| **配置扩展** | 增加 `checkpointer` 配置段（backend + TTL）、`stale_timeout_minutes`、`quality_threshold`、`require_audit_log` |
| **目录结构** | 新增 `error_handler.py` 节点、`protocols/debate.py` 协议实现、`test_collaboration_debate.py` 测试 |
| **数据来源** | 2026 年 5 月搜索：Bioptic Agent F1 数据、Navy Federal Credit Union（5天→4小时）、Booking.com 合成面板、行业采用率（15%→44%） |

**搜索覆盖** (5 路并行，均以 2026 年优先):
1. `GitHub multi-agent product analysis competitive research LangGraph 2026`
2. `GitHub AI agent e-commerce product comparison collaborative multi-agent system 2026`
3. `LangGraph StateGraph advanced patterns 2026 multi-agent orchestration supervisor swarm`
4. `human-in-the-loop AI agent approval gate LangGraph interrupt 2026 production pattern`
5. `AI agent competitive intelligence market research automation 2026 state of art`

**关键参考链接**:
- [competitor-hunter](https://github.com/Duang777/competitor-hunter) — LangGraph + MCP + Playwright 竞品分析
- [Product-Research-Multi-Agent-System](https://github.com/To11-o11/Product-Research-Multi-Agent-System) — 中文 4 Agent 产品调研
- [Multi-Agent-BDS](https://github.com/aparaajita19/Multi-Agent-BDS) — 4 Agent 电商情报平台
- [e-commerce-agents](https://github.com/nitin27may/e-commerce-agents) — 6 Agent + A2A 协议
- [Supervisor Pattern (LangGraph 2026)](https://deepwiki.com/langchain-ai/langgraphjs/4.1-supervisor-pattern)
- [Swarm Pattern (LangGraph 2026)](https://deepwiki.com/langchain-ai/langgraphjs/4.2-swarm-pattern)
- [LangGraph 2.0 Definitive Guide (2026)](https://dev.to/richard_dillon_b9c238186e/langgraph-20-the-definitive-guide-to-building-production-grade-ai-agents-in-2026-4j2b)
- [HITL or HOTL? Three-Tier Framework (April 2026)](https://dev.to/waxell/human-in-the-loop-or-human-on-the-loop-most-teams-are-using-the-wrong-model-588p)
- [Production HITL Patterns (Feb 2026)](https://focused.io/lab/your-ai-just-emailed-a-customer-without-permission)
- [Bioptic Agent: Wide Search (arXiv 2026)](https://arxiv.org/html/2602.15019v4)
- [AI in Competitive Intelligence 2026 — Klue](https://klue.com/topics/how-ai-helps-with-competitive-intelligence)
- [Agentic AI Market Research 2026 — Qualtrics](https://www.qualtrics.com/articles/strategy-research/agentic-ai-market-research/)
- [LangGraph vs CrewAI in 2026 — Redwerk](https://redwerk.com/blog/langgraph-vs-crewai/)
