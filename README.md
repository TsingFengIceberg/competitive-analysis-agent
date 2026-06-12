<p align="center">
  <img src="images/logo.png" alt="Competitive-Analysis-Agent" width="80" />
</p>

<h1 align="center">Competitive-Analysis-Agent</h1>

AI 驱动的竞品分析 Agent 协作系统

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-ff6f00?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19-61dafb?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178c6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003b57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ed?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

## 目录

- [定位](#定位)
- [架构概览](#架构概览)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置](#配置)
- [运行示例](#运行示例)
- [目录结构](#目录结构)
- [API 接口](#api-接口)
- [竞赛要求覆盖](#竞赛要求覆盖)
- [License](#license)

## 定位

Competitive-Analysis-Agent 是一个"数字竞争情报小组"——6 个专门化 AI Agent 以结构化协作协议完成竞品数据采集、交叉验证、多维对比分析和交互式报告生成。全程可溯源、可干预、可交互。

---

## 架构概览

![系统架构图](images/architecture.png)

### 6 个 Agent 角色

| Agent | 职责 | 输出 |
|-------|------|------|
| **Orchestrator** | 意图解析 + 复杂度判定 + 维度权重 + 动态 Schema（深度 × 行业） | `OrchestrationResult` |
| **Collector** | 多源搜索采集 + 去重 + 自评覆盖率 + VoC 问卷生成 | `CollectedDataPoint[]` |
| **Analyst** | 对比矩阵 + SWOT + 趋势预测 + 动态维度 | `AnalysisResult` |
| **Reviewer** | 8 项质量审查 + gap 判定 + 打回重做 | `ReviewVerdict` |
| **Writer** | 结构化报告生成 + 双视角 + `[n]` 溯源标注 | `ReportData` |
| **HITL Gate** | 人工审批：批准 / 重写 / 重分析 / 重采集 | `HitlDecision` |

Agent 间通过 **结构化 Pydantic Schema** 通信（非纯自然语言），每个环节的 Prompt、输入、输出均可在前端流程追踪面板中查看。

---

## 核心特性

### 反馈闭环

Reviewer 执行 **8 项质量审查**（数据覆盖、交叉验证、来源可信度、时间新鲜度、维度完整性等）+ **数字源头校验**（claim 中数字须在采集原文逐字可查），发现 gap 即打回 Collector/Analyst 重做，**最多 2 轮**。打回时精准定位缺失维度，**定向补采**而非全量重跑，减少 Token 消耗。每次重做后追踪改善率 + **修复增量**（repair delta），确保闭环真实可触发而非伪闭环。

### 信息溯源

每条分析结论标注 `[n]` 上标来源，hover 弹出 source card（URL、采集时间、置信度、验证状态），支持一键跳转到原始数据源。来源按域名历史可信度自动分为**强/中/弱**三档证据强度，低可信来源自动降权。

### 分支树 BranchTree

Agent 执行过程版本化管理——每次 HITL 干预创建新分支，支持从任意历史版本 fork、版本对比、分支合并。类似 Git for Agent workflow。

### 动态 Schema

3 层 Schema 模型：通用固定层 + 行业专属层 + LLM 自适应动态层。Orchestrator 根据 query 复杂度和行业类型自动选择报告深度与专属分析维度。

### 可观测面板

- **DAG 执行图**: 节点 5 状态高亮 + 边动画 + 反馈回环虚线 + 自评分数圆点
- **流程追踪**: 每节点 Prompt / 输入 / 输出 / Token / 结构化 JSON 可查
- **溯源链视图**: 报告结论 ↔ 原始数据源一键跳转
- **人工修正面板**: 报告章节在线编辑 + 提交改善率量化

### 来源可信度动态演化

每个数据源的域名维护可信度分数（0-1），Reviewer 每次校验后根据结果（verified/conflict/error/outdated）自动调分，跨分析 session 累积演化。采集时自动**持久化页面全文**，下游 Agent 可回溯原文验证 claim，不做仅靠摘要的二手判断。

### Agent 可靠性

内置**熔断器**（连续 3 次重复调用自动中断）防止 LLM 死循环烧 Token，per-Agent 超时 + 降级兜底保证单点故障不阻塞整体流程。

### 项目偏好配置

`profile.md` 定义分析风格、维度权重、来源规则等持久化偏好，Orchestrator 启动时自动注入 Prompt，跨 session 保持一致性。

### 飞书消息推送

分析完成后自动通过飞书应用机器人推送私聊通知，包含报告标题与产品名。配置可选，不影响分析主流程。

---

## 技术栈

| 层 | 技术 |
|---|------|
| **编排** | LangGraph StateGraph + 条件路由 + 反馈闭环 |
| **后端** | Python 3.12 + FastAPI + Pydantic v2 + SQLite |
| **前端** | Next.js 16 + React 19 + TypeScript + Tailwind CSS 4 + [DeerFlow](https://github.com/bytedance/deer-flow)（auth / i18n / UI 组件） |
| **DAG 可视化** | [@xyflow/react](https://reactflow.dev/) (ReactFlow) |
| **LLM** | OpenAI 兼容 API |
| **搜索** | Tavily / DuckDuckGo / Jina AI / LLM 内置联网搜索 |
| **部署** | Docker Compose + Nginx 反向代理 |
| **持久化** | SQLite (WAL mode): analysis_history + phase_history + source_credibility + product_baseline + branch_snapshots |

---

## 快速开始

### 环境要求

| | 方式一 (Make) | 方式二 (Docker) | 方式三 (手动) |
|---|:---:|:---:|:---:|
| Docker + Docker Compose | | ● | |
| Node.js 22+ | ● | | ● |
| Python 3.12+ | ● | | ● |
| uv (Python 包管理器) | ● | | ● |
| pnpm | ● | | ● |
| nginx | ● | | ● |

三种方式任选其一即可，最终均访问 `http://localhost:2026/competition`。

### 方式一：Make 命令（推荐）

```bash
cp .env.example .env    # 编辑填写 DOUBAO_API_KEY 等
make install            # 安装依赖
make start              # 启动全部服务
```

常用命令：

```bash
make stop               # 停止
make restart            # 重启
make test               # 运行测试
make lint               # 代码检查
make build              # 重新构建前端
```

### 方式二：Docker Compose

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yaml up -d
```

常用命令：

```bash
docker compose -f docker/docker-compose.yaml down          # 停止
docker compose -f docker/docker-compose.yaml logs -f       # 日志
docker compose -f docker/docker-compose.yaml up -d --build # 重建
```

### 方式三：手动脚本

```bash
# 安装（在项目根目录执行）
cd backend && uv sync
cd ../frontend && pnpm install
cd ..

# 配置
cp .env.example .env && source .env

# 一键启动
./scripts/restart-light.sh              # 启动全部
./scripts/restart-light.sh --backend    # 仅后端
./scripts/restart-light.sh --frontend   # 仅前端（自动检测源码变更）

# 调试实例（独立端口 :8002/:3001/:2027，不影响生产实例）
./scripts/dev-instance.sh start
./scripts/dev-instance.sh stop
```

---

## 配置

项目配置分为两层：**`.env`** 提供 API 密钥（必须填写），**`config.yaml`** 提供 Agent 级别的模型和参数调优（所有字段均有内置默认值，不创建也能运行）。

### .env

所有 API 密钥和 LLM 连接信息通过环境变量注入。从模板复制并填写：

```bash
cp .env.example .env
```

**核心变量：**

| 变量 | 必填 | 说明 |
|------|:---:|------|
| `DOUBAO_API_KEY` | ● | 豆包方舟 API 密钥 |
| `DOUBAO_API_BASE` | ● | API 地址，默认 `https://ark.cn-beijing.volces.com/api/v3` |
| `DOUBAO_MODEL` | ● | 所有 Agent 共用的默认模型 |
| `TAVILY_API_KEY` | | 搜索 API 密钥（Tavily） |
| `JINA_API_KEY` | | 网页抓取 API 密钥（Jina AI） |

支持接入其他 OpenAI 兼容的 LLM 提供商（DeepSeek、Qwen、Gemini 等），只需修改 `DOUBAO_API_KEY`、`DOUBAO_API_BASE`、`DOUBAO_MODEL` 三个变量指向对应服务的地址和密钥即可。

搜索类密钥（`TAVILY_API_KEY`、`JINA_API_KEY`）未填写时，系统自动退化为 DuckDuckGo 免费搜索。

### config.yaml

所有字段均有内置默认值，无需创建即可运行。如需为不同 Agent 分配不同模型或调整超时/工具集，从模板复制：

```bash
cp config.example.yaml config.yaml
```

`config.yaml` 中 `competition` 段可为每个 Agent 单独配置模型、超时、工具集等参数：

```yaml
competition:
  default_model: "doubao-seed-2-0-lite-260215"

  orchestrator:
    model: "doubao-seed-2-0-lite-260215"   # 意图解析（单次调用，轻量模型即可）
    timeout_seconds: 60

  collector:
    model: "doubao-seed-2-0-lite-260215"   # 多源搜索采集（建议用强搜索模型）
    max_turns: 30
    timeout_seconds: 600

  analyst:
    model: "doubao-seed-2-0-lite-260215"   # 对比分析 + SWOT（建议用推理强模型）
    max_turns: 20

  reviewer:
    model: "doubao-seed-2-0-lite-260215"   # 质量审查（轻量模型即可）
    max_feedback_rounds: 2                 # 最多打回重做轮数

  writer:
    model: "doubao-seed-2-0-lite-260215"   # 报告生成（建议用长文模型）
    executive_summary_max_chars: 500

  hitl:
    approval_timeout_minutes: 30
```

**当前状态说明：** `config.yaml` 中每个 Agent 的 `model` 字段已定义但尚未接入路由层。目前所有 Agent **统一使用 `.env` 中 `DOUBAO_MODEL` 指定的模型**。如需为不同 Agent 分配不同模型（例如 Collector 用搜索强模型、Writer 用长文模型），可先在 `config.yaml` 中预配置，后续路由层接入后即时生效。

### 飞书消息推送（可选）

分析完成后通过飞书应用机器人推送私聊通知。

**前提准备**：

1. 登录 [飞书开放平台](https://open.feishu.cn/app) → 创建「企业自建应用」
2. 添加应用能力 → 开启「机器人」
3. 权限管理 → 添加 `im:message:send_as_bot` → 发布新版本

**获取配置变量**：

| 变量 | 说明 | 获取方式 |
|------|------|---------|
| `FEISHU_APP_ID` | 应用 ID | 应用详情页 → 凭证与基础信息 |
| `FEISHU_APP_SECRET` | 应用密钥 | 同上 |
| `FEISHU_NOTIFY_OPEN_ID` | 通知接收人 Open ID | API 调试台 → 发送消息接口 → 快速复制 open_id |

填入 `.env`：

```bash
FEISHU_APP_ID=your-feishu-app-id
FEISHU_APP_SECRET=your-feishu-app-secret
FEISHU_NOTIFY_OPEN_ID=your-feishu-open-id
```

### 配置文件位置

两项配置均放在**项目根目录**：

```
competitive-analysis-agent/
├── .env               # API 密钥（不提交 Git）
├── config.yaml        # Agent 参数调优（不提交 Git）
├── .env.example       # 密钥模板（可提交）
└── config.example.yaml # 参数模板（可提交）
```

---

## 运行示例

> **Query**: "深度分析 Claude Code 和 Codex，特别是定价方面"  
> **Thread**: `comp-05350dc0770f` · 耗时 ~15 分钟 · 总 Token 20,840 · 产出 9 章节报告

### 全流程截图

<table>
<tr>
<td width="50%"><img src="images/sample/01竞品解析.png" width="100%"></td>
<td width="50%"><img src="images/sample/02意图解析.png" width="100%"></td>
</tr>
<tr>
<td align="center" width="50%"><b>竞品解析</b> — 产品名识别 + 纠错</td>
<td align="center" width="50%"><b>意图解析</b> — Orchestrator 判定 standard 模式</td>
</tr>
<tr>
<td width="50%"><img src="images/sample/03信息采集.png" width="100%"></td>
<td width="50%"><img src="images/sample/04信息分析1.png" width="100%"></td>
</tr>
<tr>
<td align="center" width="50%"><b>信息采集</b> — 多源搜索 12 条结构化数据点</td>
<td align="center" width="50%"><b>对比分析</b> — 功能 × 定价 × 用户 × 市场矩阵</td>
</tr>
<tr>
<td width="50%"><img src="images/sample/04信息分析2.png" width="100%"></td>
<td width="50%"><img src="images/sample/05质量审查.png" width="100%"></td>
</tr>
<tr>
<td align="center" width="50%"><b>SWOT + 趋势</b> — 预测推演 + What-if</td>
<td align="center" width="50%"><b>质量审查</b> — G7 语义矛盾检测 + 定向返工</td>
</tr>
<tr>
<td width="50%"><img src="images/sample/06报告卡片.png" width="100%"></td>
<td width="50%"><img src="images/sample/07报告展开.png" width="100%"></td>
</tr>
<tr>
<td align="center" width="50%"><b>报告卡片</b> — 指标条 + 证据强度 + 可折叠</td>
<td align="center" width="50%"><b>报告展开</b> — 内联溯源 [n] + DAG 图 + 追踪面板</td>
</tr>
<tr>
<td width="50%"><img src="images/sample/08人工修正.png" width="100%"></td>
<td width="50%"><img src="images/sample/09重采集.png" width="100%"></td>
</tr>
<tr>
<td align="center" width="50%"><b>人工修正</b> — 就地编辑 + 改善率追踪</td>
<td align="center" width="50%"><b>重采集 / 重分析</b> — HITL 四按钮干预</td>
</tr>
<tr>
<td width="50%"><img src="images/sample/09重分析.png" width="100%"></td>
<td width="50%"><img src="images/sample/10报告版本分支树.png" width="100%"></td>
</tr>
<tr>
<td align="center" width="50%"><b>重分析结果</b> — 版本间指标对比</td>
<td align="center" width="50%"><b>分支树</b> — v1 初始分析 → v2 重分析</td>
</tr>
</table>

<p align="center">
  <img src="images/sample/11会话界面总览.png" width="80%"><br/>
  <b>会话界面总览</b> — 左侧阶段气泡 + 中间报告卡片 + 右侧面板
</p>

### 内部流转



| 阶段 | Agent | 耗时 | Token | 关键产出 |
|------|-------|------|-------|---------|
| 🔍 竞品解析 | (前置) | 125s | 1,713 | "Claude Code" → Claude Code (Anthropic) |
| 🎯 意图解析 | Orchestrator | 12s | 51 | complexity=standard, 定价权重 0.9 |
| 📊 信息采集 | Collector | 259s | 4,002 | 12 条结构化数据点 (products×dimensions) |
| 🔬 对比分析 | Analyst | 66s | 3,529 | 2×4 对比矩阵 + SWOT + 趋势预测 |
| ✅ 质量审查 | Reviewer | 97s | 10,591 | G1-G8 8 项检查, 发现 3 个 gap |
| 🔄 定向返工 | Analyst→Reviewer | 71s+34s | — | 补采缺失维度, 交叉验证通过 |
| 📝 报告撰写 | Writer | 264s | 954 | 9 章节: 摘要·矩阵·SWOT·趋势·建议 |
| 📋 **合计** | — | **~15min** | **20,840** | **覆盖率 100% · 溯源率 100%** |

> **关键指标**: 交叉验证率 0%（初版已知 Bug，已修复）· 改善率 80% · 9 章节约 3,000 字 · 溯源链接 12 条

### 定向返工闭环

当 Reviewer 检测到数据覆盖不足时，系统自动触发**定向返工**——精确指定缺失的产品×维度组合，Collector **只补采缺口数据**而非全量重跑：

```
Collector → Analyst → Reviewer
              ↑          │
              │          ├─ pass → Writer → HITL Gate
              │          └─ gap → rework_plan: {product: "Claude Code", dimension: "pricing"}
              │                    │
              └────────────────────┘ (定向补采, 非全量重跑)
```

本示例中，Reviewer 识别到 3 个 gap 后触发 1 轮定向返工，改善率提升至 80%。

---

## 目录结构

```
competitive-analysis-agent/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 应用入口 + auth stub
│   │   └── competition_router.py      # /analyze /report /trace /stream 路由
│   ├── packages/competition/          # 竞赛核心包
│   │   └── competition/
│   │       ├── nodes/                 # 6 个 Agent 节点实现
│   │       │   ├── orchestrator.py    # Orchestrator: 意图解析 + 路由决策
│   │       │   ├── collector.py       # Collector: 多源采集 + VoC
│   │       │   ├── analyst.py         # Analyst: 对比分析 + SWOT + 趋势
│   │       │   ├── reviewer.py        # Reviewer: 8 项质量审查 + gap 判定
│   │       │   ├── writer.py          # Writer: 报告生成 + 溯源标注
│   │       │   ├── hitl_gate.py       # HITL Gate: LangGraph interrupt()
│   │       │   ├── error_handler.py   # 错误处理 + 降级
│   │       │   └── deep_*.py          # 深度模式节点 (deep 模式)
│   │       ├── tools/                 # Agent 工具
│   │       │   ├── search.py          # 多源搜索 (Tavily / DDG / Jina)
│   │       │   └── video_source.py    # YouTube / Bilibili 字幕提取
│   │       ├── prompts/               # Agent 提示词 (Markdown, 每个 Agent 一篇)
│   │       ├── branchtree/            # 分支树 + CheckpointOps
│   │       │   ├── tree.py            # BranchTree: snapshot / fork / restore / lineage
│   │       │   ├── node.py            # BranchNode 数据结构
│   │       │   ├── store.py           # SQLite 持久化 (branch_snapshots 表)
│   │       │   ├── checkpoint_ops.py  # LangGraph checkpoint 便捷操作
│   │       │   ├── adapter.py         # State ↔ BranchTree 双向桥接
│   │       │   ├── diff.py            # 节点/版本对比
│   │       │   └── merge.py           # 分支合并
│   │       ├── graph.py               # LangGraph StateGraph 构建
│   │       ├── state.py               # CompetitionState 定义
│   │       ├── schema.py              # Pydantic Schema + 校验
│   │       ├── router.py              # 条件路由逻辑
│   │       ├── dag.py                 # DAG 状态提取器
│   │       ├── db.py                  # SQLite 业务表 (4 张)
│   │       ├── executor.py            # LLM 调用封装
│   │       ├── graph_algorithms.py    # 图拓扑算法
│   │       ├── industry.py            # 行业 profile 定义
│   │       ├── config.py              # 配置模型
│   │       ├── visualization.py       # matplotlib/seaborn 图表
│   │       └── observability.py       # 可观测性工具
│   ├── tests/                         # 后端测试
│   ├── pyproject.toml                 # Python 项目配置 (uv workspace)
│   └── uv.lock                        # 依赖锁定
├── frontend/
│   └── src/
│       ├── app/competition/           # /competition 路由页面
│       │   ├── layout.tsx             # 根布局
│       │   ├── page.tsx               # 首页 (新建分析)
│       │   └── [thread_id]/           # 分析详情页 (动态路由)
│       ├── app/api/competition/       # SSE 流代理端点
│       └── components/competition/    # 19 个竞赛 UI 组件
│           ├── competition-chat-area.tsx       # 主聊天区
│           ├── competition-report-panel.tsx    # 报告面板
│           ├── competition-report-card.tsx     # 报告卡片
│           ├── dag-graph.tsx                   # DAG 执行图
│           ├── process-trace-panel.tsx         # 流程追踪面板
│           ├── report-editor.tsx               # 人工修正编辑器
│           ├── branch-tree-panel.tsx           # 分支树面板
│           ├── source-card.tsx                 # 溯源卡片 (hover 弹窗)
│           ├── hitl-card.tsx                   # HITL 审批卡片
│           ├── agent-detail-panel.tsx          # Agent 节点详情
│           ├── analysis-timeline.tsx           # 分析时间线
│           ├── message-flow-timeline.tsx       # 消息流时间线
│           ├── token-panel.tsx                 # Token 消耗面板
│           ├── version-tree.tsx                # 版本树
│           ├── competition-header.tsx          # 顶部导航栏
│           ├── competition-sidebar.tsx         # 侧边栏
│           ├── competition-history-list.tsx    # 历史记录列表
│           ├── competition-query-input.tsx     # 查询输入框
│           └── replay-slider.tsx               # 回放滑块
├── scripts/
│   ├── restart-light.sh               # 生产实例一键重启（含 IO 防护）
│   ├── dev-instance.sh                # 调试实例启动（:8002/:3001/:2027）
│   └── cleanup-all.sh                 # 进程 + 端口清理
├── docker/
│   ├── docker-compose.yaml            # 生产部署
│   ├── docker-compose-dev.yaml        # 开发部署
│   ├── dev-entrypoint.sh              # 开发容器入口
│   ├── nginx/                         # Nginx 配置
│   └── provisioner/                   # Sandbox 资源预配器
├── images/                            # 文档图片
├── .env.example                       # 环境变量模板
├── config.example.yaml                # Agent 配置模板
├── Makefile                           # 构建/启动/测试快捷命令
└── README.md
```

---

## 竞赛要求覆盖

| 要求 | 描述 | 实现位置 |
|------|------|---------|
| R1 | 6 Agent 职责边界清晰 | `nodes/orchestrator.py` `collector.py` `analyst.py` `reviewer.py` `writer.py` `hitl_gate.py` |
| R2 | Collector 双轨采集 + 问卷 | `nodes/collector.py` VoC Aggregator |
| R3 | 竞品知识 Schema (FeatureTree/PricingModel/UserPersona) | `schema.py` |
| R4 | Agent 间结构化 JSON 通信 | `schema.py` AnalysisResult/ReviewVerdict/ReviewPackage/ReportData/HitlDecision |
| R5 | Reviewer 8 项 gap 判定 + 打回 | `nodes/reviewer.py` + `router.py` |
| R6 | 反馈改善率量化 | `competition_router.py` improvement_ratio |
| R7 | 溯源标注 `[n]` + traceability_map | `nodes/writer.py` + 前端 `source-card.tsx` |
| R8 | Schema 强制校验 + 重试 + 降级 | `schema.py` model_validate() |
| R9 | DAG 图实时高亮 + 边动画 | `dag.py` + 前端 `dag-graph.tsx` |
| R10 | Prompt/输入/输出/决策过程/Token 可查 | 前端 `process-trace-panel.tsx` + `agent-detail-panel.tsx` + `competition_router.py` /trace |
| R11 | 端到端链路完整，可现场演示 | `graph.py` 全链路编排 + `competition_router.py` SSE 流式 + 前端完整交互 |
| R12 | 幻觉抑制：引用强制 + 自一致性 + 分片 | `nodes/reviewer.py` + `nodes/analyst.py` |
| R13 | 超时重试 + 降级机制 | `config.py` per-Agent timeout + `nodes/error_handler.py` C/D 级错误决策树 |
| R14 | 前瞻性：BranchTree + CheckpointOps + 来源可信度 | `branchtree/` + `db.py` source_credibility |
| R15 | 输出指标可量化（覆盖率/交叉验证率/改善率） | `nodes/writer.py` compute_metrics() + `schema.py` metrics |

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/competition/analyze` | 创建竞品分析任务，返回 thread_id |
| GET | `/api/competition/stream/{thread_id}` | SSE 实时事件流（进度推送 + Agent 输出） |
| GET | `/api/competition/report/{thread_id}` | 获取分析报告与阶段数据 |
| GET | `/api/competition/report/{thread_id}/history` | 获取版本历史与分支树 |
| GET | `/api/competition/report/{thread_id}/trace` | 获取 Agent 执行追踪日志 |
| PATCH | `/api/competition/report/{thread_id}/sections` | 人工修正报告章节 |
| PUT | `/api/competition/report/{thread_id}` | 提交 HITL 审批决策 |
| POST | `/api/competition/{thread_id}/cancel` | 终止运行中的分析 |
| GET | `/api/competition/report/{thread_id}/export` | 导出报告（Markdown / JSON） |
| GET | `/api/competition/me` | 获取当前用户信息 |
| GET | `/api/competition/history` | 获取历史分析列表 |

后端 FastAPI 自动生成 Swagger 文档：`http://localhost:8001/docs`

---

## License

[MIT](LICENSE)

