"""Regression tests for settings concurrency and provider connection checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from httpx import ASGITransport, AsyncClient

from competition.db import get_user_settings, init_db, save_user_settings_if_current
from competition.settings_connection import ConnectionCheckError, run_connection_check


def test_settings_compare_and_swap_rejects_stale_token(tmp_path):
    conn = init_db(tmp_path / "settings.db")
    try:
        first = save_user_settings_if_current("user-1", {"default_model": "a"}, conn=conn)
        assert first["result"] == "saved"
        token = first["settings"]["updated_at"]

        second = save_user_settings_if_current("user-1", {"default_model": "b"}, token, conn=conn)
        assert second["result"] == "saved"
        assert second["settings"]["default_model"] == "b"

        stale = save_user_settings_if_current("user-1", {"default_model": "c"}, token, conn=conn)
        assert stale["result"] == "conflict"
        assert stale["settings"]["default_model"] == "b"
    finally:
        conn.close()


def test_settings_compare_and_swap_allows_one_concurrent_writer(tmp_path):
    db_path = tmp_path / "settings-race.db"
    setup = init_db(db_path)
    initial = save_user_settings_if_current("user-1", {"default_model": "initial"}, conn=setup)
    token = initial["settings"]["updated_at"]
    setup.close()

    def save(value: str) -> str:
        local = init_db(db_path)
        try:
            return save_user_settings_if_current("user-1", {"default_model": value}, token, conn=local)["result"]
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["one", "two"]))
    assert sorted(results) == ["conflict", "saved"]
    final = init_db(db_path)
    try:
        assert get_user_settings("user-1", final)["default_model"] in {"one", "two"}
    finally:
        final.close()


def test_connection_check_success_does_not_return_secret(monkeypatch):
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))

    monkeypatch.setattr("competition.settings_connection._request", fake_request)
    result = run_connection_check("llm", "primary", {
        "provider_keys": {"primary": "secret-value"},
        "provider_bases": {"primary": "https://llm.example/v1"},
    })
    assert result["ok"] is True
    assert "secret-value" not in str(result)
    assert calls == [("https://llm.example/v1/models", {"token": "secret-value"})]


def test_connection_check_rejects_missing_saved_provider():
    with pytest.raises(ConnectionCheckError, match="尚未配置") as error:
        run_connection_check("llm", "missing", {"provider_keys": {}, "provider_bases": {}})
    assert error.value.code == "missing_config"


@pytest.mark.asyncio
async def test_settings_routes_require_auth_and_return_conflict(monkeypatch):
    from fastapi import FastAPI

    import app.competition_router as competition_router

    app = FastAPI()
    app.include_router(competition_router.router)
    monkeypatch.setattr(competition_router, "_get_user_id", lambda _request: "user-1")
    monkeypatch.setattr("competition.db.get_user_settings", lambda _user: {"updated_at": "server-token"})
    monkeypatch.setattr(
        "competition.db.save_user_settings_if_current",
        lambda *_args, **_kwargs: {"result": "conflict", "settings": {"updated_at": "server-token", "default_model": "server"}},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/api/competition/settings", json={"settings": {"default_model": "draft"}, "expected_updated_at": "old-token"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "settings_conflict"
    assert response.json()["detail"]["settings"]["default_model"] == "server"


@pytest.mark.asyncio
async def test_settings_connection_route_uses_saved_provider(monkeypatch):
    from fastapi import FastAPI

    import app.competition_router as competition_router

    app = FastAPI()
    app.include_router(competition_router.router)
    monkeypatch.setattr(competition_router, "_get_user_id", lambda _request: "user-1")
    async def run_inline(function, *args):
        return function(*args)
    monkeypatch.setattr(competition_router.asyncio, "to_thread", run_inline)
    monkeypatch.setattr("competition.db.get_user_settings", lambda _user: {"provider_keys": {"primary": "secret"}, "provider_bases": {"primary": "https://example.test"}})
    monkeypatch.setattr("competition.settings_connection.run_connection_check", lambda kind, name, settings: {"ok": True, "kind": kind, "name": name, "latency_ms": 4, "message": "连接成功。"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/competition/settings/test-connection", json={"kind": "llm", "name": "primary"})
    assert response.status_code == 200
    assert response.json()["latency_ms"] == 4


@pytest.mark.asyncio
async def test_settings_connection_route_rejects_anonymous(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    import app.competition_router as competition_router

    monkeypatch.setattr(competition_router, "_get_user_id", lambda _request: "default")
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as error:
        await competition_router.test_settings_connection(
            competition_router.SettingsConnectionRequest(kind="llm", name="primary"), request,
        )
    assert error.value.status_code == 401
