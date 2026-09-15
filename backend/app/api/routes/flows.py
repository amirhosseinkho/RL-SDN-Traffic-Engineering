"""Flow management API endpoints."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.controller.ryu_controller import RyuControllerClient, TopologyManager, FlowManager
from app.database.models import Flow, Topology
from app.database.schemas import FlowInstallRequest, FlowResponse
from app.database.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/flows", tags=["flows"])


@router.get("/", response_model=list[FlowResponse])
async def list_flows(
    topology_id: str | None = None,
    active_only: bool = True,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> list[Flow]:
    query = select(Flow)
    if topology_id:
        query = query.where(Flow.topology_id == topology_id)
    if active_only:
        query = query.where(Flow.is_active == True)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/ryu")
async def get_ryu_flows() -> dict:
    """Get live flow tables from Ryu controller."""
    async with RyuControllerClient() as ryu:
        flows = await ryu.get_flows()
    return {"flows": flows}


@router.post("/install", response_model=FlowResponse, status_code=status.HTTP_201_CREATED)
async def install_flow(
    request: FlowInstallRequest,
    topology_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Flow:
    topo = await db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    flow = Flow(
        topology_id=topology_id,
        flow_id=f"flow_{request.src_host}_{request.dst_host}",
        src_host=request.src_host,
        dst_host=request.dst_host,
        protocol=request.protocol,
        bandwidth_mbps=request.bandwidth_mbps,
        is_active=True,
    )
    db.add(flow)
    await db.commit()
    await db.refresh(flow)
    return flow


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_flow(
    flow_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    flow = await db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    flow.is_active = False
    await db.commit()


@router.get("/stats/summary")
async def flow_stats_summary(
    topology_id: str | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> dict:
    query = select(Flow).where(Flow.is_active == True)
    if topology_id:
        query = query.where(Flow.topology_id == topology_id)
    result = await db.execute(query)
    flows = list(result.scalars().all())

    elephant = [f for f in flows if f.is_elephant]
    total_bw = sum(f.bandwidth_mbps for f in flows)

    return {
        "total_active_flows": len(flows),
        "elephant_flows": len(elephant),
        "mice_flows": len(flows) - len(elephant),
        "total_bandwidth_mbps": round(total_bw, 2),
        "avg_bandwidth_mbps": round(total_bw / len(flows), 2) if flows else 0.0,
    }
