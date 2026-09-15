"""Real-time metrics collection from Ryu controller and simulated environment."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.controller.ryu_controller import RyuControllerClient
from app.rl.environment import SDNRoutingEnv, SimState

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class LinkSnapshot:
    src_dpid: int
    dst_dpid: int
    utilization: float = 0.0
    throughput_mbps: float = 0.0
    latency_ms: float = 0.0
    packet_loss: float = 0.0
    queue_occupancy: float = 0.0
    dropped_packets: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "src_dpid": self.src_dpid,
            "dst_dpid": self.dst_dpid,
            "utilization": round(self.utilization, 4),
            "throughput_mbps": round(self.throughput_mbps, 2),
            "latency_ms": round(self.latency_ms, 2),
            "packet_loss": round(self.packet_loss, 4),
            "queue_occupancy": round(self.queue_occupancy, 4),
            "dropped_packets": self.dropped_packets,
            "timestamp": self.timestamp.isoformat(),
        }


class MetricsCollector:
    """
    Collects network metrics from either the Ryu REST API (real network)
    or the simulated environment (when Ryu is unavailable).
    """

    def __init__(
        self,
        env: SDNRoutingEnv | None = None,
        history_size: int = 1000,
    ) -> None:
        self.env = env
        self.history: deque[list[LinkSnapshot]] = deque(maxlen=history_size)
        self._running = False
        self._task: asyncio.Task | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._prev_port_stats: dict[str, Any] = {}
        self._prev_stat_time: float = 0.0

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers = [s for s in self._subscribers if s is not q]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("MetricsCollector started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MetricsCollector stopped")

    async def _collect_loop(self) -> None:
        while self._running:
            try:
                snapshots = await self._collect()
                if snapshots:
                    self.history.append(snapshots)
                    await self._broadcast(snapshots)
            except Exception as e:
                logger.error("Metrics collection error: %s", e)
            await asyncio.sleep(settings.metrics_collection_interval)

    async def _collect(self) -> list[LinkSnapshot]:
        """Try Ryu first, fall back to simulation."""
        snapshots = await self._collect_from_ryu()
        if not snapshots and self.env is not None:
            snapshots = self._collect_from_env()
        return snapshots

    async def _collect_from_ryu(self) -> list[LinkSnapshot]:
        snapshots: list[LinkSnapshot] = []
        try:
            async with RyuControllerClient() as ryu:
                if not await ryu.health_check():
                    return snapshots

                switches = await ryu.get_switches()
                links = await ryu.get_links()

                now = time.time()
                dt = now - self._prev_stat_time if self._prev_stat_time else 1.0
                self._prev_stat_time = now

                for link in links:
                    src_dpid = link["src"]["dpid"]
                    dst_dpid = link["dst"]["dpid"]
                    src_port = link["src"]["port_no"]

                    port_stats = await ryu.get_port_stats(src_dpid)
                    stats_list = port_stats.get(str(src_dpid), [])
                    port_data = next(
                        (p for p in stats_list if p["port_no"] == src_port), None
                    )

                    utilization = 0.0
                    throughput_mbps = 0.0
                    if port_data:
                        key = f"{src_dpid}_{src_port}"
                        prev = self._prev_port_stats.get(key, {})
                        tx_bytes = port_data.get("tx_bytes", 0) - prev.get("tx_bytes", 0)
                        throughput_mbps = (tx_bytes * 8) / (dt * 1e6)
                        capacity_mbps = settings.default_link_bandwidth
                        utilization = min(1.0, throughput_mbps / capacity_mbps)
                        self._prev_port_stats[key] = port_data

                    snapshots.append(
                        LinkSnapshot(
                            src_dpid=src_dpid,
                            dst_dpid=dst_dpid,
                            utilization=utilization,
                            throughput_mbps=round(throughput_mbps, 2),
                            latency_ms=settings.default_link_latency,
                            packet_loss=0.0,
                        )
                    )
        except Exception as e:
            logger.debug("Ryu metrics unavailable: %s", e)
        return snapshots

    def _collect_from_env(self) -> list[LinkSnapshot]:
        """Extract metrics directly from the simulation state."""
        snapshots: list[LinkSnapshot] = []
        if self.env is None:
            return snapshots

        for (src, dst), ls in self.env.sim_state.link_states.items():
            src_dpid = self.env.topology.graph.nodes.get(src, {}).get("dpid", 0)
            dst_dpid = self.env.topology.graph.nodes.get(dst, {}).get("dpid", 0)
            if src_dpid == 0 or dst_dpid == 0:
                continue
            snapshots.append(
                LinkSnapshot(
                    src_dpid=src_dpid,
                    dst_dpid=dst_dpid,
                    utilization=ls.utilization,
                    throughput_mbps=ls.utilization * ls.bandwidth,
                    latency_ms=ls.latency_ms,
                    packet_loss=ls.packet_loss,
                    queue_occupancy=ls.queue_occupancy,
                    dropped_packets=ls.dropped_packets,
                )
            )
        return snapshots

    async def _broadcast(self, snapshots: list[LinkSnapshot]) -> None:
        payload = {
            "event": "metrics_update",
            "data": [s.to_dict() for s in snapshots],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def get_latest_snapshot(self) -> list[LinkSnapshot]:
        return self.history[-1] if self.history else []

    def get_summary(self) -> dict[str, Any]:
        latest = self.get_latest_snapshot()
        if not latest:
            return {}
        utils = [s.utilization for s in latest]
        latencies = [s.latency_ms for s in latest]
        losses = [s.packet_loss for s in latest]
        throughputs = [s.throughput_mbps for s in latest]
        congested = sum(1 for u in utils if u > 0.8)
        return {
            "avg_utilization": round(sum(utils) / len(utils), 4) if utils else 0.0,
            "max_utilization": round(max(utils), 4) if utils else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "avg_throughput_mbps": round(sum(throughputs) / len(throughputs), 2) if throughputs else 0.0,
            "total_throughput_mbps": round(sum(throughputs), 2),
            "avg_packet_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
            "congested_links": congested,
            "total_links": len(latest),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
