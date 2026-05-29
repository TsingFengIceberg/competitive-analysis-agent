"""ConversationTree — 对话消息分支树。

BranchTree 的 P1 子类。节点存 messages（对话历史）。
用户编辑历史消息时触发分叉——新消息路径成为独立分支。
"""

from __future__ import annotations

from deerflow.branchtree.tree import BranchTree


class ConversationTree(BranchTree):
    """对话消息分支树。

    节点 = {messages}
    分叉 = 用户编辑历史消息 → 新对话路径
    受众 = 用户（对话式交互场景）
    """

    def _serialize_state(self, channel_values: dict) -> dict:
        """从 LangGraph channel_values 提取消息相关数据。"""
        messages = channel_values.get("messages", [])
        # 只序列化可读的摘要信息，完整消息列表由 LangGraph checkpoint 管理
        return {
            "messages": [
                {
                    "role": _msg_role(m),
                    "content": _msg_preview(m),
                }
                for m in messages
            ],
            "message_count": len(messages),
        }


def _msg_role(msg) -> str:
    """提取消息角色：'user' | 'assistant' | 'tool' | 'system'."""
    type_name = type(msg).__name__
    if "Human" in type_name:
        return "user"
    if "AI" in type_name or "Assistant" in type_name:
        return "assistant"
    if "Tool" in type_name:
        return "tool"
    if "System" in type_name:
        return "system"
    return "unknown"


def _msg_preview(msg, max_len: int = 80) -> str:
    """提取消息文本预览（截断到 max_len 字符）。"""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content[:max_len] + ("..." if len(content) > max_len else "")
    if isinstance(content, list):
        # 多模态消息：取第一个 text block
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                return text[:max_len] + ("..." if len(text) > max_len else "")
        return "[multimodal]"
    return str(content)[:max_len]
