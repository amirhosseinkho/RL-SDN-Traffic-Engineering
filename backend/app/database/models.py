"""SQLAlchemy ORM models for the RL-SDN platform."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class TopologyType(str, enum.Enum):
    LINEAR = "linear"
    TREE = "tree"
    FAT_TREE = "fat_tree"
    SPINE_LEAF = "spine_leaf"
    CUSTOM = "custom"


class AgentType(str, enum.Enum):
    DQN = "dqn"
    PPO = "ppo"
    SHORTEST_PATH = "shortest_path"
    ECMP = "ecmp"


class TrainingStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class Topology(Base):
    __tablename__ = "topologies"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    topology_type: Mapped[TopologyType] = mapped_column(Enum(TopologyType), nullable=False)
    num_switches: Mapped[int] = mapped_column(Integer, nullable=False)
    num_hosts: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    graph_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    flows: Mapped[list["Flow"]] = relationship("Flow", back_populates="topology")
    metrics: Mapped[list["LinkMetric"]] = relationship("LinkMetric", back_populates="topology")


class Switch(Base):
    __tablename__ = "switches"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    topology_id: Mapped[str] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    port: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("topology_id", "dpid"),)


class Link(Base):
    __tablename__ = "links"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    topology_id: Mapped[str] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    src_dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dst_dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    src_port: Mapped[int] = mapped_column(Integer, nullable=False)
    dst_port: Mapped[int] = mapped_column(Integer, nullable=False)
    bandwidth: Mapped[float] = mapped_column(Float, default=100.0)  # Mbps
    latency: Mapped[float] = mapped_column(Float, default=5.0)  # ms
    loss: Mapped[float] = mapped_column(Float, default=0.0)  # %
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    topology_id: Mapped[str] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    flow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    src_host: Mapped[str] = mapped_column(String(64), nullable=False)
    dst_host: Mapped[str] = mapped_column(String(64), nullable=False)
    src_ip: Mapped[Optional[str]] = mapped_column(String(45))
    dst_ip: Mapped[Optional[str]] = mapped_column(String(45))
    protocol: Mapped[Optional[str]] = mapped_column(String(16))
    bandwidth_mbps: Mapped[float] = mapped_column(Float, default=0.0)
    path: Mapped[Optional[list]] = mapped_column(JSON)
    is_elephant: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    topology: Mapped["Topology"] = relationship("Topology", back_populates="flows")


class LinkMetric(Base):
    __tablename__ = "link_metrics"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    topology_id: Mapped[str] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    src_dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dst_dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    utilization: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1
    throughput_mbps: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    packet_loss: Mapped[float] = mapped_column(Float, default=0.0)
    queue_occupancy: Mapped[float] = mapped_column(Float, default=0.0)
    dropped_packets: Mapped[int] = mapped_column(BigInteger, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    topology: Mapped["Topology"] = relationship("Topology", back_populates="metrics")


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    agent_type: Mapped[AgentType] = mapped_column(Enum(AgentType), nullable=False)
    status: Mapped[TrainingStatus] = mapped_column(Enum(TrainingStatus), default=TrainingStatus.PENDING)
    topology_id: Mapped[Optional[str]] = mapped_column(ForeignKey("topologies.id"))
    hyperparameters: Mapped[dict] = mapped_column(JSON, default=dict)
    total_timesteps: Mapped[int] = mapped_column(Integer, default=0)
    current_timestep: Mapped[int] = mapped_column(Integer, default=0)
    best_reward: Mapped[float] = mapped_column(Float, default=float("-inf"))
    model_path: Mapped[Optional[str]] = mapped_column(String(512))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episodes: Mapped[list["TrainingEpisode"]] = relationship("TrainingEpisode", back_populates="session")


class TrainingEpisode(Base):
    __tablename__ = "training_episodes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("training_sessions.id"), nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    total_reward: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    avg_throughput_mbps: Mapped[float] = mapped_column(Float, default=0.0)
    avg_packet_loss: Mapped[float] = mapped_column(Float, default=0.0)
    avg_link_utilization: Mapped[float] = mapped_column(Float, default=0.0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    epsilon: Mapped[Optional[float]] = mapped_column(Float)
    policy_loss: Mapped[Optional[float]] = mapped_column(Float)
    value_loss: Mapped[Optional[float]] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["TrainingSession"] = relationship("TrainingSession", back_populates="episodes")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    agent_type: Mapped[AgentType] = mapped_column(Enum(AgentType), nullable=False)
    topology_id: Mapped[str] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("training_sessions.id"))
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    avg_throughput_mbps: Mapped[float] = mapped_column(Float, default=0.0)
    avg_packet_loss: Mapped[float] = mapped_column(Float, default=0.0)
    avg_link_utilization: Mapped[float] = mapped_column(Float, default=0.0)
    convergence_time_s: Mapped[Optional[float]] = mapped_column(Float)
    num_episodes: Mapped[int] = mapped_column(Integer, default=0)
    raw_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CopilotQuery(Base):
    __tablename__ = "copilot_queries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[Optional[str]] = mapped_column(Text)
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    model_used: Mapped[str] = mapped_column(String(64), default="llama3.2")
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
