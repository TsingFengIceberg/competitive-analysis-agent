<p align="center">
  <img src="frontend/public/logo.png" alt="Competitive-Analysis-Agent" width="80" />
</p>

# Competitive-Analysis-Agent

AI 驱动的竞品分析 Agent 协作系统 — 多智能体竞争情报平台。

> 字节跳动 CIS「AI 全栈项目挑战赛」参赛项目 | 2026-05-20 ~ 2026-06-10

## 定位

Competitive-Analysis-Agent 是一个"数字竞争情报小组"——5 个专门化 AI Agent 以结构化协作协议完成竞品数据采集、交叉验证、多维对比分析和交互式报告生成。全程可溯源、可干预、可交互。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                      前端 (Next.js 16)                    │
│  DAG 执行图 · 流程追踪 · 溯源链 · 人工修正 · 分支树       │
└──────────────────────────┬──────────────────────────────┘
                           │ SSE / REST
┌──────────────────────────▼──────────────────────────────┐
│                   Gateway API (FastAPI)                   │
│              /analyze · /report · /trace · /stream       │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│              LangGraph StateGraph 编排引擎                │
│                                                          │
│  Orchestrator ──▶ Collector ──▶ Analyst ──▶ Reviewer     │
│       │               ▲           │            │         │
│       │               │           │            ▼         │
│       │               └─── gap ───┘         Writer       │
│       │                  (最多2轮)             │          │
│       │                                       ▼          │
│       └───────────────────────────────── HITL Gate       │
│                                          │    │    │     │
│                                     approve replan rewrite│
│                                        │    │    │       │
│                                       END ←┴────┘       │
│                                                          │
│  反馈闭环: 质检打回重做 → 改善率量化 → HITL 人工审批      │
└──────────────────────────────────────────────────────────┘
```

### 5 个 Agent 角色

| Agent | 职责 | 输出 |
|-------|------|------|
| **Orchestrator** | 意图解析 + 复杂度判定 + 维度权重分配 + Schema 裁剪 | `OrchestrationResult` |
| **Collector** | 多源搜索采集 + 去重 + 自评覆盖率 | `CollectedDataPoint[]` |
| **Analyst** | 对比矩阵 + SWOT + 趋势预测 + 动态维度 | `AnalysisResult` |
| **Reviewer** | 8 项质量审查 + gap 判定 + 打回重做 | `ReviewVerdict` |
| **Writer** | 结构化报告生成 + 双视角 + 溯源标注 | `ReportData` |
| **HITL Gate** | 人工审批：批准 / 重写 / 重分析 / 重采集 | `HitlDecision` |

Agent 间通过 **结构化 Pydantic Schema** 通信（非纯自然语言），每个环节的 Prompt、输入、输出均可在前端流程追踪面板中查看。

---

## 核心特性

### 反馈闭环 (R5/R6)

Reviewer 执行 **8 项质量审查**（数据覆盖、交叉验证、来源可信度、时间新鲜度、维度完整性等），发现 gap 即打回 Collector/Analyst 重做，**最多 2 轮**。每次重做后追踪改善率，确保闭环真实可触发而非伪闭环。

### 信息溯源 (R7)

每条分析结论标注 `[n]` 上标来源，hover 弹出 source card（URL、采集时间、置信度、验证状态），支持一键跳转到原始数据源。

### 分支树 BranchTree (核心差异化)

Agent 执行过程版本化管理——每次 HITL 干预创建新分支，支持从任意历史版本 fork、版本对比、分支合并。类似 Git for Agent workflow。

### 动态 Schema (DynamicBlock)

3 层 Schema 模型：通用固定层 + 行业专属层 + LLM 自适应动态层。支持 kv_list / comparison_table / stat_chart / insight_text 四种动态块类型。

### 可观测面板 (R9/R10)

- **DAG 执行图**: 节点 5 状态高亮 + 边动画 + 反馈回环虚线 + 自评分数圆点
- **流程追踪**: 每节点 Prompt / 输入 / 输出 / Token / 结构化 JSON 可查
- **溯源链视图**: 报告结论 ↔ 原始数据源一键跳转
- **人工修正面板**: 报告章节在线编辑 + 提交改善率量化

### 来源可信度动态演化

每个数据源的域名维护可信度分数（0-1），Reviewer 每次校验后根据结果（verified/conflict/error/outdated）自动调分，跨分析 session 累积演化。

---

## 技术栈

| 层 | 技术 |
|---|------|
| **编排** | LangGraph StateGraph + 条件路由 + 反馈闭环 |
| **后端** | Python 3.12 + FastAPI + Pydantic v2 + SQLite |
| **前端** | Next.js 16 + React 19 + TypeScript + Tailwind CSS 4 |
| **DAG 可视化** | @xyflow/react (ReactFlow) |
| **LLM** | OpenAI 兼容 API（支持多模型灵活切换） |
| **搜索** | Tavily / Jina AI / DuckDuckGo |
| **部署** | Docker Compose + Nginx 反向代理 |
| **持久化** | SQLite (WAL mode): analysis_history + phase_history + source_credibility + product_baseline + branch_snapshots |

---

## 快速开始

### 环境要求

- [Docker](https://docs.docker.com/get-docker/) 和 Docker Compose
- （可选）Node.js 22+ / Python 3.12+ 用于本地开发

### Docker 一键部署（推荐）

```bash
# 1. 配置 API Key
cp config.example.yaml config.yaml    # 编辑填写 LLM API Key
cp .env.example .env

