"""Independent gateway for Competitive-Analysis-Agent.

A minimal FastAPI app that mounts the competition router without any
dependency on the DeerFlow framework. Provides just enough auth stubs
for the competition frontend to work (auto-login with demo account).
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# ── CORS origins ──────────────────────────────────────────────────────
_cors_env = os.getenv("GATEWAY_CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]


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

    # ── CORS ──────────────────────────────────────────────────────────
    if _cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── Auth stubs (for competition frontend auto-login) ──────────────
    # The competition page auto-registers/logs-in with demo credentials.
    # We accept any credentials and return success.

    @app.post("/api/v1/auth/register")
    async def auth_register():
        return {"status": "ok"}

    @app.post("/api/v1/auth/login/local")
    async def auth_login():
        return {"status": "ok"}

    @app.get("/api/v1/auth/logout")
    async def auth_logout():
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    async def auth_me():
        return {
            "id": "default",
            "email": "demo@ci-agent.demo",
            "system_role": "admin",
            "needs_setup": False,
        }

    # ── Competition router ────────────────────────────────────────────
    from app.competition_router import router as competition_router

    app.include_router(competition_router)

    # ── Health ────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "competitive-analysis-agent"}

    return app


# ── Uvicorn entry point ─────────────────────────────────────────────────
app = create_app()
