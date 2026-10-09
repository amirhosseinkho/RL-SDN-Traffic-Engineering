"""WebSocket endpoint for real-time network metrics streaming."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.monitoring.collector import MetricsCollector

logger = logging.getLogger(__name__)
router = APIRouter()

_collector: MetricsCollector | None = None


def set_collector(collector: MetricsCollector) -> None:
    global _collector
    _collector = collector


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active_connections.append(ws)
        logger.info("WebSocket connected. Total: %d", len(self.active_connections))

    def disconnect(self, ws: WebSocket) -> None:
        self.active_connections = [c for c in self.active_connections if c is not ws]
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws/metrics")
async def metrics_websocket(ws: WebSocket) -> None:
    await manager.connect(ws)
    queue: asyncio.Queue | None = None

    if _collector:
        queue = _collector.subscribe()

    try:
        # Send current state immediately
        if _collector:
            summary = _collector.get_summary()
            await ws.send_json({"event": "connected", "data": summary})

        while True:
            if queue:
                try:
                    # Wait for new metrics with timeout
                    message = await asyncio.wait_for(queue.get(), timeout=5.0)
                    await ws.send_json(message)
                except asyncio.TimeoutError:
                    # Send heartbeat
                    await ws.send_json({"event": "heartbeat", "data": {}})
            else:
                # No collector; just heartbeat
                await asyncio.sleep(2.0)
                await ws.send_json({"event": "heartbeat", "data": {}})

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected cleanly")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        manager.disconnect(ws)
        if _collector and queue:
            _collector.unsubscribe(queue)


@router.websocket("/ws/training/{session_id}")
async def training_websocket(ws: WebSocket, session_id: str) -> None:
    """Stream training progress for a specific session."""
    await ws.accept()
    logger.info("Training WebSocket connected for session %s", session_id)

    try:
        # Poll the database for updates
        while True:
            from sqlalchemy import desc, select

            from app.database.models import TrainingEpisode, TrainingSession
            from app.database.session import async_session_factory

            async with async_session_factory() as db:
                session = await db.get(TrainingSession, session_id)
                if not session:
                    await ws.send_json({"event": "error", "data": {"message": "Session not found"}})
                    break

                ep_result = await db.execute(
                    select(TrainingEpisode)
                    .where(TrainingEpisode.session_id == session_id)
                    .order_by(desc(TrainingEpisode.timestamp))
                    .limit(1)
                )
                latest_ep = ep_result.scalar_one_or_none()

            payload = {
                "event": "training_update",
                "data": {
                    "session_id": session_id,
                    "status": session.status.value,
                    "current_timestep": session.current_timestep,
                    "total_timesteps": session.total_timesteps,
                    "progress_pct": round(
                        session.current_timestep / max(session.total_timesteps, 1) * 100, 2
                    ),
                    "best_reward": session.best_reward,
                    "latest_episode": {
                        "total_reward": latest_ep.total_reward if latest_ep else None,
                        "avg_latency_ms": latest_ep.avg_latency_ms if latest_ep else None,
                        "episode_number": latest_ep.episode_number if latest_ep else None,
                    } if latest_ep else None,
                },
            }
            await ws.send_json(payload)

            if session.status.value in ("completed", "failed", "paused"):
                break

            await asyncio.sleep(2.0)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Training WebSocket error: %s", e)
        try:
            await ws.send_json({"event": "error", "data": {"message": str(e)}})
        except Exception:
            pass