# 2. 启动全部服务（后端 + 前端 + Nginx）
docker compose up -d

# 3. 访问
# 打开 http://localhost:2026/competition
```

服务启动后，访问 `http://localhost:2026/competition`，在输入框中输入自然语言竞品分析 query 即可。

常用命令：
```bash
docker compose down          # 停止服务
docker compose logs -f       # 查看日志
docker compose up -d --build # 重新构建并启动
```

### 本地开发启动

```bash
# 1. 安装依赖
cd backend && uv sync
cd frontend && pnpm install

# 2. 启动后端
cd backend && PYTHONPATH=packages/competition uv run uvicorn app.main:app --host 0.0.0.0 --port 8001

# 3. 构建并启动前端
cd frontend && pnpm build && PORT=3000 pnpm start

# 4. 启动 Nginx（或直接访问 localhost:3000）
# 生产推荐使用 Nginx 代理，见 docker/nginx/nginx.conf
```

---

## 目录结构

```
ci-agent/
├── backend/
│   ├── app/gateway/              # FastAPI Gateway + 竞赛路由
│   │   └── routers/competition.py  # /analyze /report /trace /stream
│   ├── packages/competition/     # 竞赛核心代码
│   │   └── competition/
│   │       ├── nodes/            # 5 个 Agent 节点实现
│   │       ├── prompts/          # Agent 提示词 (Markdown)
│   │       ├── graph.py          # LangGraph 图构建
│   │       ├── state.py          # CompetitionState 定义
│   │       ├── schema.py         # Pydantic Schema + 校验
│   │       ├── router.py         # 条件路由逻辑
│   │       ├── dag.py            # DAG 状态提取器
│   │       ├── db.py             # SQLite 业务表
│   │       └── branchtree/       # 分支树 + CheckpointOps
│   └── tests/                    # 后端测试
├── frontend/
│   └── src/
│       ├── app/competition/      # /competition 路由页面
│       └── components/competition/ # 竞赛 UI 组件
├── scripts/                      # 运维脚本
├── docker/                       # Docker 配置
├── config.example.yaml           # 配置模板
└── .env.example                  # 环境变量模板
```

---

## 竞赛要求覆盖

| 要求 | 描述 | 实现位置 |
|------|------|---------|
| R1 | 5 Agent 职责边界清晰 | `nodes/orchestrator.py` `collector.py` `analyst.py` `reviewer.py` `writer.py` |
| R2 | Collector 双轨采集 + 问卷 | `nodes/collector.py` §VoC Aggregator |
| R3 | 竞品知识 Schema (FeatureTree/PricingModel/UserPersona) | `schema.py` |
| R4 | Agent 间结构化 JSON 通信 | `schema.py` §AnalysisResult/ReviewVerdict/ReportData/HitlDecision |
| R5 | Reviewer 8 项 gap 判定 + 打回 | `nodes/reviewer.py` + `router.py` |
| R6 | 反馈改善率量化 | `competition.py` §improvement_ratio |
| R7 | 溯源标注 `[n]` + traceability_map | `nodes/writer.py` + 前端 source-card |
| R8 | Schema 强制校验 + 重试 + 降级 | `schema.py` §model_validate() |
| R9 | DAG 图实时高亮 + 边动画 | `dag.py` + 前端 `dag-graph.tsx` |
| R10 | Prompt/输入/输出/Token 可查 | 前端 `process-trace-panel.tsx` + `competition.py` `/trace` |
| R12 | 幻觉抑制：引用强制 + 自一致性 + 分片 | `nodes/reviewer.py` + `nodes/analyst.py` |
| R14 | 前瞻性：BranchTree + CheckpointOps + 来源可信度 | `branchtree/` + `db.py` §source_credibility |

完整追溯矩阵见 [COMPETITION_TODO.md](./COMPETITION_TODO.md)。

---
