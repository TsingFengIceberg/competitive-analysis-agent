# 【AI 全栈项目挑战赛】项目成果提交

> 个人参赛 | 吴冈 | 杭州电子科技大学 | 2026-06-10

---

# 一、基础信息

| 字段 | 内容 |
|------|------|
| **项目名称** | AI 驱动的竞品分析 Agent 协作系统 |
| **参赛课题** | CIS — AI 驱动的竞品分析 Agent 协作系统 |
| **团队名称** | 个人参赛 |
| **队长** | 吴冈 / 杭州电子科技大学 / 计算机科学与技术 / 2027届硕士 |

## 分工说明

| 成员 | 角色 | 负责模块 |
|------|------|---------|
| 吴冈 | 全栈工程师 | 系统架构设计、Agent 编排、后端开发、前端开发|

---

# 二、功能说明

## 核心功能清单

> **系统核心能力一览：**
>
> - **多角色 Agent 协作**：5 个专职 Agent（Orchestrator / Collector / Analyst / Reviewer / Writer）基于 LangGraph StateGraph 单图协作，通过结构化 JSON Schema 通信，职责边界清晰无重叠
> - **动态 Pipeline 与自适应任务拆分**：Orchestrator Agent 单次 LLM 调用完成意图解析、复杂度判定（quick/standard/deep）、维度权重分配、Schema 裁剪，替代传统硬编码规则
> - **Agent 工作流分支树 (BranchTree)**：类 Git 的 Agent 执行分支管理，支持 snapshot / fork / restore / lineage / merge，用户可从任意历史版本分支出新的分析路径
> - **全链路溯源与可观测**：每条结论内联来源标注，DAG 图实时高亮节点状态，SSE 实时推送分析进度，每个 Agent 的 Prompt/输入/输出/Token 可查
> - **HITL 人工干预闭环**：支持批准发布 / 重写 / 重分析 / 重采集四按钮干预 + 自由文本修正，系统追踪反馈改善率
> - **DynamicBlock 动态 Schema + 行业自适应**：三层 Schema 模型（通用固定 + 行业专属 + LLM 自适应），前端自动渲染表格、柱状图、洞察卡片

## 端到端使用流程

1. 用户进入竞品分析页面，输入自然语言 query（例如"对比 Notion、Confluence 和飞书文档的协作能力，重点分析定价策略"），竞品名称可留空由 AI 自动识别
2. Orchestrator Agent 解析语义意图，完成产品名提取、竞品补全、复杂度判定、维度权重分配
3. Collector Agent 并行搜索多源数据（Tavily + Jina），逐产品逐维度采集，前端实时展示搜索进度
4. Analyst Agent 执行多维度对比分析，生成 SWOT 矩阵、趋势预测与 DynamicBlock
5. Reviewer Agent 对分析结果进行事实校验与完整性审查（8 项 gap 检测），不合格则打回重做（最多 2 轮）
6. Writer Agent 将通过校验的分析结果整合为结构化竞品报告（ReportData），内联来源标注
7. 用户查看完整报告，支持 DAG 执行图回放、溯源跳转、人工修正、版本对比、导出下载

---

# 三、交付材料

| 材料类型 | 链接 / 说明 |
|----------|------------|
| **在线 Demo** | http://121.43.235.19:2026/competition（无需登录，自动使用体验账号） |
| **演示视频** | （待录制，建议 5-8 分钟，展示核心场景、关键功能、亮点与结果） |
| **源代码仓库** | https://github.com/wugang-cn/ci-agent |
| **README** | 见仓库根目录 README.md，含项目简介、依赖环境、Docker 启动步骤、目录结构、配置说明 |

> **注意：** 请确保 Demo 链接可直接访问，无需额外权限申请。如需登录，请提供体验账号或以录屏视频替代。

---

# 四、技术说明

