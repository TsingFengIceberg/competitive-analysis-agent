# 竞赛要求覆盖

| 要求 | 实现位置 |
| --- | --- |
| 6 个 Agent 职责边界清晰 | `nodes/orchestrator.py`、`collector.py`、`analyst.py`、`reviewer.py`、`writer.py`、`hitl_gate.py` |
| Collector 双轨采集和 VoC | `nodes/collector.py` |
| 竞品知识 Schema | `schema.py` |
| Agent 间结构化 JSON 通信 | `schema.py` 中的 AnalysisResult、ReviewVerdict、ReportData 等 |
| Reviewer 质量检查和定向返工 | `nodes/reviewer.py`、`router.py` |
| 反馈改善率量化 | `competition_router.py` |
| 引用 `[n]` 和 traceability map | `nodes/writer.py`、`source-card.tsx` |
| Schema 校验、重试和降级 | `schema.py`、各 Agent 节点的错误处理 |
| DAG 实时状态 | `dag.py`、`dag-graph.tsx` |
| Prompt、输入、输出、Token 可查 | `process-trace-panel.tsx`、`agent-detail-panel.tsx`、`/trace` |
| 端到端可演示链路 | `graph.py`、`competition_router.py`、前端分析页面 |
| 幻觉抑制和数字校验 | `nodes/reviewer.py`、`nodes/analyst.py` |
| 超时、重试和降级 | `config.py`、`nodes/error_handler.py` |
| BranchTree、Checkpoint 和来源可信度 | `branchtree/`、`db.py` |
| 覆盖率、交叉验证率、改善率 | `nodes/writer.py`、`schema.py` |

这份矩阵用于答辩和面试定位代码入口，不替代 API 和架构文档。当前实现以代码、测试和运行结果为准。
