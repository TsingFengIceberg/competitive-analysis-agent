<p align="center">
  <img src="images/logo.png" alt="Competitive-Analysis-Agent" width="80" />
</p>

<h1 align="center">Competitive-Analysis-Agent</h1>

<p align="center"><a href="./README_en.md">English</a> | 中文</p>

<p align="center"><strong>AI 驱动的竞品分析 Agent 协作系统</strong></p>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-ff6f00?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19-61dafb?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178c6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003b57?logo=sqlite&logoColor=white)](https://sqlite.org)

## 目录

- [项目定位](#项目定位)
- [核心能力](#核心能力)
- [架构速览](#架构速览)
- [快速开始](#快速开始)
- [文档导航](#文档导航)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [测试](#测试)
- [License](#license)

## 项目定位

Competitive-Analysis-Agent 将竞品研究拆分为可追踪、可审查、可干预的 Agent 工作流：从自然语言需求出发，完成范围确认、多源采集、证据核验、比较分析、质量审查和报告生成。系统同时支持持续竞品观察、本地知识库/RAG、研究工作台和标准 A2A Provider。

## 核心能力

- **结构化 Agent 协作**：Orchestrator、Collector、Analyst、Reviewer、Writer 和 HITL 通过 Pydantic Schema 协作。
- **分析前范围确认**：竞品、决策目标、维度、权重、行业、时间范围和证据策略在执行前可编辑确认。
- **三层动态维度**：通用候选、行业候选和模型提出的动态维度；用户可删除或调整范围。
- **证据质量闭环**：引用、数字一致性、来源可信度、交叉验证和定向返工均可追踪。
- **研究工作台**：报告版本树、质量门禁、语义核验、来源、证据图谱和流程追踪集中查看。
- **持续竞品观察**：定时增量采集，只有实质变化才触发深度分析，并支持告警和完整历史报告。
- **本地知识库与 RAG**：版本化文档、混合检索、重排、GraphRAG、时间过滤、知识治理和离线评估。
- **可靠性与恢复**：持久化任务队列、调度租约、独立 Worker、取消、重试、降级和 SSE 断线恢复。
- **标准 A2A 互操作**：独立 AgentCard、JSON-RPC、Task、Artifact、标准 SSE 和可替换认证。

## 架构速览

![系统架构图](images/architecture.png)

```text
Next.js UI ── REST/SSE ── FastAPI Gateway
                              │
                       LangGraph Workflow
             Orchestrator → Collector → Analyst
                                  ↓          │
                              Reviewer ←─────┘
                                  ↓
                           Writer → HITL Gate
                              │
                SQLite + Qdrant + Object Storage
                              │
                     A2A Provider (separate adapter)
```

详细的状态契约、版本模型、HITL 和事件设计见[架构与工作流](docs/architecture.md)。

## 快速开始

### 环境要求

Python 3.12+、uv、Node.js 22+、pnpm 10+。

```bash
make install
make dev
```

启动后访问 `http://localhost:2026/competition`。常用命令：

```bash
make stop
make restart
make watch
make start
make test
make lint
make build
```

默认使用 DB 配置模式；调试或演示可执行：

```bash
cp .env.example .env
cp config.example.yaml config.yaml
CI_AGENT_CONFIG_MODE=file make dev
```

端口可通过 `BACKEND_PORT=8002 FRONTEND_PORT=2027 make dev` 覆盖。完整启动、SSH 隧道和排障步骤见[运行与排障](docs/operations.md)。

## 文档导航

| 文档 | 适合阅读场景 |
| --- | --- |
| [架构与工作流](docs/architecture.md) | 理解 Agent 编排、状态、HITL、版本和可靠性 |
| [RAG 与知识治理](docs/rag.md) | 理解摄取、检索、GraphRAG、评估和权限 |
| [配置指南](docs/configuration.md) | 配置模型、搜索、观察、RAG 存储和飞书 |
| [A2A Provider](docs/a2a-provider.md) | 接入 AgentCard、JSON-RPC、Task、SSE 和认证 |
| [API 参考](docs/api.md) | 查找 REST、SSE、观察和知识库接口 |
| [运行与排障](docs/operations.md) | 启动、测试、任务恢复、日志和远程访问 |
| [竞赛要求覆盖](docs/requirements.md) | 答辩要求与代码实现位置 |
| [路线图](docs/roadmap.md) | 已完成能力、当前边界和后续方向 |

## 技术栈

| 层 | 技术 |
| --- | --- |
| 编排 | LangGraph StateGraph、条件路由、反馈闭环 |
| 后端 | Python 3.12、FastAPI、Pydantic v2、SQLite |
| 前端 | Next.js 16、React 19、TypeScript、Tailwind CSS 4 |
| 检索 | BGE-M3、FastEmbed BM25、Qdrant RRF、bge-reranker-v2-m3 |
| 解析 | Docling、RapidOCR、OOXML fallback、BeautifulSoup |
| 任务 | SQLite durable queue、schedule lease、standalone Worker |
| 互操作 | `a2a-sdk==1.1.2`、A2A protocol 1.0 |
| 部署 | uv、pnpm、Docker 配置、Make 命令 |

## 项目结构

```text
backend/app/                         # FastAPI 网关、A2A、任务 Worker
backend/packages/competition/        # LangGraph、Schema、RAG、观察和报告逻辑
backend/tests/                       # 后端单元与集成测试
frontend/src/app/competition/        # 分析、观察、知识库和设置页面
frontend/src/components/competition/ # 报告、DAG、工作台和证据组件
docs/                                # 专题文档（中英文）
evals/rag/                           # RAG 离线评估集
scripts/                             # 启动、模型准备、评估和配置同步脚本
images/                              # 架构和界面素材
```

运行时数据库、模型、原始资料和评估报告位于 `.ci-agent/`，不会提交到 Git。

## 测试

```bash
make test
make lint
make rag-eval
cd backend && uv run --locked pytest tests/test_a2a_provider.py
```

前端可使用 `frontend/node_modules/.bin/tsc --noEmit`、`eslint .` 和 `prettier --check .`。真实 S3/Qdrant 联通测试需要相应服务和凭据，不属于默认本地测试。

## License

[MIT](LICENSE)
