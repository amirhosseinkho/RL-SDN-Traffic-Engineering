"""AI Network Copilot endpoint - answers natural language questions about the network."""
from __future__ import annotations

import logging
import time
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import CopilotQuery
from app.database.schemas import CopilotQueryRequest, CopilotQueryResponse
from app.database.session import get_db
from app.monitoring.collector import MetricsCollector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot", tags=["copilot"])
settings = get_settings()

_collector: MetricsCollector | None = None


def set_collector(collector: MetricsCollector) -> None:
    global _collector
    _collector = collector


def _build_system_prompt(context: dict) -> str:
    return f"""You are an expert SDN (Software Defined Networking) network analyst with deep knowledge of:
- OpenFlow protocol and Ryu controller
- Reinforcement learning for network optimization
- Traffic engineering and congestion control
- Network performance metrics

Current network state:
- Average link utilization: {context.get('avg_utilization', 'unknown')}
- Max link utilization: {context.get('max_utilization', 'unknown')}
- Average latency: {context.get('avg_latency_ms', 'unknown')} ms
- Average packet loss: {context.get('avg_packet_loss', 'unknown')}%
- Congested links: {context.get('congested_links', 0)} / {context.get('total_links', 0)}
- Total throughput: {context.get('total_throughput_mbps', 'unknown')} Mbps

Answer questions about the network state clearly and concisely. If the RL agent has made routing decisions,
explain why it chose those paths based on the current metrics. Be specific and technical but also clear."""


async def _query_ollama(prompt: str, system: str, model: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "No response generated.")
    except httpx.ConnectError:
        return _fallback_response(prompt)
    except Exception as e:
        logger.error("Ollama query failed: %s", e)
        return _fallback_response(prompt)


def _fallback_response(query: str) -> str:
    """Rule-based fallback when Ollama is unavailable."""
    q = query.lower()

    if "latency" in q and ("increas" in q or "high" in q or "why" in q):
        return (
            "Latency is typically caused by: (1) Queue buildup at congested links - when utilization "
            "exceeds ~80%, packets queue up adding delay; (2) Long routing paths - the RL agent may "
            "be routing through more hops; (3) Network congestion causing retransmissions. "
            "Check the congestion heatmap for links above 80% utilization."
        )
    elif "congest" in q:
        return (
            "Link congestion occurs when traffic demand exceeds link capacity. "
            "The RL agent detects congestion via high utilization (>80%) and reroutes flows "
            "to alternative paths with available capacity. Check the metrics dashboard for "
            "congested links highlighted in red/orange."
        )
    elif "reroute" in q or "re-route" in q:
        return (
            "The RL agent reroutes traffic when: (1) Current path utilization exceeds the "
            "congestion threshold (80%); (2) Alternative paths with lower latency are available; "
            "(3) The reward function indicates better options exist. The agent uses its learned "
            "policy to balance load across multiple paths."
        )
    elif "rl" in q or "agent" in q or "reinforcement" in q:
        return (
            "The RL agent uses a Deep Q-Network (DQN) or Proximal Policy Optimization (PPO) "
            "to learn optimal routing policies. It observes link utilization, latency, and packet "
            "loss, then selects paths that maximize throughput while minimizing congestion and delay. "
            "Training improves performance over time compared to static shortest-path routing."
        )
    elif "throughput" in q:
        return (
            "Throughput is the actual data rate delivered across the network. The RL agent "
            "optimizes routing to maximize total network throughput by avoiding congested links "
            "and distributing load. ECMP and RL-based routing typically achieve 15-30% better "
            "throughput than shortest-path routing under heavy load."
        )
    else:
        return (
            "I can help you understand network performance, congestion patterns, RL agent "
            "decisions, and routing policies. Try asking about: latency trends, congested links, "
            "why traffic was rerouted, RL agent behavior, or current network state."
        )


@router.post("/query", response_model=CopilotQueryResponse)
async def query_copilot(
    request: CopilotQueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CopilotQueryResponse:
    """Ask the AI copilot a question about the network."""
    context: dict = {}
    if request.include_context and _collector:
        context = _collector.get_summary()

    system_prompt = _build_system_prompt(context)
    start = time.time()

    if settings.copilot_enabled:
        response_text = await _query_ollama(request.query, system_prompt, settings.ollama_model)
    else:
        response_text = _fallback_response(request.query)

    latency_ms = (time.time() - start) * 1000

    # Persist query
    record = CopilotQuery(
        query=request.query,
        response=response_text,
        context_snapshot=context,
        model_used=settings.ollama_model if settings.copilot_enabled else "rule-based",
        latency_ms=latency_ms,
    )
    db.add(record)
    await db.commit()

    return CopilotQueryResponse(
        query=request.query,
        response=response_text,
        context_used=bool(context),
        model_used=settings.ollama_model if settings.copilot_enabled else "rule-based",
        latency_ms=round(latency_ms, 2),
    )


@router.get("/history")
async def get_query_history(
    limit: int = 20,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> list[dict]:
    from sqlalchemy import desc, select
    result = await db.execute(
        select(CopilotQuery).order_by(desc(CopilotQuery.created_at)).limit(limit)
    )
    rows = list(result.scalars().all())
    return [
        {
            "id": str(r.id),
            "query": r.query,
            "response": r.response,
            "model_used": r.model_used,
            "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
