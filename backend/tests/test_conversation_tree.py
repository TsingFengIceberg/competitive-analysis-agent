"""Tests for ConversationTree."""

from __future__ import annotations

from unittest.mock import MagicMock

from deerflow.branchtree.conversation_tree import (
    ConversationTree,
    _msg_preview,
    _msg_role,
)

# ── Helpers ────────────────────────────────────────────────────


def _make_msg(role: str, content: str):
    """Create a mock LangGraph message."""
    msg = MagicMock()
    # Use type name to control _msg_role detection
    if role == "user":
        type(msg).__name__ = "HumanMessage"
    elif role == "assistant":
        type(msg).__name__ = "AIMessage"
    elif role == "tool":
        type(msg).__name__ = "ToolMessage"
    elif role == "system":
        type(msg).__name__ = "SystemMessage"
    else:
        type(msg).__name__ = "UnknownMessage"
    msg.content = content
    return msg


# ── _msg_role tests ────────────────────────────────────────────


class TestMsgRole:
    def test_human_message(self):
        msg = _make_msg("user", "hello")
        assert _msg_role(msg) == "user"

    def test_ai_message(self):
        msg = _make_msg("assistant", "response")
        assert _msg_role(msg) == "assistant"

    def test_tool_message(self):
        msg = _make_msg("tool", '{"result": 42}')
        assert _msg_role(msg) == "tool"

    def test_system_message(self):
        msg = _make_msg("system", "system prompt")
        assert _msg_role(msg) == "system"

    def test_unknown(self):
        msg = _make_msg("custom", "content")
        assert _msg_role(msg) == "unknown"


# ── _msg_preview tests ─────────────────────────────────────────


class TestMsgPreview:
    def test_short_message(self):
        assert _msg_preview(_make_msg("user", "hello")) == "hello"

    def test_long_message_truncated(self):
        long_text = "a" * 100
        result = _msg_preview(_make_msg("user", long_text))
        assert len(result) == 83  # 80 + "..."
        assert result.endswith("...")

    def test_multimodal_message(self):
        msg = MagicMock()
        msg.content = [
            {"type": "text", "text": "from image"},
            {"type": "image_url", "image_url": {}},
        ]
        assert _msg_preview(msg) == "from image"


# ── ConversationTree tests ─────────────────────────────────────


class TestConversationTree:
    def test_serialize_empty(self):
        tree = ConversationTree(MagicMock(), MagicMock())
        result = tree._serialize_state({})
        assert result == {"messages": [], "message_count": 0}

    def test_serialize_messages(self):
        msgs = [
            _make_msg("user", "分析Cursor"),
            _make_msg("assistant", "正在搜索..."),
            _make_msg("tool", '{"results": [1,2,3]}'),
            _make_msg("assistant", "分析完成"),
        ]

        tree = ConversationTree(MagicMock(), MagicMock())
        result = tree._serialize_state({"messages": msgs})

        assert result["message_count"] == 4
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "分析Cursor"
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][2]["role"] == "tool"
        assert result["messages"][3]["role"] == "assistant"

    def test_serialize_unknown_role(self):
        msg = _make_msg("custom", "unusual")
        tree = ConversationTree(MagicMock(), MagicMock())
        result = tree._serialize_state({"messages": [msg]})
        assert result["messages"][0]["role"] == "unknown"

    def test_is_subclass_of_branch_tree(self):
        from deerflow.branchtree.tree import BranchTree
        assert issubclass(ConversationTree, BranchTree)
