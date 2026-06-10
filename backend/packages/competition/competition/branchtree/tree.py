"""BranchTree — Data 粒度的版本分支树。

抽象基类，单层两级继承：BranchTree → DeliverableTree / ConversationTree。
依赖注入 CheckpointOps（LangGraph 交互）+ MetadataStore（持久化）。
子类实现 _serialize / _deserialize 决定节点存什么数据。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from competition.branchtree.node import BranchNode

# ── MetadataStore Protocol ──────────────────────────────────────


class MetadataStore(Protocol):
    """BranchTree 持久化层接口。

    BranchTree 只存 checkpoint_id 引用 + 业务 metadata。
    完整 state 由 LangGraph checkpoint 表管理。
    """

    def insert(
        self,
        thread_id: str,
        parent_version: int | None,
        checkpoint_id: str,
        action: str,
        metadata: dict | None = None,
    ) -> int:
        """插入新版本记录，返回自增 version 号。"""
        ...

    def get(self, thread_id: str, version: int) -> dict | None:
        """获取指定版本的 metadata。"""
        ...

    def list_by_thread(self, thread_id: str) -> list[dict]:
        """列出 thread 下所有版本，按 version 升序。"""
        ...


# ── BranchTree ──────────────────────────────────────────────────


class BranchTree(ABC):
    """Data 粒度的版本分支树。

    节点 = 一次完整分析的快照（report_data + analysis_result + collected_data）。
    分叉 = HITL 决策 / 编辑历史消息（用户触发）。
    不直接调用 LangGraph checkpoint API——通过 CheckpointOps 依赖倒置。

    Usage::

        tree = DeliverableTree(checkpointer, metadata_store)
        tree.load("thread-001")
        v2 = tree.fork("thread-001", from_version=1, action="rewrite")
        state = tree.restore("thread-001", version=1)
    """

    def __init__(self, checkpointer, metadata_store: MetadataStore) -> None:
        from competition.branchtree.checkpoint_ops import CheckpointOps

        self._ck = CheckpointOps(checkpointer)
        self._store = metadata_store
        self._nodes: dict[str, BranchNode] = {}  # "v{N}" → BranchNode
        self._thread_id: str | None = None

    # ── 子类必须实现的抽象方法 ──────────────────────────────────

    @abstractmethod
    def _serialize_state(self, channel_values: dict) -> dict:
        """从 LangGraph channel_values 中提取子类关心的数据。

        DeliverableTree: report_data + analysis_result + collected_data
        ConversationTree: messages
        """
        ...

    # ── 核心操作 ─────────────────────────────────────────────────

    def load(self, thread_id: str) -> None:
        """从 MetadataStore 加载 thread 的所有历史版本到内存。"""
        self._thread_id = thread_id
        self._nodes.clear()
        rows = self._store.list_by_thread(thread_id)
        for row in rows:
            from competition.branchtree.node import BranchNode
            node_id = f"v{row['version']}"
            parent_id = f"v{row['parent_version']}" if row.get("parent_version") else None
            node = BranchNode(
                node_id=node_id,
                parent_id=parent_id,
                checkpoint_id=row["checkpoint_id"],
                action=row["action"],
                created_at=datetime.fromisoformat(row["created_at"]),
                metadata=row.get("metadata_json", {}) or {},
            )
            self._nodes[node_id] = node
        # 重建 children 关系
        for node in self._nodes.values():
            if node.parent_id and node.parent_id in self._nodes:
                self._nodes[node.parent_id].children.append(node.node_id)

    def snapshot(
        self,
        thread_id: str,
        action: str,
        metadata: dict | None = None,
    ) -> BranchNode:
        """对当前最新 state 创建新版本快照。"""
        if self._thread_id is None:
            self.load(thread_id)

        state = self._ck.latest(thread_id)
        checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id", "")

        parent_version = self._current_active_version(thread_id)
        version = self._store.insert(
            thread_id=thread_id,
            parent_version=parent_version,
            checkpoint_id=checkpoint_id,
            action=action,
            metadata=metadata or {},
        )

        from competition.branchtree.node import BranchNode
        node = BranchNode(
            node_id=f"v{version}",
            parent_id=f"v{parent_version}" if parent_version else None,
            checkpoint_id=checkpoint_id,
            action=action,
            metadata=metadata or {},
        )
        self._nodes[node.node_id] = node
        if node.parent_id and node.parent_id in self._nodes:
            self._nodes[node.parent_id].children.append(node.node_id)

        return node

    def fork(
        self,
        thread_id: str,
        from_version: int,
        action: str,
        metadata: dict | None = None,
    ) -> BranchNode:
        """从历史版本分叉出新分支。

        通过 CheckpointOps.restore_to_version 获取历史 state，
        然后 CheckpointOps.fork 创建 LangGraph 层分叉，
        最后在 MetadataStore 记录新版本。
        """
        if self._thread_id is None:
            self.load(thread_id)

        from_meta = self._store.get(thread_id, from_version)
        if from_meta is None:
            raise ValueError(f"Version not found: v{from_version}")

        from_checkpoint_id = from_meta["checkpoint_id"]
        new_ck_id = self._ck.fork(
            thread_id, from_checkpoint_id, {"hitl_decision": action}
        )

        version = self._store.insert(
            thread_id=thread_id,
            parent_version=from_version,
            checkpoint_id=new_ck_id,
            action=action,
            metadata=metadata or {},
        )

        from competition.branchtree.node import BranchNode
        node = BranchNode(
            node_id=f"v{version}",
            parent_id=f"v{from_version}",
            checkpoint_id=new_ck_id,
            action=action,
            metadata=metadata or {},
        )
        self._nodes[node.node_id] = node
        parent_node = self._nodes.get(f"v{from_version}")
        if parent_node:
            parent_node.children.append(node.node_id)

        return node

    def restore(self, thread_id: str, version: int) -> dict:
        """恢复指定版本的完整 state（通过 CheckpointOps 获取）。"""
        meta = self._store.get(thread_id, version)
        if meta is None:
            raise ValueError(f"Version not found: v{version}")

        checkpoint_id = meta["checkpoint_id"]
        state = self._ck.get_state(thread_id, checkpoint_id)
        return self._serialize_state(state.values)

    def lineage(self, version: int) -> list[BranchNode]:
        """从根到指定版本的祖先链。"""
        result: list[BranchNode] = []
        cur_id: str | None = f"v{version}"
        while cur_id is not None:
            node = self._nodes.get(cur_id)
            if node is None:
                break
            result.append(node)
            cur_id = node.parent_id
        result.reverse()
        return result

    def to_dict(self) -> dict:
        """转为前端可渲染的树结构。

        Returns:
            {"nodes": [...], "edges": [...]}  每个 node 含 id/label/action/created_at
        """
        return {
            "nodes": [
                {
                    "id": n.node_id,
                    "parent_id": n.parent_id,
                    "checkpoint_id": n.checkpoint_id,
                    "action": n.action,
                    "created_at": n.created_at.isoformat(),
                    "metadata": n.metadata,
                    "children": n.children,
                }
                for n in self._nodes.values()
            ],
            "root": next(
                (n.node_id for n in self._nodes.values() if n.is_root), None
            ),
        }

    def get_node(self, version: int) -> BranchNode | None:
        return self._nodes.get(f"v{version}")

    def current_version(self) -> int | None:
        """当前活跃版本号（最新节点）。"""
        if not self._nodes:
            return None
        return max(int(n.node_id[1:]) for n in self._nodes.values())

    # ── 内部 ─────────────────────────────────────────────────────

    def _current_active_version(self, thread_id: str) -> int | None:
        """从 store 获取当前 thread 的最新版本号。"""
        rows = self._store.list_by_thread(thread_id)
        if not rows:
            return None
        return max(r["version"] for r in rows)
