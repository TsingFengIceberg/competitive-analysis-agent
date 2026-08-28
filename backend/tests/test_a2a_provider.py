from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest
from a2a.server.context import ServerCallContext
from a2a.types.a2a_pb2 import (
    Artifact,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
    TaskState,
    TaskStatus,
)
from google.protobuf.json_format import MessageToDict

from app.a2a.provider import CompetitionA2AHandler, build_agent_card
from app.a2a.store import A2AStore


def _context(owner: str = "client-a", tenant: str = "tenant-a") -> ServerCallContext:
    return ServerCallContext(state={"a2a_owner": owner}, tenant=tenant)


@pytest.mark.asyncio
async def test_agent_card_declares_a2a_1_and_capabilities() -> None:
    card = MessageToDict(build_agent_card("http://localhost:8001"), preserving_proto_field_name=False)
    assert card["name"] == "Competitive-Analysis-Agent"
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert card["capabilities"]["streaming"] is True
    assert "competitive-analysis" in {item["id"] for item in card["skills"]}


@pytest.mark.asyncio
async def test_task_mapping_persists_owner_context_and_supports_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    handler = CompetitionA2AHandler(store)

    async def hold(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(handler, "_run_task", hold)
    request = SendMessageRequest(
        message=Message(role=Role.ROLE_USER, parts=[Part(text="Compare Cursor and Codex")])
    )
    task = await handler.on_message_send(request, _context())
    assert task.status.state == TaskState.TASK_STATE_SUBMITTED
    restored = await handler.on_get_task(GetTaskRequest(id=task.id), _context())
    assert restored and restored.context_id == task.context_id
    cancelled = await handler.on_cancel_task(type("Cancel", (), {"id": task.id})(), _context())
    assert cancelled.status.state == TaskState.TASK_STATE_CANCELED
    assert await handler.on_get_task(GetTaskRequest(id=task.id), _context())


@pytest.mark.asyncio
async def test_message_stream_emits_status_artifact_and_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    handler = CompetitionA2AHandler(store)

    async def fake_run(task_id, _payload, owner, tenant):
        task = store.get(task_id, owner, tenant)
        await handler._publish_status(task, TaskState.TASK_STATE_WORKING, "working")
        await handler._publish_artifact(task, {"title": "demo"}, "report", "Report")
        await handler._publish_status(task, TaskState.TASK_STATE_COMPLETED, "done")

    monkeypatch.setattr(handler, "_run_task", fake_run)
    request = SendMessageRequest(
        message=Message(role=Role.ROLE_USER, parts=[Part(text="Compare Cursor and Codex")])
    )
    events = []
    async for event in handler.on_message_send_stream(request, _context()):
        events.append(event)
    assert events[0].id.startswith("task-")
    assert any(event.DESCRIPTOR.name == "TaskStatusUpdateEvent" and event.status.state == TaskState.TASK_STATE_WORKING for event in events)
    assert any(event.DESCRIPTOR.name == "TaskArtifactUpdateEvent" for event in events)
    assert any(event.DESCRIPTOR.name == "TaskStatusUpdateEvent" and event.status.state == TaskState.TASK_STATE_COMPLETED for event in events)


@pytest.mark.asyncio
async def test_cross_tenant_task_is_not_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    handler = CompetitionA2AHandler(store)
    monkeypatch.setattr(handler, "_run_task", lambda *_args: asyncio.sleep(0))
    request = SendMessageRequest(message=Message(role=Role.ROLE_USER, parts=[Part(text="Compare A and B")]))
    task = await handler.on_message_send(request, _context("client-a", "tenant-a"))
    with pytest.raises(Exception):
        await handler.on_get_task(GetTaskRequest(id=task.id), _context("client-b", "tenant-a"))
    with pytest.raises(Exception):
        await handler.on_get_task(GetTaskRequest(id=task.id), _context("client-a", "tenant-b"))


@pytest.mark.asyncio
async def test_persisted_events_replay_after_handler_recreation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    first = CompetitionA2AHandler(store)
    monkeypatch.setattr(first, "_run_task", lambda *_args: asyncio.sleep(0))
    request = SendMessageRequest(message=Message(role=Role.ROLE_USER, parts=[Part(text="Compare A and B")]))
    task = await first.on_message_send(request, _context())
    await first._publish_status(task, TaskState.TASK_STATE_WORKING, "replay me")
    recreated = CompetitionA2AHandler(A2AStore(tmp_path / "a2a.db"))
    restored = await recreated.on_get_task(GetTaskRequest(id=task.id), _context())
    events = recreated.store.events(task.id, "client-a", "tenant-a")
    assert restored and restored.status.state == TaskState.TASK_STATE_WORKING
    assert events and events[0]["kind"] == "status"


@pytest.mark.asyncio
async def test_start_requeues_submitted_tasks_after_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    task = Task(id="task-recover", context_id="ctx-recover", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
    task.history.append(Message(role=Role.ROLE_USER, parts=[Part(text="recover this task")]))
    store.create(task, owner="client-a", tenant="tenant-a")
    handler = CompetitionA2AHandler(store)
    called = asyncio.Event()
    captured: dict[str, object] = {}

    async def fake_run(task_id, payload, owner, tenant):
        captured.update(task_id=task_id, payload=payload, owner=owner, tenant=tenant)
        called.set()

    monkeypatch.setattr(handler, "_run_task", fake_run)
    await handler.start()
    await asyncio.wait_for(called.wait(), timeout=1)
    assert captured == {
        "task_id": "task-recover",
        "payload": {"text": "recover this task", "data": {}},
        "owner": "client-a",
        "tenant": "tenant-a",
    }
    await handler.stop()


@pytest.mark.asyncio
async def test_execution_lease_is_exclusive(tmp_path: Path) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    task = Task(id="task-lease", context_id="ctx-lease", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
    store.create(task, owner="client-a", tenant="tenant-a")
    assert store.claim_execution(task.id, "client-a", "tenant-a") is True
    assert store.claim_execution(task.id, "client-a", "tenant-a") is False


@pytest.mark.asyncio
async def test_terminal_state_cannot_be_overwritten_by_late_result(tmp_path: Path) -> None:
    store = A2AStore(tmp_path / "a2a.db")
    task = Task(id="task-terminal", context_id="ctx-terminal", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
    store.create(task, owner="client-a", tenant="tenant-a")
    task.status.state = TaskState.TASK_STATE_CANCELED
    assert store.save(task, owner="client-a", tenant="tenant-a") is True
    stale = Task(id=task.id, context_id=task.context_id, status=TaskStatus(state=TaskState.TASK_STATE_WORKING))
    stale.artifacts.append(Artifact(artifact_id="late"))
    assert store.save(stale, owner="client-a", tenant="tenant-a") is False
    restored = store.get(task.id, "client-a", "tenant-a")
    assert restored and restored.status.state == TaskState.TASK_STATE_CANCELED
    assert not restored.artifacts


@pytest.mark.asyncio
async def test_failed_task_reaches_terminal_state_after_retry_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_AGENT_A2A_MAX_ATTEMPTS", "1")
    store = A2AStore(tmp_path / "a2a.db")
    handler = CompetitionA2AHandler(store)

    async def fail(*_args):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(handler, "_run_task_limited", fail)
    request = SendMessageRequest(message=Message(role=Role.ROLE_USER, parts=[Part(text="Compare A and B")]))
    task = await handler.on_message_send(request, _context())
    await asyncio.sleep(0.05)
    failed = store.get(task.id, "client-a", "tenant-a")
    assert failed and failed.status.state == TaskState.TASK_STATE_FAILED
    assert (store.execution_info(task.id, "client-a", "tenant-a") or {}).get("attempts") == 1


@pytest.mark.asyncio
async def test_jsonrpc_routes_require_auth_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_AGENT_A2A_AUTH_REQUIRED", "true")
    monkeypatch.setenv("CI_AGENT_A2A_API_KEY", "test-key")
    monkeypatch.setenv("CI_AGENT_TASK_WORKER_ENABLED", "false")
    monkeypatch.setenv("CI_AGENT_OBSERVATION_SCHEDULER_ENABLED", "false")
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}})
        assert response.status_code == 401
        card = await client.get("/.well-known/agent-card.json")
        assert card.status_code == 200
    os.environ.pop("CI_AGENT_A2A_AUTH_REQUIRED", None)
    os.environ.pop("CI_AGENT_A2A_API_KEY", None)


@pytest.mark.asyncio
async def test_jsonrpc_protocol_version_and_error_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_AGENT_A2A_AUTH_REQUIRED", "false")
    monkeypatch.setenv("CI_AGENT_TASK_WORKER_ENABLED", "false")
    monkeypatch.setenv("CI_AGENT_OBSERVATION_SCHEDULER_ENABLED", "false")
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = {"jsonrpc": "2.0", "id": "missing", "method": "GetTask", "params": {"id": "missing"}}
        response = await client.post("/a2a", headers={"A2A-Version": "1.0"}, json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == "missing"
        assert payload["error"]["code"]
        assert "internal" not in response.text.lower()

        unsupported = await client.post("/a2a", json=body)
        assert unsupported.status_code == 200
        assert unsupported.json()["error"]["code"]
