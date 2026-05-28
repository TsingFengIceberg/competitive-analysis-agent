# CI-Agent 开发指令

> 字节跳动 CIS「AI 全栈项目挑战赛」参赛项目 | 2026-05-20 ~ 2026-06-10
> 架构设计详见 [COMPETITION_PLAN.md](./COMPETITION_PLAN.md)
> 竞赛要求 TODO 详见 [COMPETITION_TODO.md](./COMPETITION_TODO.md)

---

## 0. 编码时必做：标注竞赛要求对应关系

**每次编写或修改代码时，必须在回复中说明该代码对应竞赛的哪条要求。**

格式示例：
> `**[R1]**` 此处实现 Collector 角色，职责边界：多源采集 + 问卷生成
> `**[R7]**` Writer 的 `_inject_source_annotations()` 为每条结论添加 `[n]` 上标来源标注

完成后，更新 [COMPETITION_TODO.md](./COMPETITION_TODO.md) 将对应条目打 `[x]`。

**文档编辑权限**：编辑任何 .md 文档时，如需调整章节编号（插入新章节导致后续编号顺延），可直接使用 sed 批量重编号，无需询问。

---

## 1. 项目定位

CI-Agent 是一个**竞品分析 Agent 协作系统**，4 个专职 Agent（Collector / Analyst / Reviewer / Writer）基于 LangGraph StateGraph 完成从数据采集到报告生成的全链路。

- **基座**: ByteDance DeerFlow（Sandbox + SubagentExecutor + Tools + Skills + Middleware）
- **编排**: LangGraph StateGraph 单图 + 条件路由反馈闭环
- **前端**: 待定（Gradio 或 Next.js）
- **协议**: MIT License

---

## 2. 启动方式（服务器内存仅 7.1GB，必须用生产模式）

**前端必须用 `pnpm build && pnpm start`，严禁 `pnpm dev`。** Turbopack dev 模式吃 1.5-2.5GB 内存，会导致 SSH 断开。

```bash
# 1. 启动后端 Gateway（端口 8001）
cd backend && PYTHONPATH=packages/harness nohup uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 > /tmp/gateway.log 2>&1 &

# 2. 构建前端（仅前端代码变更时需要重新 build）
cd frontend && pnpm build

# 3. 启动前端生产模式（端口 2026）
cd frontend && PORT=2026 nohup pnpm start > /tmp/frontend.log 2>&1 &
```

| 模式 | 内存 | 说明 |
|------|------|------|
| `pnpm dev` (Turbopack) | 1.5-2.5 GB | 实时编译 + HMR，**禁止在服务器使用** |
| `pnpm build` + `pnpm start` | ~100 MB | 预编译静态文件，**必须用这个** |

- 仅改后端代码 → 重启 gateway 即可，无需 rebuild 前端
- 改前端代码 → 重新 `pnpm build && pnpm start`
- 查看日志：`tail -f /tmp/gateway.log` / `tail -f /tmp/frontend.log`
- 页面地址：`http://<服务器公网IP>:2026/competition`

### 2.1 密钥管理（强制）

**除 `.env` 和 `config.yaml` 外，任何文件不得包含明文 API Key。**

- `.env` 已在 `.gitignore`，不会提交到仓库
- `config.yaml` 已在 `.gitignore`，不会提交到仓库
- 所有其他文件（Python、TypeScript、Markdown 等）必须通过环境变量读取密钥
- 禁止 `os.environ.get("KEY", "hardcoded-fallback")` 的默认值模式
- Doubao 配置已统一迁移到 `.env`：`DOUBAO_MODEL`、`DOUBAO_API_BASE`、`DOUBAO_API_KEY`

**每次提交前必须执行密钥检查：**
```bash
grep -rn "ark-f\|sk-[a-zA-Z0-9]\{20,\}\|api_key.*[a-zA-Z0-9]\{30,\}" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --include="*.md" --include="*.yaml" --include="*.yml" \
  --include="*.json" \
  .gitignore config.yaml .env \
  2>/dev/null | grep -v node_modules | grep -v .venv | grep -v ".next" | grep -v pnpm-lock
```
输出为空才算通过。

---

## 3. 核心架构约束

### 3.1 单图 4 节点 + 反馈环

```
Collector → Analyst → Reviewer → Writer → HITL Gate
    ↑          ↑          │            │
    │          │          │            ├─ approve → END
    └──────────┴── gap ───┘            ├─ replan → Collector
            (最多 2 轮)                ├─ reanalyze → Analyst
                                       └─ rewrite → Writer
```

