"""Routing policies with one interface: select(env, obs) -> one path index per flow.

`env` is an SDNRoutingEnv holding the current flows and demands (and, in the emulation, the
measured link states); indices refer to env._get_paths(src, dst), the simulator's K shortest paths.
"""
from __future__ import annotations

import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from app.rl.environment import SDNRoutingEnv
from app.simulation.evaluator import LeastLoadedRouter

POLICIES = ["shortest_path", "ecmp", "random", "least_loaded", "dqn", "ppo"]


class Policy(Protocol):
    name: str

    def select(self, env: SDNRoutingEnv, obs: np.ndarray) -> np.ndarray: ...


class ShortestPath:
    name = "shortest_path"

    def select(self, env: SDNRoutingEnv, obs: np.ndarray) -> np.ndarray:
        return np.zeros(env.max_flows, dtype=np.int64)


def ecmp_hash(five_tuple: Sequence[Any], n: int) -> int:
    """Index in [0, n) from a CRC32 of the flow's 5-tuple (src IP, dst IP, proto, sport, dport)."""
    key = "|".join(str(x) for x in five_tuple).encode()
    return zlib.crc32(key) % n


def equal_cost_indices(env: SDNRoutingEnv, src: str, dst: str) -> list[int]:
    """Indices of the distinct candidate paths with the fewest switch hops."""
    paths = env._get_paths(src, dst)
    seen, distinct = set(), []
    for i, p in enumerate(paths):
        if tuple(p) not in seen:
            seen.add(tuple(p))
            distinct.append(i)
    fewest = min(len(env._switch_hops(paths[i])) for i in distinct)
    return [i for i in distinct if len(env._switch_hops(paths[i])) == fewest]


class ECMP:
    """Per-flow hash over the equal-cost paths: each flow keeps one path, as in switch ECMP.

    (The simulator's evaluator calls round-robin over all 4 candidates "ECMP"; this is the
    hash-based variant, used in both the emulation and the matched simulation runs.)
    """

    name = "ecmp"

    def __init__(self, five_tuples: Sequence[Sequence[Any]]) -> None:
        self.five_tuples = list(five_tuples)

    def select(self, env: SDNRoutingEnv, obs: np.ndarray) -> np.ndarray:
        action = np.zeros(env.max_flows, dtype=np.int64)
        for i, flow in enumerate(env.sim_state.flow_demands[: env.max_flows]):
            candidates = equal_cost_indices(env, flow.src_host, flow.dst_host)
            action[i] = candidates[ecmp_hash(self.five_tuples[i], len(candidates))]
        return action


class Random:
    name = "random"

    def __init__(self, seed: int) -> None:
        self._rng = np.random.default_rng(seed)

    def select(self, env: SDNRoutingEnv, obs: np.ndarray) -> np.ndarray:
        return self._rng.integers(0, env.action_space.nvec)


class LeastLoaded:
    """The simulator's least-loaded heuristic, unchanged (largest flow first, each on the
    candidate whose busiest link would be least loaded). It plans from the flows' demands."""

    name = "least_loaded"

    def select(self, env: SDNRoutingEnv, obs: np.ndarray) -> np.ndarray:
        return LeastLoadedRouter(env).select_action(obs)


class Learned:
    def __init__(self, name: str, model_path: Path, env: SDNRoutingEnv) -> None:
        from app.rl.agents.dqn_agent import DQNAgent
        from app.rl.agents.ppo_agent import PPOAgent

        cls = {"dqn": DQNAgent, "ppo": PPOAgent}[name]
        self.name = name
        self.agent = cls(obs_dim=env.observation_space.shape[0], action_dims=list(env.action_space.nvec))
        self.agent.load(model_path)

    def select(self, env: SDNRoutingEnv, obs: np.ndarray) -> np.ndarray:
        result = self.agent.select_action(obs, deterministic=True)
        return np.asarray(result[0] if isinstance(result, tuple) else result, dtype=np.int64)


def make_policy(name: str, env: SDNRoutingEnv, five_tuples: Sequence[Sequence[Any]], seed: int, model: Path | None = None) -> Policy:
    if name == "shortest_path":
        return ShortestPath()
    if name == "ecmp":
        return ECMP(five_tuples)
    if name == "random":
        return Random(seed)
    if name == "least_loaded":
        return LeastLoaded()
    if name in ("dqn", "ppo"):
        if model is None:
            raise ValueError(f"{name} needs --model")
        return Learned(name, model, env)
    raise ValueError(f"unknown policy {name}")
