"""分支合并 — 两个分支节点的差异分析与合并准备。

P2 功能：用户选择两个分支版本 → 分析差异 → 生成合并提示 → 创建新合并节点。
LLM 调用在 competition 层完成；本模块负责数据准备和版本记录。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from competition.branchtree.diff import snapshot_diff

if TYPE_CHECKING:
    from competition.branchtree.adapter import BranchTreeAdapter


def find_common_ancestor(
    adapter: BranchTreeAdapter,
    thread_id: str,
    version_a: int,
    version_b: int,
) -> int | None:
    """找到两个版本的最近公共祖先版本。

    沿 lineage 回溯，返回第一个共同版本号。
    """
    

    # 通过内部 tree 获取 lineage
    tree = adapter._tree
    tree.load(thread_id)

    chain_a = [n.node_id for n in tree.lineage(version_a)]
    chain_b = {n.node_id for n in tree.lineage(version_b)}

    # 从后往前找第一个在 chain_b 中出现的（最近的公共祖先）
    for node_id in reversed(chain_a):
        ver = int(node_id[1:])
        if node_id in chain_b:
            return ver

    return None


def merge_prepare(
    adapter: BranchTreeAdapter,
    thread_id: str,
    version_a: int,
    version_b: int,
) -> dict:
    """准备合并数据：获取两个版本的快照 + 差异分析 + 公共祖先。

    Returns:
        {
            "version_a": int,
            "version_b": int,
            "state_a": dict,        # version_a 的快照数据
            "state_b": dict,        # version_b 的快照数据
            "diff_a_to_b": dict,    # a → b 的差异
            "common_ancestor": int | None,  # 最近公共祖先版本号
            "merge_prompt": str,    # 可直接发给 LLM 的合并提示
        }
    """
    state_a = adapter.restore_state(thread_id, version_a)
    state_b = adapter.restore_state(thread_id, version_b)
    diff = snapshot_diff(state_a, state_b)
    ancestor = find_common_ancestor(adapter, thread_id, version_a, version_b)

    prompt = _build_merge_prompt(
        version_a, version_b, ancestor, state_a, state_b, diff
    )

    return {
        "version_a": version_a,
        "version_b": version_b,
        "state_a": state_a,
        "state_b": state_b,
        "diff_a_to_b": diff,
        "common_ancestor": ancestor,
        "merge_prompt": prompt,
    }


def merge_execute(
    adapter: BranchTreeAdapter,
    thread_id: str,
    version_a: int,
    version_b: int,
    merged_state: dict,
    base_version: int | None = None,
) -> int:
    """将合并结果记录为新版本。

    Args:
        adapter: BranchTreeAdapter 实例。
        thread_id: 线程 ID。
        version_a, version_b: 被合并的两个版本。
        merged_state: LLM 合并后的新 state（可以是部分字段）。
        base_version: 新节点的父版本号。默认取 version_a 和 version_b 中较新的。

    Returns:
        新版本号。
    """
    if base_version is None:
        base_version = max(version_a, version_b)

    ancestor = find_common_ancestor(adapter, thread_id, version_a, version_b)

    return adapter.snapshot(
        thread_id=thread_id,
        action="merge",
        metadata={
            "merged_from": [version_a, version_b],
            "common_ancestor": ancestor,
            "merged_state": merged_state,
        },
    )


def _build_merge_prompt(
    version_a: int,
    version_b: int,
    ancestor: int | None,
    state_a: dict,
    state_b: dict,
    diff: dict,
) -> str:
    """构建 LLM 合并提示词。

    这个提示词的输出可以直接作为 writer 的输入来生成合并报告。
    """
    lines = [
        "## 分支合并任务",
        "",
        "请合并以下两个分析版本的内容，保留各自的优点，消除冲突：",
        f"- 版本 A (v{version_a})",
        f"- 版本 B (v{version_b})",
    ]
    if ancestor is not None:
        lines.append(f"- 公共祖先: v{ancestor}（两分支从这里分叉）")

    lines.append("")
    lines.append("### 差异摘要")
    lines.append(diff.get("summary", "no differences detected"))

    # Include report data comparison
    report_a = state_a.get("report_data", {})
    report_b = state_b.get("report_data", {})
    if isinstance(report_a, dict) and isinstance(report_b, dict):
        sections_a = set(report_a.keys())
        sections_b = set(report_b.keys())
        only_a = sections_a - sections_b
        only_b = sections_b - sections_a
        common = sections_a & sections_b
        if only_a:
            lines.append(f"- 仅 A 有的章节: {', '.join(sorted(only_a))}")
        if only_b:
            lines.append(f"- 仅 B 有的章节: {', '.join(sorted(only_b))}")
        if common:
            lines.append(f"- 共同章节: {', '.join(sorted(common))}")

    lines.append("")
    lines.append("### 合并要求")
    lines.append("1. 保留两个版本中各自优于对方的部分")
    lines.append("2. 如果存在冲突，选择信息更完整或时间更新的版本")
    lines.append("3. 标注哪些内容来自哪个版本（内联引用 [vA] / [vB]）")
    lines.append("4. 输出格式与标准分析报告一致")

    return "\n".join(lines)
