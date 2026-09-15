"""Realistic traffic pattern generator for SDN simulation."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class TrafficPattern(str, Enum):
    ELEPHANT = "elephant"       # Large long-lived flows (>10 MB)
    MICE = "mice"               # Small short-lived flows (<1 MB)
    BURSTY = "bursty"           # Periodic bursts
    UNIFORM = "uniform"         # Uniformly distributed
    DIURNAL = "diurnal"         # Day-night pattern
    GRAVITY = "gravity"         # Proportional to node degree


@dataclass
class TrafficFlow:
    flow_id: str
    src_host: str
    dst_host: str
    pattern: TrafficPattern
    demand_mbps: float
    duration_s: float
    start_time: float
    is_active: bool = True
    bytes_sent: int = 0

    @property
    def is_elephant(self) -> bool:
        return self.demand_mbps > 50.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "src_host": self.src_host,
            "dst_host": self.dst_host,
            "pattern": self.pattern.value,
            "demand_mbps": round(self.demand_mbps, 2),
            "duration_s": round(self.duration_s, 1),
            "is_elephant": self.is_elephant,
            "is_active": self.is_active,
            "bytes_sent": self.bytes_sent,
        }


class TrafficMatrix:
    """Represents a traffic demand matrix between all host pairs."""

    def __init__(self, hosts: list[str]) -> None:
        self.hosts = hosts
        self.matrix: dict[tuple[str, str], float] = {}

    def set_demand(self, src: str, dst: str, demand_mbps: float) -> None:
        if src != dst:
            self.matrix[(src, dst)] = max(0.0, demand_mbps)

    def get_demand(self, src: str, dst: str) -> float:
        return self.matrix.get((src, dst), 0.0)

    def total_demand(self) -> float:
        return sum(self.matrix.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "hosts": self.hosts,
            "matrix": {f"{k[0]}->{k[1]}": v for k, v in self.matrix.items()},
            "total_demand_mbps": self.total_demand(),
        }


class TrafficGenerator:
    """
    Generates realistic traffic patterns for SDN simulation.

    Supports Elephant/Mice flows, bursty traffic, and gravity models.
    """

    def __init__(
        self,
        hosts: list[str],
        link_capacity_mbps: float = 100.0,
        rng_seed: int = 42,
    ) -> None:
        self.hosts = hosts
        self.link_capacity = link_capacity_mbps
        self._rng = np.random.default_rng(rng_seed)
        self._flows: dict[str, TrafficFlow] = {}
        self._flow_counter = 0
        self._running = False

    def _new_flow_id(self) -> str:
        self._flow_counter += 1
        return f"flow_{self._flow_counter:06d}"

    def generate_traffic_matrix(
        self,
        pattern: TrafficPattern = TrafficPattern.UNIFORM,
        load_factor: float = 0.6,
    ) -> TrafficMatrix:
        tm = TrafficMatrix(self.hosts)
        n = len(self.hosts)
        if n < 2:
            return tm

        total_capacity = self.link_capacity * load_factor

        if pattern == TrafficPattern.UNIFORM:
            per_pair = total_capacity / (n * (n - 1))
            for i, src in enumerate(self.hosts):
                for dst in self.hosts:
                    if src != dst:
                        tm.set_demand(src, dst, per_pair * float(self._rng.uniform(0.5, 1.5)))

        elif pattern == TrafficPattern.ELEPHANT:
            # 80% of traffic from 20% of flows
            num_elephants = max(1, n // 5)
            elephant_bw = total_capacity * 0.8 / num_elephants
            pairs = [(h1, h2) for h1 in self.hosts for h2 in self.hosts if h1 != h2]
            elephant_pairs = self._rng.choice(len(pairs), size=num_elephants, replace=False)
            for idx in elephant_pairs:
                src, dst = pairs[idx]
                tm.set_demand(src, dst, float(elephant_bw * self._rng.uniform(0.8, 1.2)))
            # Fill remaining with mice
            for src in self.hosts:
                for dst in self.hosts:
                    if src != dst and tm.get_demand(src, dst) == 0:
                        tm.set_demand(src, dst, float(self._rng.uniform(0.5, 5.0)))

        elif pattern == TrafficPattern.BURSTY:
            base_bw = total_capacity * 0.3 / max(n * (n - 1), 1)
            for src in self.hosts:
                for dst in self.hosts:
                    if src != dst:
                        # Add periodic burst
                        burst = float(self._rng.exponential(total_capacity * 0.1)) if self._rng.random() < 0.3 else 0.0
                        tm.set_demand(src, dst, base_bw + burst)

        elif pattern == TrafficPattern.GRAVITY:
            # Demand proportional to product of node "mass" (random capacity)
            masses = {h: float(self._rng.uniform(1, 10)) for h in self.hosts}
            total_mass_product = sum(
                masses[src] * masses[dst]
                for src in self.hosts
                for dst in self.hosts
                if src != dst
            )
            for src in self.hosts:
                for dst in self.hosts:
                    if src != dst:
                        demand = total_capacity * masses[src] * masses[dst] / max(total_mass_product, 1)
                        tm.set_demand(src, dst, demand)

        elif pattern == TrafficPattern.DIURNAL:
            # Simulate peak hour (high load)
            phase = float(self._rng.uniform(0, 2 * 3.14159))
            peak_factor = 0.5 + 0.5 * abs(np.sin(phase))
            per_pair = total_capacity * peak_factor / max(n * (n - 1), 1)
            for src in self.hosts:
                for dst in self.hosts:
                    if src != dst:
                        tm.set_demand(src, dst, per_pair * float(self._rng.uniform(0.7, 1.3)))

        else:  # MICE
            for src in self.hosts:
                for dst in self.hosts:
                    if src != dst:
                        tm.set_demand(src, dst, float(self._rng.uniform(0.1, 5.0)))

        return tm

    def generate_flows(
        self,
        pattern: TrafficPattern = TrafficPattern.UNIFORM,
        num_flows: int | None = None,
        load_factor: float = 0.6,
    ) -> list[TrafficFlow]:
        n = len(self.hosts)
        if n < 2:
            return []

        pairs = [(h1, h2) for h1 in self.hosts for h2 in self.hosts if h1 != h2]
        num_flows = num_flows or min(len(pairs), max(4, n * 2))
        selected_pairs = [
            pairs[i] for i in self._rng.choice(len(pairs), size=num_flows, replace=False)
        ]

        flows: list[TrafficFlow] = []
        now = time.time()

        for src, dst in selected_pairs:
            if pattern in (TrafficPattern.ELEPHANT, TrafficPattern.UNIFORM):
                is_elephant = self._rng.random() < 0.2 if pattern == TrafficPattern.UNIFORM else True
                demand = float(
                    self._rng.uniform(50, 200) if is_elephant else self._rng.uniform(1, 20)
                )
                duration = float(self._rng.uniform(60, 300) if is_elephant else self._rng.uniform(5, 60))

            elif pattern == TrafficPattern.MICE:
                demand = float(self._rng.uniform(0.1, 5.0))
                duration = float(self._rng.exponential(10))

            elif pattern == TrafficPattern.BURSTY:
                demand = float(
                    self._rng.uniform(10, 100) if self._rng.random() < 0.3 else self._rng.uniform(0.1, 5)
                )
                duration = float(self._rng.uniform(1, 30))

            else:
                demand = float(self._rng.uniform(1, 50) * load_factor)
                duration = float(self._rng.uniform(10, 120))

            flow = TrafficFlow(
                flow_id=self._new_flow_id(),
                src_host=src,
                dst_host=dst,
                pattern=pattern,
                demand_mbps=demand,
                duration_s=duration,
                start_time=now,
            )
            flows.append(flow)
            self._flows[flow.flow_id] = flow

        return flows

    def update_flows(self, dt: float = 1.0) -> list[TrafficFlow]:
        """Update flow states over time (called each simulation tick)."""
        now = time.time()
        for flow in list(self._flows.values()):
            elapsed = now - flow.start_time
            if elapsed > flow.duration_s:
                flow.is_active = False
            else:
                # Add some demand variation
                delta = float(self._rng.normal(0, flow.demand_mbps * 0.02))
                flow.demand_mbps = max(0.01, flow.demand_mbps + delta)
                flow.bytes_sent += int(flow.demand_mbps * 1e6 / 8 * dt)

        return [f for f in self._flows.values() if f.is_active]

    @property
    def active_flows(self) -> list[TrafficFlow]:
        return [f for f in self._flows.values() if f.is_active]

    @property
    def elephant_flows(self) -> list[TrafficFlow]:
        return [f for f in self.active_flows if f.is_elephant]

    @property
    def mice_flows(self) -> list[TrafficFlow]:
        return [f for f in self.active_flows if not f.is_elephant]
