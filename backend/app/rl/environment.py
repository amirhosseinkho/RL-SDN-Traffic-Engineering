"""SDN Routing Gymnasium environment for RL training."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Optional

import gymnasium as gym
import networkx as nx
import numpy as np
from gymnasium import spaces

from app.topology.generator import TopologyDefinition


@dataclass
class LinkState:
    src: str
    dst: str
    bandwidth: float  # Mbps capacity
    utilization: float = 0.0  # 0.0 - 1.0
    latency_ms: float = 5.0
    packet_loss: float = 0.0
    queue_occupancy: float = 0.0
    dropped_packets: int = 0

    @property
    def available_bandwidth(self) -> float:
        return self.bandwidth * (1.0 - self.utilization)

    @property
    def is_congested(self) -> bool:
        return self.utilization > 0.8


@dataclass
class FlowDemand:
    src_host: str
    dst_host: str
    demand_mbps: float
    is_elephant: bool = False
    active_path: Optional[list[str]] = None
    base_demand_mbps: float = 0.0  # demand fluctuates around this value

    def __post_init__(self) -> None:
        if self.base_demand_mbps <= 0.0:
            self.base_demand_mbps = self.demand_mbps


@dataclass
class SimState:
    link_states: dict[tuple[str, str], LinkState] = field(default_factory=dict)
    flow_demands: list[FlowDemand] = field(default_factory=list)
    step_count: int = 0
    episode_reward: float = 0.0
    # Per-flow outcomes of the current routing (see _compute_flow_outcomes)
    delivered_ratio: float = 1.0
    mean_stretch: float = 1.0
    mean_path_latency_ms: float = 0.0


class SDNRoutingEnv(gym.Env):
    """
    Gymnasium environment for SDN traffic engineering via RL.

    Observation space:
      - Per-link: [utilization, latency, packet_loss, queue_occupancy] × num_links
      - Per-flow: [demand, active] × max_flows
      - Global: [avg_utilization, max_utilization, num_congested_links]

    Action space:
      Discrete - select one of the K shortest paths for each active flow.
      Encoded as a multi-discrete action over num_flows × max_paths.

    Reward (per step):
      r = delivered_ratio - latency_weight · (mean_stretch - 1)

      delivered_ratio: fraction of the total demand that is delivered. A link whose offered
        load exceeds its capacity gives every flow on it capacity/offered of its demand; a flow
        delivers its demand times the smallest such share on its path.
      mean_stretch: demand-weighted mean of (path latency incl. queueing) / (latency of the
        flow's shortest path without queueing). 1.0 = every flow at uncongested shortest-path latency.

      Spreading traffic over extra links is not rewarded by itself; detours pay off only when
      they deliver more traffic.
    """

    metadata = {"render_modes": ["human", "rgb_array"]}

    def __init__(
        self,
        topology: TopologyDefinition,
        max_flows: int = 16,
        max_paths_per_flow: int = 4,
        max_steps: int = 200,
        traffic_intensity: float = 0.6,
        congestion_threshold: float = 0.8,
        latency_weight: float = 0.1,
        seed: int = 42,
    ) -> None:
        super().__init__()

        self.topology = topology
        self.graph: nx.Graph = topology.graph.copy()
        self.max_flows = max_flows
        self.max_paths = max_paths_per_flow
        self.max_steps = max_steps
        self.traffic_intensity = traffic_intensity
        self.congestion_threshold = congestion_threshold

        # Trade-off between delivered traffic and latency: with 0.1, ten percentage points of
        # delivered demand are worth doubling the average flow latency.
        self.latency_weight = latency_weight

        # Extract switch and host nodes
        self.switch_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "switch"]
        self.host_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "host"]
        self.switch_links = [
            (u, v)
            for u, v in self.graph.edges()
            if self.graph.nodes[u].get("node_type") == "switch"
            and self.graph.nodes[v].get("node_type") == "switch"
        ]

        self.num_links = len(self.switch_links)
        self._precompute_paths()

        # Observation: link features (4) × links + flow features (2) × max_flows + 3 global
        obs_dim = self.num_links * 4 + self.max_flows * 2 + 3
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(obs_dim,), dtype=np.float32
        )

        # Action: for each flow, choose one of max_paths paths
        self.action_space = spaces.MultiDiscrete([self.max_paths] * self.max_flows)

        self.sim_state = SimState()
        self._rng = np.random.default_rng(seed)

    # ─── Path precomputation ──────────────────────────────────────────────

    def _precompute_paths(self) -> None:
        """Precompute K shortest switch-level paths between all host pairs."""
        self._paths: dict[tuple[str, str], list[list[str]]] = {}
        self._base_latency: dict[tuple[str, str], float] = {}
        hosts = self.host_nodes
        for i, src in enumerate(hosts):
            for dst in hosts[i + 1:]:
                try:
                    # islice: the generator would otherwise enumerate every simple path
                    paths = list(
                        islice(nx.shortest_simple_paths(self.graph, src, dst, weight="latency"), self.max_paths)
                    )
                    # Pad to max_paths
                    while len(paths) < self.max_paths:
                        paths.append(paths[0] if paths else [])
                    self._paths[(src, dst)] = paths
                    self._paths[(dst, src)] = [list(reversed(p)) for p in paths]
                    base = self._switch_latency(paths[0]) if paths else 0.0
                    self._base_latency[(src, dst)] = base
                    self._base_latency[(dst, src)] = base
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    self._paths[(src, dst)] = []
                    self._paths[(dst, src)] = []

    def _get_paths(self, src: str, dst: str) -> list[list[str]]:
        return self._paths.get((src, dst), [])

    def _switch_hops(self, path: list[str]) -> list[tuple[str, str]]:
        """Switch-to-switch hops of a path (host access links are not modelled)."""
        return [
            (u, v)
            for u, v in zip(path, path[1:])
            if self.graph.nodes[u].get("node_type") == "switch"
            and self.graph.nodes[v].get("node_type") == "switch"
        ]

    def _switch_latency(self, path: list[str]) -> float:
        """Propagation latency of a path's switch hops, without queueing."""
        return sum(self.graph[u][v].get("latency", 5.0) for u, v in self._switch_hops(path))

    # ─── Reset ───────────────────────────────────────────────────────────

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)

        self.sim_state = SimState()
        self._initialize_link_states()
        self._generate_traffic()
        self._apply_initial_routing()

        obs = self._get_observation()
        info = self._get_info()
        return obs, info

    def _initialize_link_states(self) -> None:
        for u, v in self.switch_links:
            bw = self.graph[u][v].get("bandwidth", 100.0)
            lat = self.graph[u][v].get("latency", 5.0)
            self.sim_state.link_states[(u, v)] = LinkState(u, v, bw, latency_ms=lat)
            self.sim_state.link_states[(v, u)] = LinkState(v, u, bw, latency_ms=lat)

    def _generate_traffic(self) -> None:
        """Generate a random traffic matrix."""
        hosts = self.host_nodes
        if len(hosts) < 2:
            return

        num_flows = min(
            self.max_flows,
            max(1, int(len(hosts) * (len(hosts) - 1) / 2 * self.traffic_intensity)),
        )

        self.sim_state.flow_demands.clear()
        pairs = [(h1, h2) for i, h1 in enumerate(hosts) for h2 in hosts[i + 1:]]
        selected = self._rng.choice(len(pairs), size=min(num_flows, len(pairs)), replace=False)

        for idx in selected:
            src, dst = pairs[idx]
            is_elephant = self._rng.random() < 0.2
            demand = (
                float(self._rng.uniform(50, 200)) if is_elephant else float(self._rng.uniform(1, 20))
            )
            paths = self._get_paths(src, dst)
            self.sim_state.flow_demands.append(
                FlowDemand(src, dst, demand, is_elephant, paths[0] if paths else None)
            )

    def _apply_initial_routing(self) -> None:
        """Route all flows along their initial (shortest) paths."""
        self._update_link_utilization()

    def _update_link_utilization(self) -> None:
        """Recompute link utilizations from flow routing."""
        # Reset utilizations
        for ls in self.sim_state.link_states.values():
            ls.utilization = 0.0
            ls.queue_occupancy = 0.0
            ls.packet_loss = 0.0

        for flow in self.sim_state.flow_demands:
            if flow.active_path is None or len(flow.active_path) < 2:
                continue
            for i in range(len(flow.active_path) - 1):
                u, v = flow.active_path[i], flow.active_path[i + 1]
                if (u, v) in self.sim_state.link_states:
                    ls = self.sim_state.link_states[(u, v)]
                    ls.utilization = min(1.0, ls.utilization + flow.demand_mbps / ls.bandwidth)
                if (v, u) in self.sim_state.link_states:
                    ls = self.sim_state.link_states[(v, u)]
                    ls.utilization = min(1.0, ls.utilization + flow.demand_mbps / ls.bandwidth)

        for ls in self.sim_state.link_states.values():
            # Simulate queue buildup and packet loss
            if ls.utilization > 0.95:
                ls.queue_occupancy = 1.0
                ls.packet_loss = (ls.utilization - 0.95) * 20.0  # up to 1% at 100%
                ls.dropped_packets += int(ls.packet_loss * 100)
            elif ls.utilization > 0.8:
                ls.queue_occupancy = (ls.utilization - 0.8) / 0.15
                ls.packet_loss = 0.0
            else:
                ls.queue_occupancy = ls.utilization * 0.5
                ls.packet_loss = 0.0

            # Latency increases with queue
            base_latency = self.graph.get_edge_data(ls.src, ls.dst, {}).get("latency", 5.0)
            ls.latency_ms = base_latency * (1.0 + ls.queue_occupancy * 3.0)

        self._compute_flow_outcomes()

    def _compute_flow_outcomes(self) -> None:
        """Delivered traffic and path latency of every flow under the current routing.

        Uses the same link model as the utilization above: a link carries the flows crossing
        it in either direction. If their total demand exceeds the link's capacity, each gets
        capacity/offered of its demand, and a flow delivers the smallest share along its path.
        """
        flows = self.sim_state.flow_demands
        offered: dict[frozenset[str], float] = defaultdict(float)
        hops_per_flow = []
        for flow in flows:
            hops = self._switch_hops(flow.active_path or [])
            hops_per_flow.append(hops)
            for u, v in hops:
                offered[frozenset((u, v))] += flow.demand_mbps

        total_demand = delivered = weighted_stretch = weighted_latency = 0.0
        for flow, hops in zip(flows, hops_per_flow):
            share = 1.0
            latency = 0.0
            for u, v in hops:
                ls = self.sim_state.link_states[(u, v)]
                load = offered[frozenset((u, v))]
                if load > ls.bandwidth:
                    share = min(share, ls.bandwidth / load)
                latency += ls.latency_ms
            base = self._base_latency.get((flow.src_host, flow.dst_host), 0.0)
            stretch = latency / base if base > 0 else 1.0

            total_demand += flow.demand_mbps
            delivered += flow.demand_mbps * share
            weighted_stretch += flow.demand_mbps * stretch
            weighted_latency += flow.demand_mbps * latency

        state = self.sim_state
        if total_demand > 0:
            state.delivered_ratio = delivered / total_demand
            state.mean_stretch = weighted_stretch / total_demand
            state.mean_path_latency_ms = weighted_latency / total_demand
        else:
            state.delivered_ratio, state.mean_stretch, state.mean_path_latency_ms = 1.0, 1.0, 0.0

    # ─── Step ────────────────────────────────────────────────────────────

    def step(
        self, action: np.ndarray
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        # Apply routing decisions
        for i, flow in enumerate(self.sim_state.flow_demands):
            if i >= len(action):
                break
            path_idx = int(action[i]) % self.max_paths
            paths = self._get_paths(flow.src_host, flow.dst_host)
            if paths and path_idx < len(paths):
                flow.active_path = paths[path_idx]

        self._update_link_utilization()
        self._evolve_traffic()

        reward = self._compute_reward()
        self.sim_state.episode_reward += reward
        self.sim_state.step_count += 1

        terminated = False
        truncated = self.sim_state.step_count >= self.max_steps

        obs = self._get_observation()
        info = self._get_info()
        return obs, reward, terminated, truncated, info

    def _evolve_traffic(self) -> None:
        """Simulate traffic changes between steps.

        Demand fluctuates around each flow's base demand and returns to it: the deviation
        shrinks by 20% per step, so a burst halves in about three steps. (Applying bursts
        multiplicatively without reversion made total demand grow without bound.)
        """
        for flow in self.sim_state.flow_demands:
            base = flow.base_demand_mbps
            noise = float(self._rng.normal(0, base * 0.05))
            flow.demand_mbps = max(0.1, base + 0.8 * (flow.demand_mbps - base) + noise)
            # Occasional short burst or drop
            if self._rng.random() < 0.05:
                flow.demand_mbps = base * float(self._rng.uniform(1.5, 3.0))
            if self._rng.random() < 0.02:
                flow.demand_mbps = max(0.1, base * 0.3)

    # ─── Reward ──────────────────────────────────────────────────────────

    def _compute_reward(self) -> float:
        """r = delivered_ratio - latency_weight * (mean_stretch - 1); see the class docstring."""
        state = self.sim_state
        return float(state.delivered_ratio - self.latency_weight * (state.mean_stretch - 1.0))

    # ─── Observation ─────────────────────────────────────────────────────

    def _get_observation(self) -> np.ndarray:
        obs = []

        # Link features
        for u, v in self.switch_links:
            ls = self.sim_state.link_states.get((u, v))
            if ls:
                obs.extend([
                    float(ls.utilization),
                    float(min(1.0, ls.latency_ms / 50.0)),
                    float(min(1.0, ls.packet_loss / 5.0)),
                    float(ls.queue_occupancy),
                ])
            else:
                obs.extend([0.0, 0.0, 0.0, 0.0])

        # Flow features (padded to max_flows)
        for i in range(self.max_flows):
            if i < len(self.sim_state.flow_demands):
                flow = self.sim_state.flow_demands[i]
                obs.extend([
                    float(min(1.0, flow.demand_mbps / 200.0)),
                    1.0 if flow.active_path is not None else 0.0,
                ])
            else:
                obs.extend([0.0, 0.0])

        # Global features
        utils = [ls.utilization for ls in self.sim_state.link_states.values()]
        obs.append(float(np.mean(utils)) if utils else 0.0)
        obs.append(float(np.max(utils)) if utils else 0.0)
        congested = sum(1 for u in utils if u > self.congestion_threshold)
        obs.append(float(congested) / max(len(utils), 1))

        arr = np.array(obs, dtype=np.float32)
        return np.clip(arr, 0.0, 1.0)

    def _get_info(self) -> dict[str, Any]:
        link_states = list(self.sim_state.link_states.values())
        utils = [ls.utilization for ls in link_states]
        latencies = [ls.latency_ms for ls in link_states]
        losses = [ls.packet_loss for ls in link_states]
        return {
            "step": self.sim_state.step_count,
            "episode_reward": self.sim_state.episode_reward,
            "avg_utilization": float(np.mean(utils)) if utils else 0.0,
            "max_utilization": float(np.max(utils)) if utils else 0.0,
            "avg_latency_ms": float(np.mean(latencies)) if latencies else 0.0,
            "avg_packet_loss": float(np.mean(losses)) if losses else 0.0,
            "num_congested_links": sum(1 for u in utils if u > self.congestion_threshold),
            "num_active_flows": len(self.sim_state.flow_demands),
            "delivered_ratio": self.sim_state.delivered_ratio,
            "mean_stretch": self.sim_state.mean_stretch,
            "mean_path_latency_ms": self.sim_state.mean_path_latency_ms,
        }

    def render(self) -> None:
        info = self._get_info()
        print(
            f"Step {info['step']:4d} | "
            f"Util: {info['avg_utilization']:.2f} | "
            f"Latency: {info['avg_latency_ms']:.1f}ms | "
            f"Loss: {info['avg_packet_loss']:.3f}% | "
            f"Congested: {info['num_congested_links']}"
        )

    def get_network_metrics(self) -> dict[str, Any]:
        """Return current network state as dict (used by API)."""
        return self._get_info()
