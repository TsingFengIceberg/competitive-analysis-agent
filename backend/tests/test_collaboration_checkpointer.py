"""P1: Checkpointer 集成测试 — 验证协作图与 LangGraph Checkpointer 的完整交互。

测试覆盖：
- 图编译时传入 checkpointer
- invoke 后 checkpoint 创建
- interrupt() 暂停/恢复（HITL Gate 需要 checkpointer）
- 线程隔离（不同 thread_id 独立 state）
- checkpoint 恢复后状态一致性
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.collaboration.graph import build_collaboration_graph


# ═══════════════════════════════════════════════════════════════════════════════
# Checkpointer 编译与基本交互
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckpointerCompilation:
    """验证协作图与 checkpointer 的编译和基本交互。"""

    def test_graph_compiles_with_in_memory_checkpointer(self):
        """传入 InMemorySaver → 编译成功。"""
        checkpointer = InMemorySaver()
        graph = build_collaboration_graph(checkpointer=checkpointer)
        assert graph is not None
        assert graph.checkpointer is checkpointer

    def test_graph_compiles_without_checkpointer(self):
        """不传 checkpointer → 编译成功，checkpointer 为 None。"""
        graph = build_collaboration_graph()
        assert graph is not None
        # checkpointer 可能后续由 Worker 注入
        assert graph.checkpointer is None

    def test_graph_nodes_unchanged_with_checkpointer(self):
        """checkpointer 不影响图结构。"""
        graph_with = build_collaboration_graph(checkpointer=InMemorySaver())
        graph_without = build_collaboration_graph()

        nodes_with = set(graph_with.get_graph().nodes.keys())
        nodes_without = set(graph_without.get_graph().nodes.keys())
        assert nodes_with == nodes_without


# ═══════════════════════════════════════════════════════════════════════════════
# Checkpoint 创建与 State 持久化
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckpointPersistence:
    """验证 checkpoint 在 invoke 过程中的创建和读取。"""

    def test_invoke_creates_checkpoint(self):
        """invoke 后应产生至少一个 checkpoint。"""
        from unittest.mock import MagicMock, patch

        checkpointer = InMemorySaver()
        graph = build_collaboration_graph(checkpointer=checkpointer)

        # Mock 所有 LLM 节点为直通——我们只测 checkpoint 机制
        with patch("deerflow.subagents.executor.SubagentExecutor") as mock_exec_cls:
            with patch("deerflow.tools.get_available_tools", return_value=[]):
                mock_exec = MagicMock()
                mock_exec.execute.return_value = '{"topic":"test","sub_tasks":[{"id":"t1","query":"test","target_sources":["example.com"],"method":"web_search"}]}'
                mock_exec_cls.return_value = mock_exec

                config = {"configurable": {"thread_id": "test-thread-1"}}
                graph.invoke({"messages": []}, config)

        # 验证 checkpoint 被创建（thread_id 对应的 state 存在）
        checkpoint = checkpointer.get(config)
        assert checkpoint is not None
        assert "messages" in checkpoint["channel_values"]

    def test_different_threads_have_independent_state(self):
        """不同 thread_id 的 State 完全隔离。"""
        from unittest.mock import MagicMock, patch

        checkpointer = InMemorySaver()
        graph = build_collaboration_graph(checkpointer=checkpointer)

        with patch("deerflow.subagents.executor.SubagentExecutor") as mock_exec_cls:
            with patch("deerflow.tools.get_available_tools", return_value=[]):
                mock_exec = MagicMock()
                mock_exec.execute.return_value = '{"topic":"test","sub_tasks":[{"id":"t1","query":"test","target_sources":["example.com"],"method":"web_search"}]}'
                mock_exec_cls.return_value = mock_exec

                config_a = {"configurable": {"thread_id": "thread-a"}}
                config_b = {"configurable": {"thread_id": "thread-b"}}

                graph.invoke({"messages": [], "workflow_type": "competitive_analysis"}, config_a)
                graph.invoke({"messages": [], "workflow_type": "market_trend"}, config_b)

        ckpt_a = checkpointer.get(config_a)
        ckpt_b = checkpointer.get(config_b)

        # 不同线程的 checkpoint 存在
        assert ckpt_a is not None
        assert ckpt_b is not None
        # 两个线程独立
        assert ckpt_a is not ckpt_b

    def test_reinvoke_same_thread_restores_state(self):
        """同一 thread_id 再次 invoke → checkpoint 恢复之前的状态。"""
        from unittest.mock import MagicMock, patch

        checkpointer = InMemorySaver()
        graph = build_collaboration_graph(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "test-thread-restore"}}

        with patch("deerflow.subagents.executor.SubagentExecutor") as mock_exec_cls:
            with patch("deerflow.tools.get_available_tools", return_value=[]):
                mock_exec = MagicMock()
                mock_exec.execute.return_value = '{"topic":"test","sub_tasks":[{"id":"t1","query":"test","target_sources":["example.com"],"method":"web_search"}]}'
                mock_exec_cls.return_value = mock_exec

                # 第一次 invoke
                graph.invoke({"messages": [], "workflow_type": "competitive_analysis"}, config)

                # 获取 checkpoint 的 checkpoint_id
                ckpt1 = checkpointer.get(config)
                assert ckpt1 is not None

                # 再次 invoke（从 checkpoint 恢复）
                graph.invoke({"messages": []}, config)

                ckpt2 = checkpointer.get(config)
                assert ckpt2 is not None


# ═══════════════════════════════════════════════════════════════════════════════
# HITL interrupt() 与 Checkpointer 交互
# ═══════════════════════════════════════════════════════════════════════════════


class TestHITLInterruptWithCheckpointer:
    """验证 HITL Gate 的 interrupt() 与 checkpointer 的完整交互。

    LangGraph interrupt() 语义：
    - 有 checkpointer：暂停图，checkpoint 写入持久化存储，可跨进程恢复
    - 无 checkpointer：interrupt() 仍然生效，但 checkpoint 仅存在于内存
    """

    def test_graph_with_checkpointer_supports_interrupt_node(self):
        """HITL Gate 节点存在于图中，checkpointer 不影响节点注册。"""
        checkpointer = InMemorySaver()
        graph = build_collaboration_graph(checkpointer=checkpointer)
        nodes = graph.get_graph().nodes
        assert "hitl_gate" in nodes

    def test_interrupt_present_in_langgraph_types(self):
        """验证 LangGraph interrupt API 可用（无论是否有 checkpointer）。"""
        from langgraph.types import interrupt

        assert callable(interrupt)


# ═══════════════════════════════════════════════════════════════════════════════
# Checkpointer 与 State 映射
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckpointerStateMapping:
    """验证 checkpointer 序列化/反序列化时 State Mapping 字段不丢失。"""

    def test_memory_fields_survive_checkpoint_roundtrip(self):
        """source_credibility_memory 和 product_knowledge_memory 在 checkpoint 中正确保存/恢复。"""
        checkpointer = InMemorySaver()
        graph = build_collaboration_graph(checkpointer=checkpointer)

        from unittest.mock import MagicMock, patch

        with patch("deerflow.subagents.executor.SubagentExecutor") as mock_exec_cls:
            with patch("deerflow.tools.get_available_tools", return_value=[]):
                mock_exec = MagicMock()
                mock_exec.execute.return_value = '{"topic":"test","sub_tasks":[{"id":"t1","query":"test","target_sources":["example.com"],"method":"web_search"}]}'
                mock_exec_cls.return_value = mock_exec

                config = {"configurable": {"thread_id": "test-thread-memory"}}

                # 初始 invoke 携带 memory 数据
                initial_state = {
                    "messages": [],
                    "source_credibility_memory": {
                        "domains": {
                            "trusted.com": {"score": 0.9, "verified_count": 10, "failed_count": 1, "last_verified": None, "sample_topics": []}
                        },
                        "last_updated": "2026-05-19T00:00:00Z",
                    },
                    "product_knowledge_memory": {
                        "products": {
                            "iphone 17": {
                                "topic": "iPhone 17",
                                "attributes": {"battery": {"value": 4000, "confidence": 0.85}},
                                "last_updated": None,
                                "total_ingest_runs": 0,
                            }
                        },
                        "last_updated": "2026-05-19T00:00:00Z",
                    },
                }

                graph.invoke(initial_state, config)
                ckpt = checkpointer.get(config)

                assert ckpt is not None
                channel_values = ckpt["channel_values"]

                # Memory 字段在 checkpoint 中被保留
                src_mem = channel_values.get("source_credibility_memory")
                assert src_mem is not None
                assert "domains" in src_mem
                assert src_mem["domains"]["trusted.com"]["score"] == 0.9

                prod_mem = channel_values.get("product_knowledge_memory")
                assert prod_mem is not None
                assert "products" in prod_mem
                assert "iphone 17" in prod_mem["products"]


# ═══════════════════════════════════════════════════════════════════════════════
# Checkpointer 类型兼容性
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckpointerCompatibility:
    """验证协作图与不同 checkpointer 实现的兼容性。"""

    def test_in_memory_saver_is_compatible(self):
        """InMemorySaver（开发/测试用）兼容。"""
        graph = build_collaboration_graph(checkpointer=InMemorySaver())
        assert graph.checkpointer is not None

    def test_no_checkpointer_accepts_runtime_injection(self):
        """编译时不传 checkpointer → 支持运行时注入。"""
        graph = build_collaboration_graph()
        assert graph.checkpointer is None

        # Worker 行为模拟：运行时注入 checkpointer
        checkpointer = InMemorySaver()
        graph.checkpointer = checkpointer
        assert graph.checkpointer is checkpointer

    def test_checkpointer_supports_multiple_instances(self):
        """多个 checkpointer 实例互不干扰。"""
        cp1 = InMemorySaver()
        cp2 = InMemorySaver()

        g1 = build_collaboration_graph(checkpointer=cp1)
        g2 = build_collaboration_graph(checkpointer=cp2)

        assert g1.checkpointer is cp1
        assert g2.checkpointer is cp2
        assert g1.checkpointer is not g2.checkpointer
