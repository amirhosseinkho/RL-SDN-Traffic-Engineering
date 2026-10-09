"""Report generation API endpoints (PDF, CSV, JSON)."""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    EvaluationResult,
    Topology,
    TrainingEpisode,
    TrainingSession,
)
from app.database.schemas import ReportRequest
from app.database.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


async def _build_report_data(
    request: ReportRequest,
    db: AsyncSession,
) -> dict:
    topo = await db.get(Topology, request.topology_id)
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found")

    # Evaluation results
    eval_result = await db.execute(
        select(EvaluationResult)
        .where(EvaluationResult.topology_id == request.topology_id)
        .order_by(desc(EvaluationResult.created_at))
    )
    eval_rows = list(eval_result.scalars().all())

    # Training sessions
    sessions_data = []
    for sid in request.session_ids:
        sess = await db.get(TrainingSession, sid)
        if sess:
            ep_result = await db.execute(
                select(TrainingEpisode)
                .where(TrainingEpisode.session_id == sid)
                .order_by(TrainingEpisode.episode_number)
            )
            episodes = list(ep_result.scalars().all())
            sessions_data.append(
                {
                    "session": {
                        "id": str(sess.id),
                        "agent_type": sess.agent_type.value,
                        "status": sess.status.value,
                        "total_timesteps": sess.total_timesteps,
                        "current_timestep": sess.current_timestep,
                        "best_reward": sess.best_reward,
                        "started_at": sess.started_at.isoformat() if sess.started_at else None,
                        "completed_at": sess.completed_at.isoformat() if sess.completed_at else None,
                    },
                    "num_episodes": len(episodes),
                    "final_avg_reward": sum(e.total_reward for e in episodes[-10:]) / 10 if episodes else 0.0,
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topology": {
            "id": str(topo.id),
            "name": topo.name,
            "type": topo.topology_type.value,
            "num_switches": topo.num_switches,
            "num_hosts": topo.num_hosts,
        },
        "evaluation_results": [
            {
                "agent_type": r.agent_type.value,
                "avg_latency_ms": r.avg_latency_ms,
                "avg_throughput_mbps": r.avg_throughput_mbps,
                "avg_packet_loss": r.avg_packet_loss,
                "avg_link_utilization": r.avg_link_utilization,
                "convergence_time_s": r.convergence_time_s,
                "num_episodes": r.num_episodes,
                "created_at": r.created_at.isoformat(),
            }
            for r in eval_rows
        ],
        "training_sessions": sessions_data,
    }


@router.post("/generate", response_model=None)
async def generate_report(
    request: ReportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse | Response:
    data = await _build_report_data(request, db)

    if request.format == "json":
        content = json.dumps(data, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=sdn_report_{request.topology_id[:8]}.json"},
        )

    elif request.format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(["RL-SDN Traffic Engineering Report"])
        writer.writerow(["Generated At", data["generated_at"]])
        writer.writerow([])

        # Topology
        writer.writerow(["Topology Summary"])
        for k, v in data["topology"].items():
            writer.writerow([k, v])
        writer.writerow([])

        # Evaluation
        writer.writerow(["Evaluation Results"])
        writer.writerow([
            "Agent", "Avg Latency (ms)", "Avg Throughput (Mbps)",
            "Packet Loss", "Utilization", "Convergence (s)", "Episodes",
        ])
        for r in data["evaluation_results"]:
            writer.writerow([
                r["agent_type"],
                round(r["avg_latency_ms"], 2),
                round(r["avg_throughput_mbps"], 2),
                round(r["avg_packet_loss"], 4),
                round(r["avg_link_utilization"], 4),
                r["convergence_time_s"],
                r["num_episodes"],
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sdn_report_{request.topology_id[:8]}.csv"},
        )

    elif request.format == "pdf":
        # Generate a simple PDF using reportlab if available, otherwise return JSON
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

            buf = io.BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            story.append(Paragraph("RL-SDN Traffic Engineering Report", styles["Title"]))
            story.append(Paragraph(f"Generated: {data['generated_at']}", styles["Normal"]))
            story.append(Spacer(1, 12))

            # Topology section
            story.append(Paragraph("Topology Summary", styles["Heading2"]))
            topo = data["topology"]
            topo_table_data = [
                ["Property", "Value"],
                ["Name", topo["name"]],
                ["Type", topo["type"]],
                ["Switches", str(topo["num_switches"])],
                ["Hosts", str(topo["num_hosts"])],
            ]
            topo_table = Table(topo_table_data)
            story.append(topo_table)
            story.append(Spacer(1, 12))

            # Evaluation section
            if data["evaluation_results"]:
                story.append(Paragraph("Evaluation Results", styles["Heading2"]))
                eval_data = [["Agent", "Latency (ms)", "Throughput (Mbps)", "Packet Loss %"]]
                for r in data["evaluation_results"]:
                    eval_data.append([
                        r["agent_type"],
                        f"{r['avg_latency_ms']:.2f}",
                        f"{r['avg_throughput_mbps']:.2f}",
                        f"{r['avg_packet_loss']:.4f}",
                    ])
                eval_table = Table(eval_data)
                story.append(eval_table)

            doc.build(story)
            buf.seek(0)

            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=sdn_report_{request.topology_id[:8]}.pdf"},
            )
        except ImportError:
            # Fall back to JSON if reportlab not installed
            content = json.dumps(data, indent=2)
            return Response(
                content=content,
                media_type="application/json",
                headers={
                    "Content-Disposition": f"attachment; filename=sdn_report_{request.topology_id[:8]}.json",
                    "X-Warning": "PDF generation unavailable; returning JSON",
                },
            )

    raise HTTPException(status_code=400, detail=f"Unsupported format: {request.format}")
