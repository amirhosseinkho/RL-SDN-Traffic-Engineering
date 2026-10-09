"""Metrics and monitoring API endpoints."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LinkMetric, Topology
from app.database.schemas import LinkMetricResponse
from app.database.session import get_db
from app.monitoring.collector import MetricsCollector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metrics", tags=["metrics"])

# Collector injected at startup
_collector: MetricsCollector | None = None


def set_collector(collector: MetricsCollector) -> None:
    global _collector
    _collector = collector


def get_collector() -> MetricsCollector:
    if _collector is None:
        raise HTTPException(status_code=503, detail="Metrics collector not initialized")
    return _collector


@router.get("/summary")
async def get_metrics_summary() -> dict:
    """Get a summary of current network metrics."""
    collector = get_collector()
    return collector.get_summary()


@router.get("/links")
async def get_link_metrics() -> list[dict]:
    """Get current per-link metrics."""
    collector = get_collector()
    snapshots = collector.get_latest_snapshot()
    return [s.to_dict() for s in snapshots]


@router.get("/{topology_id}/history", response_model=list[LinkMetricResponse])
async def get_metrics_history(
    topology_id: str,
    limit: int = Query(default=100, le=1000),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> list[LinkMetric]:
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    result = await db.execute(
        select(LinkMetric)
        .where(LinkMetric.topology_id == topology_id)
        .order_by(desc(LinkMetric.timestamp))
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{topology_id}/congestion")
async def get_congestion_map(
    topology_id: str,
    threshold: float = Query(default=0.8, ge=0.0, le=1.0),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> dict:
    """Return a congestion heatmap for the topology."""
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    collector = get_collector()
    snapshots = collector.get_latest_snapshot()

    congested = [
        {
            "src_dpid": s.src_dpid,
            "dst_dpid": s.dst_dpid,
            "utilization": s.utilization,
            "severity": "high" if s.utilization > 0.9 else "medium",
        }
        for s in snapshots
        if s.utilization > threshold
    ]

    return {
        "topology_id": topology_id,
        "threshold": threshold,
        "congested_links": congested,
        "total_congested": len(congested),
        "total_links": len(snapshots),
    }
