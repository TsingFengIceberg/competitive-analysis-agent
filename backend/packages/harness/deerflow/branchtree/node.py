"""BranchNode — BranchTree 节点数据结构。

每个节点代表一次完整的用户交互快照。不存完整 state，
只存 checkpoint_id 引用（完整 state 由 LangGraph 管理）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BranchNode:
    """BranchTree 的一个版本节点。

    Attributes:
        node_id: 唯一版本标识，如 "v1", "v2"。
        parent_id: 父节点 ID，None 表示根节点。
        checkpoint_id: 指向 LangGraph checkpoint 的引用。
        action: 触发此快照的操作类型（initial / rewrite / reanalyze / recollect / approve）。
        created_at: 创建时间。
        metadata: 自由扩展的业务元数据。
        children: 子节点 ID 列表（内存维护，不持久化到此对象）。
    """

    node_id: str
    parent_id: str | None
    checkpoint_id: str
    action: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    @property
    def is_fork_point(self) -> bool:
        return len(self.children) > 1

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "checkpoint_id": self.checkpoint_id,
            "action": self.action,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "children": self.children,
        }
