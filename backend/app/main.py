"""FastAPI application entry point for the RL-SDN Traffic Engineering platform."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.database.session import create_tables
from app.monitoring.collector import MetricsCollector

settings = get_settings()

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ─── Shared application state ────────────────────────────────────────────────

_collector: MetricsCollector | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _collector

    logger.info("Starting RL-SDN Traffic Engineering API v%s", settings.app_version)

    # Initialize database
    try:
        await create_tables()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)

    # Start metrics collector (sim-only mode on startup)
    _collector = MetricsCollector()
    await _collector.start()

    # Wire collector into routes
    from app.api.routes import metrics as metrics_route
    from app.api.routes import copilot as copilot_route
    from app.api import websocket as ws_module

    metrics_route.set_collector(_collector)
    copilot_route.set_collector(_collector)
    ws_module.set_collector(_collector)

    logger.info("RL-SDN API ready on %s:%d", settings.api_host, settings.api_port)
    yield

    # Shutdown
    logger.info("Shutting down...")
    await _collector.stop()


# ─── Application ─────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered Software Defined Networking platform using Reinforcement Learning "
            "for optimal traffic engineering and routing decisions."
        ),
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Routers ──────────────────────────────────────────────────────────────
    from app.api.routes.topology import router as topology_router
    from app.api.routes.metrics import router as metrics_router
    from app.api.routes.flows import router as flows_router
    from app.api.routes.rl import router as rl_router
    from app.api.routes.reports import router as reports_router
    from app.api.routes.copilot import router as copilot_router
    from app.api.websocket import router as ws_router

    prefix = settings.api_prefix
    app.include_router(topology_router, prefix=prefix)
    app.include_router(metrics_router, prefix=prefix)
    app.include_router(flows_router, prefix=prefix)
    app.include_router(rl_router, prefix=prefix)
    app.include_router(reports_router, prefix=prefix)
    app.include_router(copilot_router, prefix=prefix)
    app.include_router(ws_router)  # WebSocket routes at root

    # ── Health endpoint ───────────────────────────────────────────────────────
    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {
            "status": "healthy",
            "version": settings.app_version,
            "collector_running": _collector is not None and _collector._running,
        }

    @app.get("/", tags=["health"])
    async def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": f"{settings.api_prefix}/docs",
        }

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
