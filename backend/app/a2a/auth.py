"""Authentication and caller scoping for the A2A transport."""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque

from a2a.auth.user import User
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import DefaultServerCallContextBuilder
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class A2AUser(User):
    def __init__(self, name: str, authenticated: bool = True):
        self._name = name
        self._authenticated = authenticated

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    @property
    def user_name(self) -> str:
        return self._name


def _configured_key() -> str:
    return os.getenv("CI_AGENT_A2A_API_KEY", "").strip()


def auth_required() -> bool:
    explicit = os.getenv("CI_AGENT_A2A_AUTH_REQUIRED")
    if explicit is not None:
        return explicit.lower() not in {"0", "false", "no", "off"}
    return bool(_configured_key()) or os.getenv("CI_AGENT_DEBUG", "false").lower() != "true"


def _caller_id(headers) -> str:
    value = headers.get("x-a2a-client-id", "anonymous").strip()
    return value[:160] or "anonymous"


class A2AAuthMiddleware(BaseHTTPMiddleware):
    """Validate API-key/Bearer credentials and attach a tenant-scoped caller."""

    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not path.startswith("/a2a") and path != "/.well-known/agent-card.json":
            return await call_next(request)
        if path == "/.well-known/agent-card.json":
            return await call_next(request)

        try:
            max_bytes = max(1, int(os.getenv("CI_AGENT_A2A_MAX_REQUEST_BYTES", "1000000")))
            rate_limit = max(1, int(os.getenv("CI_AGENT_A2A_RATE_LIMIT_PER_MINUTE", "60")))
        except ValueError:
            max_bytes, rate_limit = 1_000_000, 60
        try:
            if int(request.headers.get("content-length", "0") or 0) > max_bytes:
                return JSONResponse({"error": {"code": "REQUEST_TOO_LARGE", "message": "A2A request is too large"}}, status_code=413)
        except ValueError:
            return JSONResponse({"error": {"code": "INVALID_CONTENT_LENGTH", "message": "Invalid content length"}}, status_code=400)

        configured = _configured_key()
        provided = request.headers.get("x-api-key", "")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        if auth_required() and (not configured or not provided or not hmac.compare_digest(provided, configured)):
            return JSONResponse(
                {"error": {"code": "AUTH_REQUIRED", "message": "A2A authentication is required"}},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        caller = _caller_id(request.headers)
        now = time.monotonic()
        recent = self._requests[caller]
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= rate_limit:
            return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "A2A request rate limit exceeded"}}, status_code=429)
        recent.append(now)
        request.scope["a2a_owner"] = caller
        request.scope["a2a_tenant"] = request.headers.get("x-a2a-tenant", "")[:160]
        request.scope["a2a_last_event_id"] = request.headers.get("last-event-id", "")[:80]
        return await call_next(request)


class A2AContextBuilder(DefaultServerCallContextBuilder):
    def build(self, request) -> ServerCallContext:
        context = super().build(request)
        owner = request.scope.get("a2a_owner", "anonymous")
        context.user = A2AUser(owner, authenticated=bool(request.scope.get("a2a_owner")))
        context.tenant = request.scope.get("a2a_tenant", "")
        context.state["a2a_owner"] = owner
        context.state["a2a_last_event_id"] = request.scope.get("a2a_last_event_id", "")
        return context


__all__ = ["A2AAuthMiddleware", "A2AContextBuilder", "A2AUser", "auth_required"]
