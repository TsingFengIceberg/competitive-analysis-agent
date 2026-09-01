# API 参考

后端默认运行在 `http://localhost:8001`，Swagger 位于 `/docs`。所有业务接口按当前用户或知识空间权限隔离。

## 分析与报告

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/competition/analyze` | 创建分析任务 |
| GET | `/api/competition/stream/{thread_id}` | 前端专用 SSE |
| GET | `/api/competition/report/{thread_id}` | 获取报告与阶段数据 |
| GET | `/api/competition/report/{thread_id}/history` | 版本历史和分支树 |
| GET | `/api/competition/report/{thread_id}/versions/{version}` | 指定版本完整快照 |
| GET | `/api/competition/report/{thread_id}/trace` | Agent 流程追踪 |
| PATCH | `/api/competition/report/{thread_id}/sections` | 人工修订章节 |
| PUT | `/api/competition/report/{thread_id}` | HITL 审批或返工 |
| POST | `/api/competition/{thread_id}/cancel` | 取消分析 |
| GET | `/api/competition/report/{thread_id}/export` | Markdown/JSON 导出 |

## 观察与告警

`/api/competition/observation/schedules` 管理观察任务，`/api/competition/observation/schedules/{id}/run-now` 立即执行，`/api/competition/observation/runs` 查询运行历史。变化时间线使用 `/api/competition/intelligence/changes`，单条变化详情使用 `/api/competition/intelligence/changes/{change_id}`。

告警规则使用 `/api/competition/alerts/rules`，历史和投递使用 `/api/competition/alerts/events` 与 `/api/competition/alerts/dispatch`。订阅和反馈使用 `/api/competition/subscriptions` 与 `/api/competition/alerts/events/{event_id}/feedback`。

## 知识库与 RAG

| 能力 | 路径 |
| --- | --- |
| 状态、文档、任务 | `/api/competition/knowledge/status`、`/documents`、`/jobs` |
| 上传/导入/重建 | `/upload`、`/import-inbox`、`/import-intelligence`、`/rebuild` |
| 检索与反馈 | `/search`、`/retrieval-logs`、`/retrieval-feedback` |
| 评估与实验 | `/evaluate`、`/evaluation-datasets`、`/retrieval-experiments` |
| 来源运维 | `/sources/health`、`/sources/{id}/sync`、`/sources/{id}/retry` |
| 空间与治理 | `/spaces`、`/reviews`、`/governance/stats`、`/deletions` |
| 实体、关系、洞察 | `/entities`、`/graph`、`/events`、`/insights` |
| 证据分块 | `/chunks/{chunk_id}` |

具体请求体以 FastAPI OpenAPI schema 为准，避免将内部数据库字段当作外部契约。

## A2A

A2A Provider 的 AgentCard、JSON-RPC、Task 和 SSE 见 [A2A Provider 文档](a2a-provider.md)。它与前端专用 SSE 完全分离。