## 系统架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                      Nginx (:2026) — 反向代理                     │
└────────────┬─────────────────────────────────┬───────────────────┘
             │ /api/*                           │ /*
             ▼                                  ▼
┌──────────────────────────────┐  ┌──────────────────────────────────┐
│  Backend Gateway (:8001)     │  │  Frontend Next.js 16 (:3000)      │
│  FastAPI + LangGraph Runtime │  │  React 19 + TypeScript            │
│                              │  │  Tailwind CSS 4 + shadcn/ui       │
│  ┌────────────────────────┐  │  │                                   │
│  │ Competition Router     │  │  │  ┌─────────────────────────────┐  │
│  │ POST /analyze          │  │  │  │ Competition Pages            │  │
│  │ GET  /report/{id}      │  │  │  │ /competition/[thread_id]     │  │
│  │ GET  /stream/{id}      │  │  │  │ - DAG Graph (ReactFlow)     │  │
│  │ PATCH /report/{id}     │  │  │  │ - Branch Tree Panel         │  │
│  └───────────┬────────────┘  │  │  │ - Process Trace Panel       │  │
│              │               │  │  │ - Report Editor             │  │
│  ┌───────────▼────────────┐  │  │  │ - Report Cards (per-version)│  │
│  │ LangGraph StateGraph    │  │  │  └─────────────────────────────┘  │
│  │                        │  │  └──────────────────────────────────┘
│  │ Orchestrator ──┐       │  │
│  │     │          │       │  │
│  │     ▼          │       │  │
│  │ Collector ──┐  │       │  │
│  │     │       │  │       │  │
│  │     ▼       │  │       │  │
│  │  Analyst    │  │       │  │
│  │     │       │  │       │  │
│  │     ▼       │  │       │  │
│  │  Reviewer ──┘  │       │  │
│  │     │  (gap)   │       │  │
│  │     ▼          │       │  │
│  │   Writer ◄─────┘       │  │
│  │     │    (rewrite)     │  │
│  │     ▼                  │  │
│  │  HITL Gate             │  │
│  │  approve / replan /    │  │
│  │  reanalyze / rewrite   │  │
│  └───────────┬────────────┘  │
└──────────────┼───────────────┘
               │
    ┌──────────▼──────────┐  ┌──────────────────────┐
    │   Tavily Search API  │  │  Doubao LLM (方舟)    │
    │   Jina Reader API    │  │  DeepSeek / Qwen /    │
    │   DuckDuckGo (ddgs)  │  │  Gemini (备用)        │
    └─────────────────────┘  └──────────────────────┘
               │
    ┌──────────▼──────────┐
    │  SQLite              │
    │  - checkpoints       │
    │  - analysis_history  │
    │  - phase_history     │
    │  - branch_snapshots  │
    │  - source_credibility│
    │  - product_baseline  │
    └─────────────────────┘
```

## 核心技术栈

| 层级 | 技术选型 |
|------|---------|
| **前端** | Next.js 16 (Turbopack) + React 19 + TypeScript 5.8 + Tailwind CSS 4 + shadcn/ui + ReactFlow (@xyflow/react) + react-markdown |
| **后端** | Python 3.12 + FastAPI + LangGraph 1.1+ + langchain-openai + Pydantic 2.x |
| **Agent 编排** | LangGraph StateGraph 单图 + 条件路由反馈闭环，6 节点（Orchestrator / Collector / Analyst / Reviewer / Writer / ErrorHandler），固定边 + 条件边组合 |
| **大模型** | 主推理：Doubao-Seed-2.0-lite（方舟 API）；备用：DeepSeek V4 Flash/Pro、Qwen 3.6 Plus/Flash/Max、Gemini 3 Flash/2.5 Pro（共 12 个模型配置） |
| **搜索 / 采集** | Tavily Search API + Jina Reader API + DuckDuckGo (ddgs)，支持并行搜索（ThreadPoolExecutor 并发） |
| **数据库** | SQLite（LangGraph checkpoints + 6 张业务表：analysis_history / phase_history / branch_snapshots / source_credibility / product_baseline / deliverable_branches） |
| **部署** | Docker Compose + Nginx 反向代理，单机部署即可运行（服务器内存需求 ≥ 4GB） |
| **可观测** | 自建 SSE 流式事件系统 + Per-Agent Token 统计 + DAG 节点 5 状态可视化 + Phase 级别独立计时 |

## 大模型 / AI 能力使用说明

**模型调用方案：**

- 主模型：Doubao-Seed-2.0-lite（方舟 API）
- 调用方式：langchain-openai ChatOpenAI，兼容 OpenAI 协议
- 用途：5 个 Agent 全部推理任务（意图解析、数据提取、多维对比、质量审查、报告生成）
- 备用模型：DeepSeek V4 Flash/Pro、Qwen 3.6 Plus/Flash/Max、Gemini 3 Flash/2.5 Pro、Kimi K2.5、GLM 5.1（主模型故障时自动切换）

**Agent 设计方案：**

- 编排框架：LangGraph StateGraph — 6 节点固定 DAG + 条件路由反馈闭环
- 通信协议：Agent 间通过 Pydantic Schema 结构化 JSON 通信（OrchestrationResult / CollectedData / AnalysisResult / ReviewVerdict / ReportData），非纯自然语言
- Schema 强制校验：每个 Agent 输出经 `model_validate()` 校验，失败自动重试 2 次 + 降级兜底
- 反馈机制：Reviewer 8 项 gap 检测 → 自动打回重做（最多 2 轮），追踪 improvement_ratio
- Prompt 方案：每个 Agent 独立 Markdown Prompt 文件（`prompts/*.md`），Orchestrator 动态调整下游 Agent 的 Prompt 注入

## 关键工程难点与解决方案

| 难点 | 解决方案 |
|------|---------|
| **Agent 间上下文传递与超长内容管理** | Collector 输出按产品+维度分层组织，Analyst 逐产品逐维度分析而非全量压入；LangGraph State 使用 `op_add` 累加器；超长来源内容分片处理，Analyst 只接收摘要+关键数据点 |
| **低 IOPS 云盘下的前端构建稳定性** | 自研 `restart-light.sh` 智能构建脚本：检查 src/ 文件 mtime，源码无变化跳过 build（减少 90%+ 构建次数）；`eatmydata` 拦截所有 fsync/O_SYNC 消除同步写；`ionice -c 2 -n 7` + `nice -n 10` 降低 IO/CPU 优先级 |
| **SSE 流式推送的 Nginx 代理兼容** | Nginx 对该 location 设置 `proxy_buffering off`；后端 asyncio.Queue + `call_soon_threadsafe` 线程安全事件发射；前端 EventSource 断线自动重连 + 轮询降级兜底 |
| **多版本报告管理与分支回溯** | 自研 BranchTree 系统：独立于 LangGraph checkpoint tree 的用户交互分支树，通过 CheckpointOps 与 LangGraph 双向桥接；前端多版本卡片架构，按 parent_version 分组展示，支持同级版本导航和历史 fork |

## 部署与访问说明

1. **在线 Demo**：部署于阿里云 ECS 服务器，`http://121.43.235.19:2026/competition`，自动登录体验账号，评委可直接访问体验
2. **Docker 本地部署**：`git clone` → `docker compose up -d` → 访问 `http://localhost:2026/competition`
3. **手动启动**：`./scripts/restart-light.sh`（智能检测源码变更，跳过无变化的前端 build，节约 IO）
4. 无需额外配置 API Key — `.env` 已内置搜索和大模型密钥

---

# 五、结果说明

## 项目完成度

> **当前状态：已部署可体验版本**
>
> 系统已完成全部核心功能开发，支持端到端的竞品分析流程。竞赛要求中的全部必选项均已实现：
> - ✅ 4 角色 Agent 职责边界清晰 + Orchestrator 动态 Pipeline
> - ✅ 知识结构化 Schema（FeatureTree / PricingModel / UserPersona）+ 强制校验
> - ✅ DAG 协作反馈闭环（8 项 gap 检测，最多 2 轮打回）
> - ✅ 信息溯源（`[n]` 内联标注 + Source Card hover + 一键跳转）
> - ✅ 全链路可观测（DAG 图 / Agent 详情 / Token 统计 / SSE 时间轴）
> - ✅ HITL 人工干预（4 按钮 + 自由文本 + 改善率追踪）
> - ✅ 采集合规（robots.txt 预检 / 来源声明 / 数据脱敏）
> - ✅ 幻觉抑制（引用强制 + 自一致性 + 超长分片）
> - ✅ 错误恢复（per-Agent 超时 + 指数退避 + 降级）

## 项目亮点 / 创新点

> **亮点 1：Agent 工作流分支树 (BranchTree) — Python 生态首创**
>
> 类似 Git 的 Agent 执行分支管理。用户可从任意历史版本 fork 新分支，系统自动追踪 lineage、支持分支对比和 LLM 智能合并。底层 CheckpointOps 封装 LangGraph checkpoint 裸 API 为原子操作层，填补 Python LangGraph 生态的工具空白（JS SDK 有 `getBranchSequence`，Python 端无等价物）。

> **亮点 2：Query-Driven Dynamic Pipeline（Orchestrator Agent）**
>
> 传统 Agent 系统 pipeline 固定（"搜索 → 分析 → 审查 → 报告"一成不变），我们引入 Orchestrator Agent 单次 LLM 调用完成语义意图解析 → 复杂度判定 → 维度权重分配 → Schema 裁剪，实现 pipeline 的动态塑形。例如"对比三款产品的定价"和"分析全球 Top 5 的战略定位"会触发完全不同的搜索预算、维度权重和报告结构。

> **亮点 3：三层 Schema 模型 + DynamicBlock**
>
> Layer 1 通用固定 Section（6 个 baseline）→ Layer 2 行业专属 Section（SaaS/硬件/游戏 profile）→ Layer 3 LLM 自适应 DynamicBlock（kv_list / comparison_table / stat_chart / insight_text 四种类型）。兼顾输出一致性和行业灵活性，前端自动渲染表格/柱状图/洞察卡片。

---

# 六、选填补充材料

| 材料类别 | 材料名称 | 说明 / 链接 |
|----------|---------|------------|
| 产品材料 | 项目讲解 PPT | （待制作，答辩用） |
| 产品材料 | 产品截图 | `#DEMO/` 目录，含关键页面截图与录屏 |
| 技术材料 | API 接口文档 | 后端 FastAPI 自动生成 Swagger（访问 `/docs`） |
| 技术材料 | 数据库 ER 图 | 见 COMPETITION_PLAN.md §3.14 数据持久化架构 |
| AI 材料 | Prompt 策略文档 | `backend/packages/competition/prompts/` 目录，含 5 个 Agent 完整 Prompt |
| AI 材料 | 评测方案与样例 | `backend/tests/` 40 个测试文件，覆盖 Schema 校验 / DAG / 路由 / Agent 节点 / 分支树 / 可观测性 |
| AI 材料 | Agent 自评估机制 | 每个 Agent 完成时自动输出自评分数（覆盖/交叉验证/章节完整率），DAG 节点旁绿/黄/红圆点可视化 |
| 业务材料 | 场景落地设想 | 产品经理竞品调研、战略部门市场分析、投资机构行业扫描。通过切换 SaaS/硬件/游戏 profile 适配不同领域 |
| 过程材料 | 开发里程碑 | COMPETITION_TODO.md（19 个章节，300+ 子任务全部完成），Git 提交 40+ commits |
| 过程材料 | 架构设计文档 | COMPETITION_PLAN.md（~6000 行完整技术方案，含 DAG 设计 / Schema 设计 / 分支树设计 / 部署方案） |

---

# 七、合规声明

> **合规确认：**
>
> - ✅ 信息采集遵守目标站点 robots.txt 与服务条款，所有数据来源均为公开信息（通过 Tavily / Jina 官方 API）
> - ✅ 采集前自动执行 robots.txt 预检，不符合规则的站点跳过采集
> - ✅ 问卷 / 访谈数据已脱敏处理，PII 自动检测与匿名化（姓名 / 公司名 / 联系方式自动替换）
> - ✅ 工具、模型、数据的使用符合比赛规范要求（所有开源依赖 MIT / Apache 2.0 协议）
> - ✅ 未使用任何受版权保护的非授权内容
> - ✅ 所有 LLM 调用通过官方 API（方舟 / DashScope / DeepSeek / Gemini），密钥通过环境变量管理，代码中无硬编码明文密钥
