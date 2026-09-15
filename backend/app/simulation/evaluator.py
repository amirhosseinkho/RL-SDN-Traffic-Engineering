"""Comparative evaluation of routing algorithms."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import numpy as np

from app.database.models import AgentType
from app.rl.environment import SDNRoutingEnv
from app.topology.generator import TopologyDefinition

logger = logging.getLogger(__name__)


@dataclass
class EvalEpisodeResult:
    agent_type: AgentType
    episode: int
    total_reward: float
    avg_utilization: float
    avg_latency_ms: float
    avg_packet_loss: float
    steps: int
    convergence_step: int | None = None


@dataclass
class EvalResult:
    agent_type: AgentType
    episodes: list[EvalEpisodeResult] = field(default_factory=list)

    @property
    def avg_reward(self) -> float:
        return float(np.mean([e.total_reward for e in self.episodes])) if self.episodes else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return float(np.mean([e.avg_latency_ms for e in self.episodes])) if self.episodes else 0.0

    @property
    def avg_throughput_pct(self) -> float:
        return float(np.mean([e.avg_utilization for e in self.episodes])) * 100.0 if self.episodes else 0.0

    @property
    def avg_packet_loss(self) -> float:
        return float(np.mean([e.avg_packet_loss for e in self.episodes])) if self.episodes else 0.0

    @property
    def convergence_time_s(self) -> float | None:
        times = [e.convergence_step for e in self.episodes if e.convergence_step is not None]
        return float(np.mean(times)) if times else None


class ShortestPathRouter:
    """Baseline: always route via single shortest path."""

    def __init__(self, env: SDNRoutingEnv) -> None:
        self.env = env

    def select_action(self, obs: np.ndarray) -> np.ndarray:
        # Always choose path index 0 (shortest path)
        return np.zeros(self.env.max_flows, dtype=np.int64)


class ECMPRouter:
    """Equal-Cost Multi-Path: round-robin over available paths."""

    def __init__(self, env: SDNRoutingEnv) -> None:
        self.env = env
        self._counters: dict[int, int] = {}

    def select_action(self, obs: np.ndarray) -> np.ndarray:
        actions = []
        for i in range(self.env.max_flows):
            count = self._counters.get(i, 0)
            # Get number of actual paths for this flow
            if i < len(self.env.sim_state.flow_demands):
                flow = self.env.sim_state.flow_demands[i]
                paths = self.env._get_paths(flow.src_host, flow.dst_host)
                num_paths = max(1, len(paths))
            else:
                num_paths = self.env.max_paths
            actions.append(count % num_paths)
            self._counters[i] = count + 1
        return np.array(actions, dtype=np.int64)


class Evaluator:
    """Runs comparative evaluation across routing algorithms."""

    def __init__(self, topology: TopologyDefinition) -> None:
        self.topology = topology

    async def evaluate_agent(
        self,
        agent_type: AgentType,
        agent: Any | None,
        num_episodes: int = 10,
        max_steps: int = 200,
    ) -> EvalResult:
        result = EvalResult(agent_type=agent_type)
        env = SDNRoutingEnv(self.topology, max_steps=max_steps)

        if agent_type == AgentType.SHORTEST_PATH:
            router: Any = ShortestPathRouter(env)
        elif agent_type == AgentType.ECMP:
            router = ECMPRouter(env)
        else:
            router = agent

        for ep in range(num_episodes):
            obs, _ = env.reset()
            ep_reward = 0.0
            ep_steps = 0
            convergence_step = None
            reward_history: list[float] = []

            while True:
                if agent_type in (AgentType.SHORTEST_PATH, AgentType.ECMP):
                    action = router.select_action(obs)
                else:
                    # DQN or PPO
                    if hasattr(router, "select_action"):
                        result_action = router.select_action(obs, deterministic=True)
                        action = result_action[0] if isinstance(result_action, tuple) else result_action
                    else:
                        action = env.action_space.sample()

                obs, reward, terminated, truncated, info = env.step(action)
                ep_reward += reward
                ep_steps += 1
                reward_history.append(reward)

                # Detect convergence: reward stabilizes within 5% of rolling mean
                if len(reward_history) >= 20 and convergence_step is None:
                    recent = reward_history[-20:]
                    if np.std(recent) < abs(np.mean(recent)) * 0.05:
                        convergence_step = ep_steps

                if terminated or truncated:
                    break

            ep_result = EvalEpisodeResult(
                agent_type=agent_type,
                episode=ep,
                total_reward=ep_reward,
                avg_utilization=info.get("avg_utilization", 0.0),
                avg_latency_ms=info.get("avg_latency_ms", 0.0),
                avg_packet_loss=info.get("avg_packet_loss", 0.0),
                steps=ep_steps,
                convergence_step=convergence_step,
            )
            result.episodes.append(ep_result)
            await asyncio.sleep(0)

        return result

    async def compare_all(
        self,
        agents: dict[AgentType, Any],
        num_episodes: int = 10,
    ) -> dict[AgentType, EvalResult]:
        results: dict[AgentType, EvalResult] = {}

        # Always include baselines
        for baseline in [AgentType.SHORTEST_PATH, AgentType.ECMP]:
            logger.info("Evaluating %s baseline...", baseline.value)
            results[baseline] = await self.evaluate_agent(baseline, None, num_episodes)

        # Evaluate RL agents
        for agent_type, agent in agents.items():
            if agent is None:
                continue
            logger.info("Evaluating %s agent...", agent_type.value)
            results[agent_type] = await self.evaluate_agent(agent_type, agent, num_episodes)

        return results

    def compute_improvements(
        self, results: dict[AgentType, EvalResult]
    ) -> dict[str, dict[str, float]]:
        """Compute improvement of each agent over shortest-path baseline."""
        baseline = results.get(AgentType.SHORTEST_PATH)
        if not baseline:
            return {}

        improvements: dict[str, dict[str, float]] = {}
        for agent_type, result in results.items():
            if agent_type == AgentType.SHORTEST_PATH:
                continue

            latency_improvement = 0.0
            if baseline.avg_latency_ms > 0:
                latency_improvement = (
                    (baseline.avg_latency_ms - result.avg_latency_ms) / baseline.avg_latency_ms * 100
                )

            throughput_improvement = result.avg_throughput_pct - baseline.avg_throughput_pct
            loss_improvement = baseline.avg_packet_loss - result.avg_packet_loss

            improvements[agent_type.value] = {
                "latency_reduction_pct": round(latency_improvement, 2),
                "throughput_gain_pct": round(throughput_improvement, 2),
                "packet_loss_reduction": round(loss_improvement, 4),
                "reward_improvement": round(result.avg_reward - baseline.avg_reward, 4),
            }

        return improvements
