"""A protocol-native A2A Provider for the competition-analysis black box.

The module uses the official ``a2a-sdk`` 1.1.2 route and protobuf types.  No
Hub-specific identifiers, callbacks, database fields, or authentication
objects are part of the public contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any

from a2a.server.events import Event
from a2a.server.request_handlers import RequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.types import a2a_pb2
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Artifact,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import TaskNotFoundError, UnsupportedOperationError
from google.protobuf.json_format import MessageToDict, ParseDict

from app.a2a.auth import A2AAuthMiddleware, A2AContextBuilder, auth_required
from app.a2a.store import A2AStore

logger = logging.getLogger(__name__)

_TERMINAL = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
}


def _safe(value: Any, *, depth: int = 0) -> Any:
    """Remove protocol-unsafe internal fields and bound artifact size."""
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        blocked = {"api_key", "prompt", "password", "token", "secret", "path", "traceback", "stack_trace"}
        return {str(k): _safe(v, depth=depth + 1) for k, v in value.items() if str(k).lower() not in blocked}
    if isinstance(value, list):
        return [_safe(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:100_000] if isinstance(value, str) else value
    return str(value)[:100_000]


def _state_name(state: int) -> str:
    return a2a_pb2.TaskState.Name(state).removeprefix("TASK_STATE_").lower()


def _agent_message(text: str) -> Message:
    return Message(
        message_id=f"msg-{uuid.uuid4().hex}",
        role=Role.ROLE_AGENT,
        parts=[Part(text=str(text)[:4000])],
    )


class CompetitionA2AHandler(RequestHandler):
    """Small SDK RequestHandler backed by SQLite and the existing workflow."""

    def __init__(self, store: A2AStore):
        self.store = store
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._running: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        try:
            self._concurrency = asyncio.Semaphore(max(1, int(os.getenv("CI_AGENT_A2A_MAX_CONCURRENCY", "4"))))
        except ValueError:
            self._concurrency = asyncio.Semaphore(4)

    async def start(self) -> None:
        """Requeue durable non-terminal tasks after an API process restart."""
        for item in self.store.recovery_candidates():
            task = item["task"]
            owner, tenant = item["owner_id"], item["tenant_id"]
            payload = self._message_payload(task.history[-1]) if task.history else {"text": "", "data": {}}
            self._schedule(task.id, payload, owner, tenant)

    async def stop(self) -> None:
        jobs = list(self._running.values())
        for job in jobs:
            if not job.done():
                job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        self._running.clear()

    def _schedule(self, task_id: str, payload: dict[str, Any], owner: str, tenant: str, delay: float = 0) -> None:
        async def delayed() -> None:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._run_task(task_id, payload, owner, tenant)

        current = self._running.get(task_id)
        if current is None or current.done():
            self._running[task_id] = asyncio.create_task(delayed())

    @staticmethod
    def _scope(context) -> tuple[str, str]:
        return str(context.state.get("a2a_owner") or context.user.user_name or "anonymous"), str(context.tenant or "")

    async def on_get_task(self, params: GetTaskRequest, context) -> Task | None:
        owner, tenant = self._scope(context)
        task = self.store.get(params.id, owner, tenant)
        if task is None:
            raise TaskNotFoundError
        return task

    async def on_list_tasks(self, params: ListTasksRequest, context) -> ListTasksResponse:
        owner, tenant = self._scope(context)
        tasks = self.store.list(owner, tenant, params.context_id, params.page_size or 50)
        if params.status:
            tasks = [task for task in tasks if task.status.state == params.status]
        return ListTasksResponse(tasks=tasks, page_size=len(tasks), total_size=len(tasks))

    async def on_cancel_task(self, params: CancelTaskRequest, context) -> Task | None:
        owner, tenant = self._scope(context)
        task = self.store.get(params.id, owner, tenant)
        if task is None:
            raise TaskNotFoundError
        if task.status.state in _TERMINAL:
            return task
        internal = self.store.internal_thread(task.id, owner, tenant)
        if internal:
            from app.competition_router import cancel_analysis_for_a2a

            await asyncio.to_thread(cancel_analysis_for_a2a, internal, user_id=owner)
        await self._publish_status(task, TaskState.TASK_STATE_CANCELED, "Task cancelled by caller")
        running = self._running.get(task.id)
        if running and not running.done():
            running.cancel()
        return task

    async def on_message_send(self, params: SendMessageRequest, context) -> Task | Message:
        task, _created = await self._accept(params, context)
        return task

    async def on_message_send_stream(self, params: SendMessageRequest, context) -> AsyncGenerator[Event]:
        task, _created = await self._accept(params, context)
        owner, tenant = self._scope(context)
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers[task.id].add(queue)
        try:
            last_sequence = max(0, int(context.state.get("a2a_last_event_id") or 0))
        except (TypeError, ValueError):
            last_sequence = 0
        try:
            yield task
            for item in self.store.events(task.id, owner, tenant, last_sequence):
                last_sequence = item["sequence"]
                event = self._event_from(item)
                if event is not None:
                    yield event
            current = self.store.get(task.id, owner, tenant)
            if current and current.status.state in _TERMINAL | {TaskState.TASK_STATE_INPUT_REQUIRED}:
                return
            while True:
                sequence, event = await queue.get()
                if sequence <= last_sequence:
                    continue
                last_sequence = sequence
                yield event
                if isinstance(event, TaskStatusUpdateEvent) and event.status.state in _TERMINAL | {TaskState.TASK_STATE_INPUT_REQUIRED}:
                    return
        finally:
            self._subscribers[task.id].discard(queue)
            if not self._subscribers[task.id]:
                self._subscribers.pop(task.id, None)

    async def on_subscribe_to_task(self, params: SubscribeToTaskRequest, context) -> AsyncGenerator[Event]:
        # Subscription is the same replayable stream without a new message.
        owner, tenant = self._scope(context)
        task = self.store.get(params.id, owner, tenant)
        if task is None:
            raise TaskNotFoundError
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers[task.id].add(queue)
        try:
            last_sequence = max(0, int(context.state.get("a2a_last_event_id") or 0))
        except (TypeError, ValueError):
            last_sequence = 0
        try:
            yield task
            for item in self.store.events(task.id, owner, tenant, last_sequence):
                last_sequence = item["sequence"]
                event = self._event_from(item)
                if event is not None:
                    yield event
            if task.status.state in _TERMINAL | {TaskState.TASK_STATE_INPUT_REQUIRED}:
                return
            while True:
                sequence, event = await queue.get()
                if sequence <= last_sequence:
                    continue
                last_sequence = sequence
                yield event
                if isinstance(event, TaskStatusUpdateEvent) and event.status.state in _TERMINAL | {TaskState.TASK_STATE_INPUT_REQUIRED}:
                    return
        finally:
            self._subscribers[task.id].discard(queue)

    async def _accept(self, params: SendMessageRequest, context) -> tuple[Task, bool]:
        owner, tenant = self._scope(context)
        message = params.message
        if not message.message_id:
            message.message_id = f"msg-{uuid.uuid4().hex}"
        task_id = message.task_id or f"task-{uuid.uuid4().hex}"
        context_id = message.context_id or f"ctx-{uuid.uuid4().hex}"
        message.task_id, message.context_id = task_id, context_id
        task = self.store.get(task_id, owner, tenant)
        created = task is None
        if created:
            task = Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
            task.history.append(message)
            self.store.create(task, owner=owner, tenant=tenant)
        else:
            if task.context_id != context_id:
                raise ValueError("Message context_id does not match the task")
            if task.status.state not in {TaskState.TASK_STATE_INPUT_REQUIRED}:
                if task.status.state in _TERMINAL:
                    raise ValueError("Task is already in a terminal state")
                raise ValueError("Task is already running")
            task.history.append(message)
            self.store.save(task, owner=owner, tenant=tenant)
        if created or task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            async with self._lock:
                previous = self._running.get(task_id)
                if previous is None or previous.done():
                    self._schedule(task_id, self._message_payload(message), owner, tenant)
        return task, created

    @staticmethod
    def _message_payload(message: Message) -> dict[str, Any]:
        text_parts: list[str] = []
        data: dict[str, Any] = {}
        for part in message.parts:
            if part.text:
                text_parts.append(part.text)
            if part.HasField("data"):
                data.update(MessageToDict(part.data, preserving_proto_field_name=False))
        return {"text": "\n".join(text_parts).strip(), "data": _safe(data)}

    async def _run_task(self, task_id: str, payload: dict[str, Any], owner: str, tenant: str) -> None:
        lease_seconds = max(30, int(os.getenv("CI_AGENT_A2A_LEASE_SECONDS", "120")))
        if not self.store.claim_execution(task_id, owner, tenant, lease_seconds):
            return
        try:
            async with self._concurrency:
                await self._run_task_limited(task_id, payload, owner, tenant)
        except asyncio.CancelledError:
            self.store.release_execution(task_id, owner, tenant)
            raise
        except Exception as exc:
            logger.exception("A2A task %s failed", task_id)
            self.store.release_execution(task_id, owner, tenant, str(exc))
            task = self.store.get(task_id, owner, tenant)
            if task is None or task.status.state in _TERMINAL:
                return
            info = self.store.execution_info(task_id, owner, tenant) or {}
            attempts = int(info.get("attempts") or 0)
            max_attempts = int(info.get("max_attempts") or self.store.max_attempts())
            if attempts < max_attempts:
                await self._publish_status(task, TaskState.TASK_STATE_SUBMITTED, f"执行失败，将在重试后继续（{attempts}/{max_attempts}）")
                delay = min(60, 2 ** max(0, attempts - 1))
                self._running.pop(task_id, None)
                self._schedule(task_id, payload, owner, tenant, delay=delay)
            else:
                await self._publish_status(task, TaskState.TASK_STATE_FAILED, "竞品分析任务执行失败")
        finally:
            self.store.release_execution(task_id, owner, tenant)

    async def _run_task_limited(self, task_id: str, payload: dict[str, Any], owner: str, tenant: str) -> None:
        task = self.store.get(task_id, owner, tenant)
        if task is None or task.status.state in _TERMINAL:
            return
        try:
            event_loop = asyncio.get_running_loop()
            await self._publish_status(task, TaskState.TASK_STATE_WORKING, "竞品分析已进入后台执行")
            internal = self.store.internal_thread(task_id, owner, tenant)
            data = payload.get("data") or {}
            if internal:
                from app.competition_router import continue_analysis_for_a2a

                result = await asyncio.to_thread(
                    continue_analysis_for_a2a,
                    internal,
                    payload.get("text", ""),
                    user_id=owner,
                    brief=data.get("brief") if isinstance(data.get("brief"), dict) else None,
                    event_loop=event_loop,
                )
            else:
                from app.competition_router import start_analysis_for_a2a

                products = data.get("target_products") if isinstance(data.get("target_products"), list) else []
                result = await asyncio.to_thread(
                    start_analysis_for_a2a,
                    data.get("query") or payload.get("text", ""),
                    products,
                    user_id=owner,
                    context_report=data.get("context_report") if isinstance(data.get("context_report"), dict) else None,
                    event_loop=event_loop,
                )
                internal = result["thread_id"]
                task = self.store.get(task_id, owner, tenant)
                self.store.save(task, owner=owner, tenant=tenant, internal_thread_id=internal)
            if result.get("status") == "awaiting_confirmation":
                await self._publish_status(
                    task,
                    TaskState.TASK_STATE_INPUT_REQUIRED,
                    "请补充或确认 Analysis Brief 后继续执行",
                    metadata={"required_input": "analysis_brief", "analysis_brief": _safe(result.get("analysis_brief"))},
                )
                return
            await self._poll_internal(task_id, internal, owner, tenant)
        except asyncio.CancelledError:
            raise

    async def _poll_internal(self, task_id: str, internal: str, owner: str, tenant: str) -> None:
        from app.competition_router import get_analysis_for_a2a

        timeout = max(30, int(os.getenv("CI_AGENT_A2A_TASK_TIMEOUT_SECONDS", "3600")))
        deadline = time.monotonic() + timeout
        last_progress = ""
        while time.monotonic() < deadline:
            snapshot = await asyncio.to_thread(get_analysis_for_a2a, internal, user_id=owner)
            if snapshot is None:
                raise RuntimeError("internal analysis disappeared")
            task = self.store.get(task_id, owner, tenant)
            if task is None or task.status.state == TaskState.TASK_STATE_CANCELED:
                return
            status = snapshot.get("status", "running")
            progress = snapshot.get("progress") or snapshot.get("current_node") or ""
            if progress and progress != last_progress:
                last_progress = progress
                await self._publish_status(task, TaskState.TASK_STATE_WORKING, progress, metadata={"progress": progress, "internal_stage": snapshot.get("current_node", "")})
            if status == "awaiting_confirmation":
                await self._publish_status(task, TaskState.TASK_STATE_INPUT_REQUIRED, "请确认分析范围后继续")
                return
            if status in {"failed", "error"}:
                raise RuntimeError("internal competition analysis failed")
            if status in {"completed", "approved", "partial"}:
                report = _safe(snapshot.get("report_data") or {})
                await self._publish_artifact(task, report, "competition-report", "完整竞品分析报告")
                await self._publish_status(task, TaskState.TASK_STATE_COMPLETED, "竞品分析已完成")
                return
            await asyncio.sleep(1.0)
        raise TimeoutError("A2A task timed out")

    async def _publish_status(self, task: Task, state: int, text: str, metadata: dict[str, Any] | None = None) -> None:
        if task.status.state in _TERMINAL:
            return
        task.status.CopyFrom(TaskStatus(state=state, message=_agent_message(text)))
        owner, tenant = await self._owner_for(task.id)
        if not self.store.save(task, owner=owner, tenant=tenant):
            return
        event = TaskStatusUpdateEvent(task_id=task.id, context_id=task.context_id, status=task.status, metadata=_safe(metadata or {}))
        await self._emit(task.id, owner, tenant, "status", event)

    async def _publish_artifact(self, task: Task, report: dict[str, Any], artifact_id: str, name: str) -> None:
        if task.status.state in _TERMINAL:
            return
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if len(payload) > 2_000_000:
            payload = payload[:2_000_000] + "\n[truncated]"
        artifact = Artifact(artifact_id=artifact_id, name=name, description="Sanitized competition analysis report", parts=[Part(text=payload, media_type="application/json")])
        task.artifacts.append(artifact)
        owner, tenant = await self._owner_for(task.id)
        if not self.store.save(task, owner=owner, tenant=tenant):
            return
        event = TaskArtifactUpdateEvent(task_id=task.id, context_id=task.context_id, artifact=artifact, last_chunk=True)
        await self._emit(task.id, owner, tenant, "artifact", event)

    async def _owner_for(self, task_id: str) -> tuple[str, str]:
        # Subscribers/tasks are always addressed through their owner.  The
        # in-process map avoids exposing owner data in the wire protocol.
        conn = self.store._conn()
        try:
            row = conn.execute("SELECT owner_id, tenant_id FROM a2a_tasks WHERE task_id = ?", (task_id,)).fetchone()
            return (row[0], row[1]) if row else ("anonymous", "")
        finally:
            conn.close()

    async def _emit(self, task_id: str, owner: str, tenant: str, kind: str, event: Event) -> None:
        payload = MessageToDict(event, preserving_proto_field_name=False)
        sequence = self.store.append_event(task_id, owner, tenant, kind, payload)
        for queue in list(self._subscribers.get(task_id, ())):
            try:
                queue.put_nowait((sequence, event))
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

    @staticmethod
    def _event_from(item: dict[str, Any]) -> Event | None:
        kind, payload = item.get("kind"), item.get("payload") or {}
        try:
            if kind == "status":
                return ParseDict(payload, TaskStatusUpdateEvent())
            if kind == "artifact":
                return ParseDict(payload, TaskArtifactUpdateEvent())
        except Exception:
            logger.warning("Unable to replay A2A event", exc_info=True)
        return None

    async def on_create_task_push_notification_config(self, params: TaskPushNotificationConfig, context) -> TaskPushNotificationConfig:
        raise UnsupportedOperationError(message="Push notifications are not supported")

    async def on_get_task_push_notification_config(self, params: GetTaskPushNotificationConfigRequest, context) -> TaskPushNotificationConfig:
        raise UnsupportedOperationError(message="Push notifications are not supported")

    async def on_list_task_push_notification_configs(self, params: ListTaskPushNotificationConfigsRequest, context) -> ListTaskPushNotificationConfigsResponse:
        raise UnsupportedOperationError(message="Push notifications are not supported")

    async def on_delete_task_push_notification_config(self, params: DeleteTaskPushNotificationConfigRequest, context) -> None:
        raise UnsupportedOperationError(message="Push notifications are not supported")

    async def on_get_extended_agent_card(self, params: GetExtendedAgentCardRequest, context) -> AgentCard:
        raise UnsupportedOperationError(message="Extended AgentCard is not supported")


def build_agent_card(base_url: str) -> AgentCard:
    security = {}
    requirements = []
    if auth_required():
        security["bearerAuth"] = a2a_pb2.SecurityScheme(
            http_auth_security_scheme=a2a_pb2.HTTPAuthSecurityScheme(
                scheme="Bearer",
                bearer_format="API key",
                description="Use the configured A2A API key as a Bearer token",
            )
        )
        requirements.append(a2a_pb2.SecurityRequirement(schemes={"bearerAuth": a2a_pb2.StringList(list=["bearerAuth"])}))
    return AgentCard(
        name="Competitive-Analysis-Agent",
        description="A black-box agent that researches competitors and returns evidence-backed comparison reports.",
        supported_interfaces=[AgentInterface(url=f"{base_url.rstrip('/')}/a2a", protocol_binding="JSON_RPC", protocol_version="1.0")],
        provider=AgentProvider(organization="Competitive-Analysis-Agent", url=base_url),
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        security_schemes=security,
        security_requirements=requirements,
        default_input_modes=["text", "application/json"],
        default_output_modes=["application/json", "text/markdown"],
        skills=[
            AgentSkill(
                id="competitive-analysis",
                name="Competitive analysis",
                description="Compare named or inferred products across decision dimensions with sources, matrix, SWOT, trends, and quality metrics.",
                tags=["competition", "research", "rag"],
                examples=["Compare Cursor and GitHub Copilot for an engineering team"],
                input_modes=["text", "application/json"],
                output_modes=["application/json", "text/markdown"],
            )
        ],
    )


def install_a2a_provider(app) -> None:
    """Install the independent A2A card, JSON-RPC, and REST routes."""
    if os.getenv("CI_AGENT_A2A_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return
    app.add_middleware(A2AAuthMiddleware)
    base_url = os.getenv("CI_AGENT_A2A_PUBLIC_URL", "http://127.0.0.1:8001")
    store = A2AStore()
    handler = CompetitionA2AHandler(store)
    app.state.a2a_handler = handler
    card = build_agent_card(base_url)
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a", context_builder=A2AContextBuilder()),
        rest_routes=create_rest_routes(handler, context_builder=A2AContextBuilder(), path_prefix="/a2a"),
    )


__all__ = ["CompetitionA2AHandler", "build_agent_card", "install_a2a_provider"]
