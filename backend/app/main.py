"""FastAPI application for Competitive Analysis Agent.

A minimal FastAPI app that mounts the competition router without any
Provides auth endpoints backed by a simple SQLite user store and JWT cookie auth.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# ── Constants ──
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_DAYS = 7
AUTH_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".ci-agent", "auth.db")

# ── CORS origins ──
_cors_env = os.getenv("GATEWAY_CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]


# ── Minimal auth DB ──

def _get_auth_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            system_role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL,
            token_version INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    return conn


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
    return f"pbkdf2:sha256:600000${salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo_iter, salt, expected = stored.split("$", 2)
        if not algo_iter.startswith("pbkdf2:sha256"):
            return False
        _, _, iterations_str = algo_iter.rpartition(":")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                 int(iterations_str))
        return dk.hex() == expected
    except Exception:
        return False


def _create_token(user_id: str, token_version: int = 0) -> str:
    now = datetime.now(UTC)
    return pyjwt.encode({
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRY_DAYS),
        "ver": token_version,
    }, JWT_SECRET, algorithm="HS256")


def _decode_token(token: str) -> dict | None:
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def _read_user(user_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    close_conn = conn is None
    if conn is None:
        conn = _get_auth_conn()
    row = conn.execute(
        "SELECT id, email, system_role, password_hash, token_version FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if close_conn:
        conn.close()
    if row is None:
        return None
    return {
        "id": row[0], "email": row[1], "system_role": row[2],
        "password_hash": row[3], "token_version": row[4],
    }


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,  # local dev; set True behind HTTPS
        samesite="lax",
        max_age=JWT_EXPIRY_DAYS * 24 * 3600,
        path="/",
    )


def create_app() -> FastAPI:
    """Create the standalone FastAPI application."""

    enable_docs = os.getenv("GATEWAY_ENABLE_DOCS", "true").lower() == "true"

    app = FastAPI(
        title="Competitive-Analysis-Agent API",
        version="0.1.0",
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
    )

    if _cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── Auth endpoints ──

    @app.post("/api/v1/auth/register")
    async def auth_register(request: Request, response: Response):
        """Register a new user and log them in."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="Valid email required")
        if not password or len(password) < 4:
            raise HTTPException(status_code=400, detail="Password must be at least 4 characters")

        conn = _get_auth_conn()
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.close()
            raise HTTPException(status_code=409, detail="Email already registered")

        user_id = secrets.token_hex(16)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, system_role, created_at, token_version) "
            "VALUES (?, ?, ?, 'user', ?, 0)",
            (user_id, email, _hash_password(password), now),
        )
        conn.commit()
        conn.close()

        token = _create_token(user_id, 0)
        _set_cookie(response, token)
        logger.info("User registered: %s (%s)", email, user_id)
        return {"id": user_id, "email": email, "needs_setup": False,
                "expires_in": JWT_EXPIRY_DAYS * 24 * 3600}

    @app.post("/api/v1/auth/login/local")
    async def auth_login(request: Request, response: Response):
        """Login with email/password."""
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
            email = (body.get("email") or body.get("username") or "").strip().lower()
            password = body.get("password") or ""
        else:
            raw = await request.body()
            params = dict(p.split("=", 1) for p in raw.decode().split("&") if "=" in p)
            email = (params.get("username") or "").strip().lower()
            # URL-decode the email if needed
            from urllib.parse import unquote
            email = unquote(email)
            password = params.get("password") or ""

        if not email or not password:
            raise HTTPException(status_code=401, detail="Email and password required")

        conn = _get_auth_conn()
        row = conn.execute(
            "SELECT id, email, password_hash, token_version FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None or not _verify_password(password, row[2]):
            conn.close()
            raise HTTPException(status_code=401, detail="Incorrect email or password")

        user_id, user_email, _, token_version = row
        conn.close()

        token = _create_token(user_id, token_version)
        _set_cookie(response, token)
        return {"id": user_id, "email": user_email, "needs_setup": False,
                "expires_in": JWT_EXPIRY_DAYS * 24 * 3600}

    @app.post("/api/v1/auth/logout")
    async def auth_logout(response: Response):
        """Clear the auth cookie."""
        response.delete_cookie(key="access_token", path="/")
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    async def auth_me(request: Request):
        """Return current user info from JWT cookie."""
        token = request.cookies.get("access_token", "")
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        payload = _decode_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = _read_user(payload["sub"])
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        if user["token_version"] != payload.get("ver", 0):
            raise HTTPException(status_code=401, detail="Token revoked")
        return {
            "id": user["id"],
            "email": user["email"],
            "system_role": user["system_role"],
            "needs_setup": False,
        }

    # ── Competition router ──
    from app.competition_router import router as competition_router
    from app.competition_router import (
        start_knowledge_runtime,
        start_observation_runtime,
        stop_knowledge_runtime,
        stop_observation_runtime,
    )

    app.include_router(competition_router)

    @app.on_event("startup")
    async def start_background_services():
        start_knowledge_runtime()
        if os.getenv("CI_AGENT_OBSERVATION_SCHEDULER_ENABLED", "true").lower() == "true":
            try:
                poll_seconds = int(os.getenv("CI_AGENT_OBSERVATION_POLL_SECONDS", "30"))
            except ValueError:
                logger.warning("Invalid CI_AGENT_OBSERVATION_POLL_SECONDS; using 30 seconds")
                poll_seconds = 30
            start_observation_runtime(poll_seconds)

    @app.on_event("shutdown")
    async def stop_background_services():
        stop_observation_runtime()
        stop_knowledge_runtime()
        from competition.knowledge_service import close_knowledge_service

        close_knowledge_service()

    # ── Health ──
    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "competitive-analysis-agent"}

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready():
        try:
            from competition.db import init_db
            conn = init_db()
            conn.execute("SELECT 1")
            conn.close()
            try:
                from competition.knowledge_service import get_knowledge_service

                knowledge = await __import__("asyncio").to_thread(
                    get_knowledge_service().status, "default"
                )
            except Exception as knowledge_error:
                knowledge = {"index": {"available": False, "error": str(knowledge_error)[:200]}}
            return {
                "status": "ready",
                "database": "connected",
                "knowledge": knowledge,
                "knowledge_required": False,
            }
        except Exception as e:
            return {"status": "not ready", "database": str(e)[:100]}

    return app


# ── Uvicorn entry point ──
app = create_app()