**不允许**引入 PA-Agent-DF 的旧架构模式：
- ❌ 不建 Nested SubGraph、不建独立的 Research/Analysis 子图
- ❌ 不引入 Critic/Meta-Judge 分离（合并为 Reviewer）
- ❌ 不引入四权分立 permission 系统
- ❌ 不在 Harness 层 import `app.*`

### 3.2 DeerFlow-First 铁律

```
DeerFlow 原生实现 > 外围封装/适配器 > 引入外部框架 > 从零自建
```

| 需求 | 实现 |
|------|------|
| Agent 执行 | `SubagentExecutor(config, tools, ...).execute(task)` — 不直接调 LLM API |
| 沙箱文件操作 | `ensure_sandbox_initialized(runtime)` — 不走裸文件系统 |
| 工具加载 | `get_available_tools(groups=["community"])` — 不过滤掉 DF 内置工具 |
| Skills | `SubagentConfig.skills` 白名单 — 不重复实现 DF 已有 Skill |
| 中间件 | 复用 DF 18 个中间件链，不替换 |
| Checkpointer | DF 已有 SqliteSaver/PostgresSaver |
| Stream | DF 已有 `stream_mode=["values", "custom"]` + StreamBridge |
| Config | 扩展 `config.yaml` 的 `competition` 段，走 `deerflow.config` 读取 |

### 3.3 禁止修改的 DF 文件

- `deerflow/sandbox/sandbox.py` / `sandbox_provider.py` / `tools.py`
- `deerflow/subagents/executor.py`
- `deerflow/tools/tools.py`
- `deerflow/agents/lead_agent/agent.py`（仅可增加路由入口）

---

## 4. 竞赛要求速查

