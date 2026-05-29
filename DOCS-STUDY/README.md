# DOCS-STUDY 目录索引

> PA-Agent-DF 编码过程中的学习记录，按架构主题分类，非逐文件对应。

## 目录结构

| 编号 | 主题 | 文件 | 最后更新 |
|------|------|------|----------|
| 01 | 三层 State 体系 + State Mapping | [`01-state-system.md`](01-state-system.md) | 2026-05-14 (8 Q&A) |
| 02 | SubGraph 构建与编译隔离 | [`02-subgraph-design.md`](02-subgraph-design.md) | 2026-05-14 (10 Q&A) |
| 03 | Parent Graph 组装与条件路由 | [`03-graph-orchestration.md`](03-graph-orchestration.md) | 2026-05-14 (4 Q&A) |
| 04 | 测试模式与断言 | [`04-testing-patterns.md`](04-testing-patterns.md) | 2026-05-14 (3 Q&A) |
| 05 | 对抗式批判协议：Challenge/Rebuttal/Ruling | [`05-debate-protocol.md`](05-debate-protocol.md) | 2026-05-14 (3 Q&A) |
| 06 | 执行实例走读：Research 全链路 | [`06-execution-walkthrough.md`](06-execution-walkthrough.md) | 2026-05-14 |
| 07 | Analysis SubGraph：节点流转与分析 Prompt | [`07-analysis-subgraph.md`](07-analysis-subgraph.md) | 2026-05-14 (2 Q&A) |
| 08 | 角色权限体系：Action 映射 + PermissionGuard | [`08-permission-system.md`](08-permission-system.md) | 2026-05-15 (10 Q&A) |
| 09 | HITL 审批门：interrupt() + Checkpoint 暂停/恢复 | [`09-hitl-gate.md`](09-hitl-gate.md) | 2026-05-15 (1 Q&A) |
| 10 | 流式事件系统：EventType + SSE 推送链路 | [`10-events-streaming.md`](10-events-streaming.md) | 2026-05-15 (2 Q&A) |
| 11 | 协作系统整体层级调用图 | [`11-architecture-hierarchy.md`](11-architecture-hierarchy.md) | 2026-05-15 (1 Q&A) |
| 12 | Sprint 5 集成层：中间件注册 + 配置热加载 + HITL API | [`12-sprint5-integration.md`](12-sprint5-integration.md) | 2026-05-15 (3 Q&A) |
| 13 | 协作记忆系统：来源可信度 + 产品知识库双轨记忆 | [`13-memory-system.md`](13-memory-system.md) | 2026-05-19 (5 Q&A) |
| 14 | Phase 4 P0/P1 Review: 生产就绪关键修补 | [`14-phase4-p0-p1-review.md`](14-phase4-p0-p1-review.md) | 2026-05-19 (6 Q&A) |

## 关联源文件索引

| 源文件 | 相关学习文档 |
|--------|-------------|
| `collaboration/state.py` | 01, 11, 13 |
| `collaboration/subgraphs/state_mapping.py` | 01, 11, 13 |
| `collaboration/subgraphs/research_subgraph.py` | 02, 05, 11, 14 |
| `collaboration/subgraphs/analysis_subgraph.py` | 02, 07, 11 |
| `collaboration/graph.py` | 03, 11, 14 |
| `collaboration/nodes/research_nodes.py` | 02, 06, 13, 14 |
| `collaboration/nodes/analysis_nodes.py` | 07 |
| `collaboration/nodes/hitl_gate.py` | 09 |
| `collaboration/prompts/research_prompts.py` | 05, 06 |
| `collaboration/prompts/analysis_prompts.py` | 07 |
| `collaboration/protocols/messages.py` | 05, 06 |
| `collaboration/protocols/debate.py` | 05, 06 |
| `collaboration/memory/__init__.py` | 13 |
| `collaboration/memory/source_credibility.py` | 13 |
| `collaboration/memory/product_knowledge.py` | 13 |
| `collaboration/permissions/role_definition.py` | 08 |
| `collaboration/permissions/permission_guard.py` | 08 |
| `collaboration/context.py` | 08, 12 |
| `collaboration/events.py` | 10 |
| `collaboration/memory/__init__.py` | 13 |
| `collaboration/memory/source_credibility.py` | 13 |
| `collaboration/memory/product_knowledge.py` | 13 |
| `collaboration/nodes/research_nodes.py` | 02, 06, 14 |
| `config/collaboration_config.py` | 12 |
| `agents/middlewares/collaboration_middleware.py` | 12 |
| `agents/lead_agent/agent.py` | 12 |
| `config/app_config.py` | 12 |
| `app/gateway/routers/collaboration.py` | 09, 12 |
| `agents/thread_state.py` | 01 |
| `runtime/stream_bridge/base.py` | 10 |
| `runtime/runs/worker.py` | 10 |
| `tests/test_collaboration_subgraphs.py` | 04 |
| `tests/test_collaboration_graph.py` | 04 |
| `tests/test_collaboration_debate.py` | 04 |
| `tests/test_collaboration_nodes.py` | 02, 04 |
| `tests/test_collaboration_analysis.py` | 04, 07 |
| `tests/test_collaboration_permissions.py` | 04, 08 |
| `tests/test_collaboration_hitl.py` | 04, 09 |
| `tests/test_collaboration_memory.py` | 13 |
| `langgraph.json` | 14 |
