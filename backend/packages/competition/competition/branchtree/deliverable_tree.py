"""DeliverableTree — 报告/可交付物版本分支。

BranchTree 的 P0 子类。节点存 report_data + analysis_result + collected_data。
"""

from __future__ import annotations

from deerflow.branchtree.tree import BranchTree


class DeliverableTree(BranchTree):
    """报告/可交付物版本分支树。

    节点 = {report_data, analysis_result, collected_data}
    分叉 = HITL 决策（重写/重分析/重搜索/批准）
    受众 = 用户（PM/创业者）
    """

    def _serialize_state(self, channel_values: dict) -> dict:
        """从 LangGraph channel_values 提取报告相关数据。"""
        return {
            "report_data": channel_values.get("report_data"),
            "analysis_result": channel_values.get("analysis_result"),
            "collected_data": channel_values.get("collected_data"),
        }
