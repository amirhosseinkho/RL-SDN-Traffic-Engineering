"""Topology API endpoints."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import metrics as metrics_route
from app.database.models import Topology
from app.database.schemas import (
    EdgeResponse,
    NodeResponse,
    TopologyConfig,
    TopologyGraphResponse,
    TopologyResponse,
)
from app.database.session import get_db
from app.topology.generator import TopologyGenerator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/topology", tags=["topology"])
generator = TopologyGenerator()


@router.post("/", response_model=TopologyResponse, status_code=status.HTTP_201_CREATED)
async def create_topology(
    config: TopologyConfig,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Topology:
    """Generate and persist a new network topology."""
    try:
        topo_def = generator.generate(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    topo = Topology(
        name=config.name,
        topology_type=config.topology_type,
        num_switches=len(topo_def.switches),
        num_hosts=len(topo_def.hosts),
        config=topo_def.config,
        graph_data=topo_def.to_graph_data(),
    )
    db.add(topo)
    await db.commit()
    await db.refresh(topo)
    logger.info("Created topology %s (%s)", topo.id, topo.topology_type)
    return topo


@router.get("/", response_model=list[TopologyResponse])
async def list_topologies(db: Annotated[AsyncSession, Depends(get_db)]) -> list[Topology]:
    result = await db.execute(select(Topology).order_by(Topology.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{topology_id}", response_model=TopologyResponse)
async def get_topology(
    topology_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Topology:
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")
    return topo


@router.get("/{topology_id}/graph", response_model=TopologyGraphResponse)
async def get_topology_graph(
    topology_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TopologyGraphResponse:
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    graph_data = topo.graph_data or {"nodes": [], "edges": []}
    nodes = [NodeResponse(**n) for n in graph_data.get("nodes", [])]
    edges = [EdgeResponse(**e) for e in graph_data.get("edges", [])]
    return TopologyGraphResponse(topology_id=topology_id, nodes=nodes, edges=edges)


@router.post("/{topology_id}/activate", response_model=TopologyResponse)
async def activate_topology(
    topology_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Topology:
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    # Deactivate all others
    await db.execute(update(Topology).values(is_active=False))
    topo.is_active = True
    await db.commit()
    await db.refresh(topo)

    if metrics_route._collector is not None:
        metrics_route._collector.use_topology(generator.generate(TopologyConfig(**topo.config)))
    return topo


@router.delete("/{topology_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_topology(
    topology_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")
    await db.delete(topo)
    await db.commit()