> 完整追溯矩阵见 [COMPETITION_PLAN.md §1.4](./COMPETITION_PLAN.md#14-竞赛要求追溯矩阵)

| 编码时必须确保 |
|-------------|
| `**[R1]**` 4 角色职责边界清晰：Collector/Analyst/Reviewer/Writer，各有规范章节 |
| `**[R2]**` Collector 双轨：VoC Aggregator（主）+ 问卷/访谈生成（辅） |
| `**[R3]**` 输出符合 Pydantic Schema（FeatureTree/PricingModel/UserPersona） |
| `**[R4]**` Agent 间走 6 边结构化 JSON（AnalysisResult/ReviewVerdict/ReviewPackage/HitlDecision） |
| `**[R5]**` Reviewer 8 项 gap 判定 → 打回 Collector，最多 2 轮 |
| `**[R6]**` 反馈改善率量化（improvement_ratio） |
| `**[R7]**` 每条结论 ReportData 内联 `[n]` 上标 + traceability_map |
| `**[R8]**` Schema 强制校验：model_validate() + 重试 2 次 + 降级 |
| `**[R9]**` DAG 图实时高亮，节点状态可视化 |
| `**[R10]**` 每个 Agent Prompt/输入/输出/Token 可查（§7 可观测面板） |
| `**[R12]**` 幻觉抑制：引用强制 + 自一致性 + 超长分片（§3.15.1） |
| `**[R13]**` per-Agent 超时 + 指数退避 + 降级（§3.15.5-3.15.6） |
| `**[R15]**` 输出指标：覆盖率/交叉验证率/改善率/溯源率（§3.15.4） |
| `**[R17]**` robots.txt 预检 + 来源声明（§3.15.2） |
| `**[R18]**` 数据脱敏：PII 检测 + 匿名化（§3.15.3） |

---

## 5. 目录结构

```
backend/packages/harness/deerflow/
├── competition/                     # 竞赛代码（与 collaboration/ 平级）
│   ├── __init__.py
│   ├── state.py                     # CompetitionState (单层 TypedDict)
│   ├── schema.py                    # Pydantic Schema + validate_agent_output()
│   ├── graph.py                     # build_competition_graph()
│   ├── router.py                    # route_after_* 条件路由
│   ├── config.py                    # Pydantic 配置模型
│   ├── visualization.py             # matplotlib/seaborn 图表
│   ├── db.py                        # SQLite 业务表（source_credibility/product_baseline/analysis_history）
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── collector.py             # + VoC Aggregator 子模块
│   │   ├── analyst.py
│   │   ├── reviewer.py
│   │   ├── writer.py
│   │   ├── hitl_gate.py             # LangGraph interrupt() + 飞书审批
│   │   ├── error_handler.py
│   │   ├── deep_collector.py        # (P1)
    │   ├── deep_analyst.py          # (P1)
    │   ├── deep_reviewer.py         # (P1)
    │   ├── deep_writer.py           # (P1)
    │   └── feishu_delivery.py       # (P1)
    ├── prompts/
    │   ├── collector.md
    │   ├── analyst.md
    │   ├── reviewer.md
    │   └── writer.md
    ├── tools/
    │   └── video_source.py          # YouTube/Bilibili 字幕提取
    └── memory/
        └── source_credibility.py    # (P2)
└── versiontree/                     # Agent 工作流版本树基座 `**[核心差异化]**`
    ├── __init__.py
    ├── node.py                      # StateSnapshot + VersionTreeNode 数据结构
    ├── tree.py                      # VersionTree: add/fork/restore/lineage
    ├── store.py                     # SQLite 持久化
    ├── adapter.py                   # LangGraph State ↔ VersionTree 双向桥接
    └── diff.py                      # 节点对比 (P2)

backend/app/gateway/routers/
└── competition.py                   # POST /analyze, GET /report/{id}, WS /stream

backend/tests/
└── test_competition_*.py

config.yaml                          # 扩展 competition 段
```

---

## 6. 编码规范

### 6.1 节点函数签名

```python
# 所有节点函数统一签名
def collector_node(state: CompetitionState) -> dict:
    """返回部分 state 更新，LangGraph 自动 merge。"""
    ...
    return {"collected_data": new_data}  # Annotated[list, op_add] 自动累加
```

### 6.2 SubagentExecutor 使用模式

```python
from deerflow.subagents.executor import SubagentExecutor
from deerflow.subagents.config import SubagentConfig
from deerflow.tools import get_available_tools

config = SubagentConfig(
    name="collector",
    model="doubao-seed-2-0-lite-260215",
    system_prompt=load_prompt("collector"),
    tools=["web_search", "web_fetch", "python", "write_file"],
    skills=["data-normalizer", "deep-research"],
    max_turns=30,
    timeout_seconds=600,
)
executor = SubagentExecutor(config, tools, sandbox=sandbox)
result = executor.execute(task_description)
```

### 6.3 类型注解

- Python 3.12+，所有函数强制类型注解
- State 字段用 `NotRequired` 标记可选
- 累加字段用 `Annotated[list, op_add]`

### 6.4 错误处理

- **DF 基座层**：LLM API 重试（指数退避）、循环检测、高危命令拦截 — 不需要我们写
- **节点内部**：收到 DF 失败结果后的降级行为、Schema 校验失败重试
- **Graph 路由层**：`error` 字段 → `route_after_*` → `error_handler` 节点
- 不静默吞异常；完整决策树见 [COMPETITION_PLAN.md §3.15.6](./COMPETITION_PLAN.md#3156-错误处理决策树)

### 6.5 Prompt 管理

- Prompt 存为 Markdown 文件（`prompts/*.md`），不在代码中硬编码长文本
- 加载方式：`pathlib.Path(__file__).parent.parent / "prompts" / "collector.md"`
- Prompt 中的变量用 Python `str.format()` 或 f-string 注入

### 6.6 测试驱动开发（TDD — 强制）

**每个新模块必须同步编写测试文件。编码完成 ≠ 测试通过才是完成。**

- 测试目录：`backend/tests/test_competition_*.py`
- 模块 → 测试文件映射：
  - `competition/state.py` → `test_competition_state.py`
  - `competition/schema.py` → `test_competition_schema.py`
  - `competition/config.py` → `test_competition_config.py`
  - `competition/graph.py` → `test_competition_graph.py`
  - `competition/router.py` → `test_competition_router.py`
  - `competition/nodes/*.py` → `test_competition_nodes.py`
  - `competition/db.py` → `test_competition_db.py`
- 运行方式：`cd backend && PYTHONPATH=packages/harness uv run pytest tests/test_competition_*.py -v`
- 状态字段、Schema 校验、配置加载这类纯函数优先测试（无外部依赖）
- 涉及 SubagentExecutor / LLM 调用的节点测试使用 mock

### 6.7 提交前 Lint 检查（强制）

**每次 `git commit` 前必须跑 lint，CI 报红 = 提交不合格。**

| 端 | 命令 | 说明 |
|---|------|------|
| 后端 | `cd backend && PYTHONPATH=packages/harness uv run ruff check packages/harness/deerflow/competition/ tests/` | Python 代码规范（ruff） |
| 前端 | `cd frontend && npx eslint src/app/competition/ src/components/competition/` | TS/React 代码规范（eslint） |

CI（GitHub Actions）每次 push 自动跑这两条，失败会发邮件通知。本地跑过就不用等 CI 报错再修。

---

## 7. 提交规范

- Commit message 格式：`competition: <简短描述> — <English>`
- 中文在前，英文在后
- 每 commit 附 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
- 不在 commit 中包含 `.env`、`config.yaml`（含密钥）、`.venv/`

---

## 8. 上游文档

PA-Agent-DF 的原始架构和开发指令见 [PA-AGENT-DOCS/](./PA-AGENT-DOCS/)。
