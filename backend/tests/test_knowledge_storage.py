from __future__ import annotations

import pytest

from competition.knowledge_storage import LocalObjectStore, build_object_store, qdrant_connection_options


def test_local_object_store_round_trip_and_key_safety(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    assert store.put_bytes("docs/a.txt", b"hello", content_type="text/plain") == "docs/a.txt"
    assert store.get_bytes("docs/a.txt") == b"hello"
    store.delete("docs/a.txt")
    with pytest.raises(FileNotFoundError):
        store.get_bytes("docs/a.txt")
    with pytest.raises(ValueError):
        store.put_bytes("../outside", b"no")


def test_object_store_defaults_to_local(tmp_path, monkeypatch):
    monkeypatch.delenv("CI_AGENT_OBJECT_STORE", raising=False)
    monkeypatch.setenv("CI_AGENT_OBJECT_STORE_ROOT", str(tmp_path / "configured"))
    store = build_object_store(tmp_path / "fallback")
    assert isinstance(store, LocalObjectStore)
    assert store.root == (tmp_path / "configured").resolve()


def test_qdrant_connection_options_are_optional(monkeypatch):
    monkeypatch.delenv("CI_AGENT_RAG_QDRANT_URL", raising=False)
    monkeypatch.delenv("CI_AGENT_RAG_QDRANT_API_KEY", raising=False)
    assert qdrant_connection_options() == {"url": None, "api_key": None}
