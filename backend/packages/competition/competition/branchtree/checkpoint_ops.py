"""CheckpointOps — LangGraph checkpoint 便捷操作工具层。

独立工具库，不是一棵树。封装 LangGraph checkpoint 裸 API 为应用层友好的原子操作。
BranchTree 通过调用 CheckpointOps 来与 LangGraph 交互，实现依赖倒置。

调研结论：PyPI 7 个 langgraph-checkpoint-* 包全是存储后端，无操作封装层。
LangGraph JS SDK 有 getBranchSequence / getBranchView，Python 端无等价物。
LangGraph JS SDK has getBranchSequence / getBranchView, Python side has no equivalent.

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
        config: dict = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
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
        parent_of = self._parent_of[thread_id]
        if checkpoint_id not in parent_of:
            return []  # checkpoint not found — empty lineage
        chain = []
        cur: str | None = checkpoint_id
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


# ── Agent 执行层扩展 ────────────────────────────────────────────
#
# AgentBranchOps 在 CheckpointOps 上增加 Agent 执行层的操作语义：
#   自动分支探索 / A/B 测试 / 分支对比与择优 / cherry-pick。
# 这是 Agent Git 论文理念的实现层 — Agent 可自主操作 checkpoint tree，
# 类似 git branch / git merge / git cherry-pick，但由 LLM 驱动决策。
#
# 定位：CheckpointOps 是原子操作层（CRUD），AgentBranchOps 是策略层（智能决策）。


class AgentBranchOps:
    """Agent 执行层分支操作 — 自动化分支探索与择优。

    依赖注入 CheckpointOps（依赖倒置），不直接调 LangGraph API。
    所有策略方法返回结构化结果，由调用方（Agent/LLM）做最终决策。

    Usage::

        ck = CheckpointOps(saver, graph=graph)
        agent = AgentBranchOps(ck, graph)

        # A/B test: try two Collector strategies, pick winner
        result = agent.a_b_test(
            thread_id="t1",
            base_checkpoint=latest_id,
            branch_a={"collected_data": strategy_a_results},
            branch_b={"collected_data": strategy_b_results},
            evaluator=lambda state: state.get("coverage", 0),
        )

        # Explore: fork N branches, run graph on each, compare
        variants = agent.explore_branches(
            thread_id="t1",
            base_checkpoint=latest_id,
            variants=[
                {"label": "aggressive", "state_update": {"deep_mode": True}},
                {"label": "conservative", "state_update": {"deep_mode": False}},
            ],
        )
        best = agent.compare_branches(thread_id, variants, key="coverage")
    """

    def __init__(
        self,
        checkpoint_ops: CheckpointOps,
        graph: CompiledStateGraph | None = None,
    ) -> None:
        self._ck = checkpoint_ops
        self._graph = graph or checkpoint_ops._graph

    # ── 分支探索 ──────────────────────────────────────────────────

    def explore_branches(
        self,
        thread_id: str,
        base_checkpoint: str,
        variants: list[dict],
    ) -> list[dict]:
        """从 base_checkpoint fork 出多个分支，每个分支写入不同 state。

        Args:
            thread_id: 线程 ID。
            base_checkpoint: 分叉起点 checkpoint_id。
            variants: [{"label": str, "state_update": dict}, ...]
                      每个 variant 的 state_update 会被写入新分支。

        Returns:
            [{"label": str, "checkpoint_id": str, "parent": str}, ...]
            每个 variant 的标签和新 checkpoint_id。

        典型场景：
            Agent 决定尝试 3 种不同分析聚焦方向 → fork 3 个分支 →
            各自运行 analyst + writer → 对比择优。
        """
        results: list[dict] = []
        for v in variants:
            label = v.get("label", f"branch-{len(results)}")
            try:
                new_id = self._ck.fork(
                    thread_id, base_checkpoint, v.get("state_update", {})
                )
                self._ck.tag(thread_id, new_id, label)
                results.append({
                    "label": label,
                    "checkpoint_id": new_id,
                    "parent": base_checkpoint,
                })
                logger.info(
                    "AgentBranchOps: explored branch '%s' → %s", label, new_id[:12]
                )
            except Exception:
                logger.exception("AgentBranchOps: failed to explore branch '%s'", label)
        return results

    # ── A/B 测试 ──────────────────────────────────────────────────

    def a_b_test(
        self,
        thread_id: str,
        base_checkpoint: str,
        branch_a: dict,
        branch_b: dict,
        evaluator: callable,
    ) -> dict:
        """A/B 测试：创建两个分支，评估后返回优胜者。

        Args:
            thread_id: 线程 ID。
            base_checkpoint: 分叉起点。
            branch_a: {"state_update": dict} — A 方案的 state 变更。
            branch_b: {"state_update": dict} — B 方案的 state 变更。
            evaluator: StateSnapshot → float — 评分函数，高分者胜出。

        Returns:
            {"winner": "a"|"b"|"tie", "score_a": float, "score_b": float,
             "checkpoint_a": str, "checkpoint_b": str,
             "parent": str}

        典型场景：
            Agent 不确定用"激进"还是"保守"的采集策略 →
            A/B test 两种策略 → 选覆盖率高的一方。
        """
        # Fork both
        a_id = self._ck.fork(thread_id, base_checkpoint, branch_a.get("state_update", {}))
        b_id = self._ck.fork(thread_id, base_checkpoint, branch_b.get("state_update", {}))

        self._ck.tag(thread_id, a_id, "a/b-test-a")
        self._ck.tag(thread_id, b_id, "a/b-test-b")

        # Evaluate
        state_a = self._ck.get_state(thread_id, a_id)
        state_b = self._ck.get_state(thread_id, b_id)

        score_a = evaluator(state_a)
        score_b = evaluator(state_b)

        if score_a > score_b:
            winner = "a"
        elif score_b > score_a:
            winner = "b"
        else:
            winner = "tie"

        logger.info(
            "AgentBranchOps: A/B test result — A=%.3f, B=%.3f → winner=%s",
            score_a, score_b, winner,
        )

        return {
            "winner": winner,
            "score_a": score_a,
            "score_b": score_b,
            "checkpoint_a": a_id,
            "checkpoint_b": b_id,
            "parent": base_checkpoint,
        }

    # ── 分支对比 ──────────────────────────────────────────────────

    def compare_branches(
        self,
        thread_id: str,
        variants: list[dict],
        key: str = "coverage",
    ) -> dict:
        """对比多个分支，返回按评分排序的结果。

        Args:
            thread_id: 线程 ID。
            variants: [{"checkpoint_id": str, "label": str}, ...] — 分支列表。
            key: 在 state.values 中查找的评分字段名。

        Returns:
            {"best": {"checkpoint_id": str, "label": str, "score": float},
             "rankings": [{"checkpoint_id": str, "label": str, "score": float}, ...],
             "all_tied": bool}

        典型场景：
            explore_branches() 后 → 每个分支跑了 full pipeline →
            compare 各分支的 coverage/cross_validation_rate → 选最优。
        """
        scored: list[dict] = []
        for v in variants:
            cid = v.get("checkpoint_id", "")
            label = v.get("label", cid[:8])
            try:
                state = self._ck.get_state(thread_id, cid)
                values = state.values if hasattr(state, "values") else state
                # Navigate nested: try state → metrics[key], then flat key
                metrics = values.get("metrics", {}) if isinstance(values, dict) else {}
                score = float(
                    metrics.get(key)
                    or values.get(key, 0) if isinstance(values, dict) else 0
                )
            except Exception:
                score = 0.0
            scored.append({"checkpoint_id": cid, "label": label, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)

        return {
            "best": scored[0] if scored else None,
            "rankings": scored,
            "all_tied": len(set(s["score"] for s in scored)) <= 1 if scored else True,
        }

    # ── Cherry-pick ───────────────────────────────────────────────

    def cherry_pick(
        self,
        thread_id: str,
        target_checkpoint: str,
        source_checkpoint: str,
        fields: list[str],
    ) -> str:
        """从 source 分支 cherry-pick 指定字段到 target 分支。

        类似 git cherry-pick：只复制选中的字段，不影响 target 其他 state。

        Args:
            thread_id: 线程 ID。
            target_checkpoint: 目标分支 checkpoint（接收变更）。
            source_checkpoint: 源分支 checkpoint（提供值）。
            fields: 要复制的 state 字段名列表。

        Returns:
            新 checkpoint_id（在 target 分支上）。

        典型场景：
            分支 B 的"用户画像分析"做得更好，cherry-pick 这个章节
            到主分支，而不覆盖主分支的其他内容。
        """
        source_state = self._ck.get_state(thread_id, source_checkpoint)
        source_values = source_state.values if hasattr(source_state, "values") else source_state

        if not isinstance(source_values, dict):
            raise ValueError("Source state values must be dict-like for cherry-pick")

        picked: dict = {}
        for field in fields:
            if field in source_values:
                picked[field] = source_values[field]
            else:
                logger.warning(
                    "AgentBranchOps: cherry-pick field '%s' not found in source %s",
                    field, source_checkpoint[:12],
                )

        new_id = self._ck.fork(thread_id, target_checkpoint, picked)
        self._ck.tag(thread_id, new_id, f"cherry-pick:{','.join(fields)}")
        logger.info(
            "AgentBranchOps: cherry-picked %s from %s → %s",
            fields, source_checkpoint[:12], new_id[:12],
        )
        return new_id

    # ── 自动择优合并 ──────────────────────────────────────────────

    def auto_merge(
        self,
        thread_id: str,
        branch_checkpoints: list[str],
        strategy: str = "best_per_field",
        field_scorer: callable | None = None,
    ) -> str:
        """从多个分支中择优合并，创建最优合成版本。

        Args:
            thread_id: 线程 ID。
            branch_checkpoints: 候选分支 checkpoint_id 列表。
            strategy: 合并策略。
                - "best_overall": 选评分最高的分支（不合并字段）。
                - "best_per_field": 每个字段从表现最好的分支取（需 field_scorer）。
            field_scorer: (field_name, checkpoint_id) → float，
                          仅在 best_per_field 策略时需要。

        Returns:
            合并后的新 checkpoint_id。

        典型场景：
            3 个探索分支各有优势 → auto_merge 取各自最强字段 →
            合成一个综合最优版本。
        """
        if strategy == "best_overall":
            # 使用 compare 选最高分
            variants = [{"checkpoint_id": cid} for cid in branch_checkpoints]
            result = self.compare_branches(thread_id, variants)
            if result["best"] is None:
                raise ValueError("No valid branches to merge")
            best_id = result["best"]["checkpoint_id"]
            new_id = self._ck.fork(thread_id, best_id, {})
            self._ck.tag(thread_id, new_id, "auto-merge:best-overall")
            return new_id

        elif strategy == "best_per_field":
            if field_scorer is None:
                raise ValueError("field_scorer is required for best_per_field strategy")

            # 对每个字段找最优分支
            best_per_field: dict[str, tuple[str, float]] = {}
            for field in self._discover_fields(thread_id, branch_checkpoints):
                best_cid = None
                best_score = float("-inf")
                for cid in branch_checkpoints:
                    score = field_scorer(field, cid)
                    if score > best_score:
                        best_score = score
                        best_cid = cid
                if best_cid:
                    best_per_field[field] = (best_cid, best_score)

            # 从各分支 cherry-pick 最优字段
            base = branch_checkpoints[0]
            merged_id = base
            for field, (source_cid, _score) in best_per_field.items():
                if source_cid != merged_id:
                    try:
                        merged_id = self.cherry_pick(
                            thread_id, merged_id, source_cid, [field]
                        )
                    except Exception:
                        logger.warning(
                            "AgentBranchOps: failed to cherry-pick '%s' from %s",
                            field, source_cid[:12],
                        )

            self._ck.tag(thread_id, merged_id, "auto-merge:best-per-field")
            return merged_id

        raise ValueError(f"Unknown merge strategy: {strategy}")

    def _discover_fields(
        self, thread_id: str, checkpoint_ids: list[str]
    ) -> list[str]:
        """发现所有分支共有的 top-level state 字段。"""
        all_fields: set[str] = set()
        for cid in checkpoint_ids:
            try:
                state = self._ck.get_state(thread_id, cid)
                values = state.values if hasattr(state, "values") else state
                if isinstance(values, dict):
                    all_fields.update(values.keys())
            except Exception:
                pass
        return sorted(all_fields)
