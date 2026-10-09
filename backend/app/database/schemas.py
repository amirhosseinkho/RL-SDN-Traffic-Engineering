"""Pydantic schemas for API request/response serialization."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.database.models import AgentType, TopologyType, TrainingStatus

# ─── Base ────────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── Topology ────────────────────────────────────────────────────────────────

class TopologyConfig(BaseModel):
    topology_type: TopologyType = TopologyType.LINEAR
    num_switches: int = Field(default=4, ge=2, le=64)
    num_hosts: int = Field(default=8, ge=2, le=256)
    bandwidth: float = Field(default=100.0, gt=0)  # Mbps
    latency: float = Field(default=5.0, ge=0)  # ms
    loss: float = Field(default=0.0, ge=0, le=100)  # %
    # Fat-tree specific
    k: Optional[int] = Field(default=4, ge=2)
    # Tree specific
    depth: Optional[int] = Field(default=2, ge=1)
    fanout: Optional[int] = Field(default=2, ge=2)
    # Spine-leaf specific
    num_spine: Optional[int] = Field(default=2, ge=1)
    num_leaf: Optional[int] = Field(default=4, ge=2)
    # Custom topology JSON
    custom_data: Optional[dict[str, Any]] = None
    name: str = "my-topology"


class TopologyResponse(OrmBase):
    id: str
    name: str
    topology_type: TopologyType
    num_switches: int
    num_hosts: int
    config: dict[str, Any]
    graph_data: Optional[dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NodeResponse(BaseModel):
    id: str
    label: str
    node_type: str  # "switch" | "host"
    dpid: Optional[int] = None
    ip: Optional[str] = None
    position: Optional[dict[str, float]] = None


class EdgeResponse(BaseModel):
    id: str
    source: str
    target: str
    bandwidth: float
    latency: float
    loss: float
    utilization: float = 0.0


class TopologyGraphResponse(BaseModel):
    topology_id: str
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]


# ─── Metrics ─────────────────────────────────────────────────────────────────

class LinkMetricResponse(OrmBase):
    id: str
    topology_id: str
    src_dpid: int
    dst_dpid: int
    utilization: float
    throughput_mbps: float
    latency_ms: float
    packet_loss: float
    queue_occupancy: float
    dropped_packets: int
    timestamp: datetime


class NetworkMetricsSummary(BaseModel):
    topology_id: str
    timestamp: datetime
    avg_utilization: float
    max_utilization: float
    avg_latency_ms: float
    avg_throughput_mbps: float
    total_throughput_mbps: float
    avg_packet_loss: float
    congested_links: int
    total_links: int
    link_metrics: list[LinkMetricResponse]


# ─── Flows ───────────────────────────────────────────────────────────────────

class FlowResponse(OrmBase):
    id: str
    topology_id: str
    flow_id: str
    src_host: str
    dst_host: str
    src_ip: Optional[str]
    dst_ip: Optional[str]
    protocol: Optional[str]
    bandwidth_mbps: float
    path: Optional[list[Any]]
    is_elephant: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FlowInstallRequest(BaseModel):
    src_host: str
    dst_host: str
    bandwidth_mbps: float = 10.0
    priority: int = 1
    protocol: str = "tcp"


# ─── RL Training ─────────────────────────────────────────────────────────────

class TrainingRequest(BaseModel):
    agent_type: AgentType
    topology_id: str
    total_timesteps: int = Field(default=500_000, ge=1_000)
    hyperparameters: dict[str, Any] = Field(default_factory=dict)


class TrainingSessionResponse(OrmBase):
    id: str
    agent_type: AgentType
    status: TrainingStatus
    topology_id: Optional[str]
    hyperparameters: dict[str, Any]
    total_timesteps: int
    current_timestep: int
    best_reward: float
    model_path: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class TrainingEpisodeResponse(OrmBase):
    id: str
    session_id: str
    episode_number: int
    total_reward: float
    avg_latency_ms: float
    avg_throughput_mbps: float
    avg_packet_loss: float
    avg_link_utilization: float
    steps: int
    epsilon: Optional[float]
    policy_loss: Optional[float]
    value_loss: Optional[float]
    timestamp: datetime


class TrainingProgressResponse(BaseModel):
    session: TrainingSessionResponse
    recent_episodes: list[TrainingEpisodeResponse]
    progress_pct: float


# ─── Evaluation ──────────────────────────────────────────────────────────────

class EvaluationRequest(BaseModel):
    topology_id: str
    agents: list[AgentType] = Field(default_factory=lambda: list(AgentType))
    num_episodes: int = Field(default=10, ge=1, le=100)


class EvaluationResultResponse(OrmBase):
    id: str
    agent_type: AgentType
    topology_id: str
    session_id: Optional[str]
    avg_latency_ms: float
    avg_throughput_mbps: float
    avg_packet_loss: float
    avg_link_utilization: float
    convergence_time_s: Optional[float]
    num_episodes: int
    raw_metrics: dict[str, Any]
    created_at: datetime


class ComparisonResponse(BaseModel):
    topology_id: str
    results: list[EvaluationResultResponse]
    best_agent: AgentType
    improvement_over_shortest_path: dict[str, float]


# ─── Copilot ─────────────────────────────────────────────────────────────────

class CopilotQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    include_context: bool = True


class CopilotQueryResponse(BaseModel):
    query: str
    response: str
    context_used: bool
    model_used: str
    latency_ms: float


# ─── WebSocket ───────────────────────────────────────────────────────────────

class WSMessage(BaseModel):
    event: str
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── Report ──────────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    topology_id: str
    session_ids: list[str] = Field(default_factory=list)
    include_raw_metrics: bool = False
    format: str = Field(default="json", pattern="^(json|csv|pdf)$")
