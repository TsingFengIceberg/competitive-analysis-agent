"""CheckpointOps — LangGraph checkpoint 便捷操作工具层。

独立工具库，不是一棵树。封装 LangGraph checkpoint 裸 API 为应用层友好的原子操作。
BranchTree 通过调用 CheckpointOps 来与 LangGraph 交互，实现依赖倒置。

调研结论：PyPI 7 个 langgraph-checkpoint-* 包全是存储后端，无操作封装层。
LangGraph JS SDK 有 getBranchSequence / getBranchView，Python 端无等价物。
DeerFlow 自身仅封装了 checkpointer 工厂函数。这是真正的生态空白。

LangGraph 隐式 Fork 机制：
  非最新 checkpoint_id 调用 update_state/stream → pregel loop 检测 is_time_traveling=True
  → 自动创建 source:"fork" checkpoint，parent_checkpoint_id 指向历史节点。
  旧分支不受影响——fork 是 INSERT 新行，不 UPDATE 旧行。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
    from langgraph.pregel.main import CompiledStateGraph
    from langgraph.types import StateSnapshot

logger = logging.getLogger(__name__)


class CheckpointOps:
    """LangGraph checkpoint 便捷操作工具。

    所有方法统一接收 thread_id 参数，使缓存可以按 thread 分区。
    入参和返回值均为 LangGraph 原生类型，不依赖任何 BranchTree 特有概念。

    Usage::

        from langgraph.checkpoint.sqlite import SqliteSaver
        saver = SqliteSaver.from_conn_string("checkpoints.db")
        ck = CheckpointOps(saver)
        state = ck.get_state("thread-001")
        tree = ck.build_tree("thread-001")
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        graph: CompiledStateGraph | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._graph = graph

        # 内存缓存：按 thread 分区，写操作时失效
        self._tree_cache: dict[str, dict[str | None, list[str]]] = {}

        # parent 反向索引缓存（children → parent），用于 lineage
        self._parent_of: dict[str, dict[str, str | None]] = {}

    # ── 内部：缓存管理 ──────────────────────────────────────────

    def _ensure_cache(self, thread_id: str) -> None:
        """惰性构建缓存。

        首次调用：全量扫描并构建缓存。
        后续调用：信任缓存，零 DB 查询。
        缓存失效后（写操作或外部 invalidate_cache() 调用）：下次读时重建。
        """
        if thread_id in self._tree_cache:
            return  # 缓存命中，零 DB 查询

        self._tree_cache[thread_id] = {}
        self._parent_of[thread_id] = {}

        for cp in self._checkpointer.list(
            {"configurable": {"thread_id": thread_id}}
        ):
            cid = self._extract_checkpoint_id(cp.config)
            pid = self._extract_parent_id(cp)
            self._tree_cache[thread_id].setdefault(pid, []).append(cid)
            self._parent_of[thread_id][cid] = pid

    def invalidate_cache(self, thread_id: str) -> None:
        """使缓存失效，下次读时惰性重建。

        写操作（fork/update_state）内部自动调用。
        外部调用方在 graph.stream/invoke 后也需调用此方法，因为 LangGraph 内部
        会写新的 checkpoint，而 CheckpointOps 无法感知。
        """
        self._tree_cache.pop(thread_id, None)
        self._parent_of.pop(thread_id, None)

    @staticmethod
    def _extract_checkpoint_id(config: dict) -> str:
        return config.get("configurable", {}).get("checkpoint_id", "")

    @staticmethod
    def _extract_parent_id(cp: CheckpointTuple) -> str | None:
        if cp.parent_config is None:
            return None
        return cp.parent_config.get("configurable", {}).get("checkpoint_id")

    @staticmethod
    def _make_config(thread_id: str, checkpoint_id: str | None = None) -> dict:
        config: dict = {"configurable": {"thread_id": thread_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        return config

    # ── 读操作 ──────────────────────────────────────────────────

    def get_state(
        self, thread_id: str, checkpoint_id: str | None = None
    ) -> StateSnapshot:
        """获取指定 checkpoint 的 StateSnapshot。

        不传 checkpoint_id → 返回最新 state。
        底层：SQLite 主键查询 WHERE thread_id=? AND checkpoint_id=? — O(1)。
        """
        config = self._make_config(thread_id, checkpoint_id)
        if self._graph is not None:
            return self._graph.get_state(config)
        checkpoint = self._checkpointer.get(config)
        if checkpoint is None:
            raise ValueError(
                f"Checkpoint not found: thread={thread_id}, ck={checkpoint_id}"
            )
        # 无 graph 时从 checkpoint dict 构造简单返回值
        from langgraph.types import StateSnapshot
        return StateSnapshot(
            values=checkpoint.get("channel_values", {}),
            next=(),
            config=config,
            metadata=checkpoint.get("metadata"),
            created_at=checkpoint.get("ts"),
            parent_config=None,
            tasks=(),
            interrupts=(),
        )

    def get_history(
        self, thread_id: str, limit: int | None = None
    ) -> list[StateSnapshot]:
        """获取 thread 的 checkpoint 历史，最新的在前。

        底层：索引扫描，limit 直接下推到 SQL — O(k)。
        """
        if self._graph is not None:
            return list(self._graph.get_state_history(
                self._make_config(thread_id), limit=limit
            ))
        result = []
        for cp in self._checkpointer.list(
            self._make_config(thread_id), limit=limit
        ):
            from langgraph.types import StateSnapshot
            result.append(StateSnapshot(
                values=cp.checkpoint.get("channel_values", {}),
                next=(),
                config=cp.config,
                metadata=cp.metadata,
                created_at=cp.checkpoint.get("ts"),
                parent_config=cp.parent_config,
                tasks=(),
                interrupts=(),
            ))
        return result

    def latest(self, thread_id: str) -> StateSnapshot:
        """获取最新 StateSnapshot。等价于 get_state(thread_id)。"""
        return self.get_state(thread_id)

    def build_tree(
        self, thread_id: str
    ) -> dict[str | None, list[str]]:
        """构建 checkpoint 树：{parent_id: [child_ids]}。

        缓存命中：O(1) 返回缓存 dict。
        裸调 LangGraph 需要全量扫描 + 手工按 parent_checkpoint_id 建树。
        None key = 根节点们。
        """
        self._ensure_cache(thread_id)
        return self._tree_cache[thread_id]

    def children(
        self, thread_id: str, checkpoint_id: str
    ) -> list[str]:
        """查询指定 checkpoint 的所有子节点。

        缓存命中：O(1) dict 查找。
        LangGraph 有 parent_checkpoint_id 但无 child 索引 — 裸调需全量扫描。
        """
        self._ensure_cache(thread_id)
        return self._tree_cache[thread_id].get(checkpoint_id, [])

    def is_fork_point(
        self, thread_id: str, checkpoint_id: str
    ) -> bool:
        """判断是否为分叉点（有多个子节点）。

        缓存命中：O(1)，继承 children() 的 O(1)。
        """
        return len(self.children(thread_id, checkpoint_id)) > 1

    def lineage(
        self, thread_id: str, checkpoint_id: str
    ) -> list[str]:
        """追溯祖先链，从根到指定 checkpoint。

        缓存预热后：O(深度) 纯内存遍历，零 DB 查询。
        裸调：200 步深度 = 200 次 SQLite 查询。
        """
        self._ensure_cache(thread_id)
        chain = []
        cur: str | None = checkpoint_id
        parent_of = self._parent_of[thread_id]
        while cur is not None:
            chain.append(cur)
            cur = parent_of.get(cur)
        chain.reverse()
        return chain

    # ── 写操作（触发缓存失效）───────────────────────────────────

    def fork(
        self,
        thread_id: str,
        from_checkpoint: str,
        state_update: dict,
    ) -> str:
        """从历史 checkpoint 分叉出新分支。

        非最新 checkpoint_id → LangGraph 内部检测 time-travel
        → 自动创建 source:"fork" checkpoint。
        调用者不需要理解隐式 fork 机制——函数名就是语义。

        Returns:
            新 checkpoint_id。
        """
        if self._graph is None:
            raise RuntimeError(
                "fork() requires a CompiledStateGraph. "
                "Pass graph= to CheckpointOps constructor."
            )
        config = self._make_config(thread_id, from_checkpoint)
        new_config = self._graph.update_state(config, state_update)
        self.invalidate_cache(thread_id)
        return self._extract_checkpoint_id(new_config)

    def update_state(
        self,
        thread_id: str,
        values: dict,
        as_node: str | None = None,
    ) -> str:
        """更新当前最新 state。

        与 fork() 的区别：不指定 from_checkpoint → 更新最新而非分叉。
        """
        if self._graph is None:
            raise RuntimeError(
                "update_state() requires a CompiledStateGraph. "
                "Pass graph= to CheckpointOps constructor."
            )
        config = self._make_config(thread_id)
        new_config = self._graph.update_state(config, values, as_node=as_node)
        self.invalidate_cache(thread_id)
        return self._extract_checkpoint_id(new_config)

    # ── 标签管理 ────────────────────────────────────────────────

    def tag(
        self, thread_id: str, checkpoint_id: str, label: str
    ) -> None:
        """给 checkpoint 打标签。标签存储在 checkpoint metadata.extra 中。"""
        cp = self._checkpointer.get(
            self._make_config(thread_id, checkpoint_id)
        )
        if cp is None:
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")
        metadata = dict(cp.get("metadata", {}) or {})
        extra = dict(metadata.get("extra", {}) or {})
        tags: list[str] = list(extra.get("tags", []))
        tags.append(label)
        extra["tags"] = tags
        metadata["extra"] = extra
        self._checkpointer.put(
            self._make_config(thread_id, checkpoint_id),
            cp,
            metadata,
            {},
        )

    def list_tags(self, thread_id: str) -> dict[str, list[str]]:
        """列出 thread 下所有标签：{checkpoint_id: [labels]}。"""
        result: dict[str, list[str]] = {}
        for cp in self._checkpointer.list(
            self._make_config(thread_id)
        ):
            cid = self._extract_checkpoint_id(cp.config)
            metadata = cp.checkpoint.get("metadata") or {}
            extra = metadata.get("extra", {}) if isinstance(metadata, dict) else {}
            tags = extra.get("tags", [])
            if tags:
                result[cid] = tags
        return result

    def restore_to_tag(
        self, thread_id: str, label: str
    ) -> StateSnapshot:
        """恢复到指定标签对应的 checkpoint。"""
        for cid, tags in self.list_tags(thread_id).items():
            if label in tags:
                return self.get_state(thread_id, cid)
        raise ValueError(f"Tag not found: {label}")
