"""Policies: ECMP hashing, equal-cost paths, and agreement with the simulator's baselines."""
import numpy as np
import pytest
from app.rl.environment import SDNRoutingEnv
from app.simulation.evaluator import LeastLoadedRouter

from emulation.churn import rule_changes
from emulation.mapping import build_mapping, experiment_topology
from emulation.policies import (
    ECMP,
    LeastLoaded,
    Random,
    ShortestPath,
    ecmp_hash,
    equal_cost_indices,
)
from emulation.traffic import FlowSpec


@pytest.fixture(scope="module")
def topo():
    return experiment_topology()


@pytest.fixture()
def env(topo):
    env = SDNRoutingEnv(topo, seed=1000)
    env.reset(seed=1000)
    return env


def test_ecmp_hash_is_deterministic_and_in_range():
    t = ("192.168.1.2", "192.168.3.6", 17, 40001, 5201)
    assert ecmp_hash(t, 2) == ecmp_hash(t, 2)
    assert all(0 <= ecmp_hash((*t[:3], 40001 + i, 5201 + i), 3) < 3 for i in range(100))


def test_ecmp_hash_spreads_flows():
    counts = np.bincount([ecmp_hash(("10.0.0.1", "10.0.0.2", 17, 40000 + i, 5201), 2) for i in range(1000)], minlength=2)
    assert 400 < counts[0] < 600


def test_equal_cost_paths_between_leaves_are_the_two_spines(env):
    paths = env._get_paths("h1", "h5")
    idx = equal_cost_indices(env, "h1", "h5")
    assert sorted(paths[i][2] for i in idx) == ["spine1", "spine2"]
    assert equal_cost_indices(env, "h1", "h2") == [0]  # same leaf: one path (the rest is padding)


def test_ecmp_policy_is_static_and_uses_only_equal_cost_paths(env, topo):
    mapping = build_mapping(topo, 0.05)
    flows = [FlowSpec(i, f.src_host, f.dst_host, mapping.hosts[f.src_host].ip, mapping.hosts[f.dst_host].ip)
             for i, f in enumerate(env.sim_state.flow_demands)]
    policy = ECMP([f.five_tuple for f in flows])
    a1 = policy.select(env, None)
    env.step(a1)
    a2 = policy.select(env, None)
    assert (a1 == a2).all()
    for f, i in zip(env.sim_state.flow_demands, a1):
        assert i in equal_cost_indices(env, f.src_host, f.dst_host)


def test_baselines_match_the_simulator(env):
    obs = env._get_observation()
    assert (ShortestPath().select(env, obs) == 0).all()
    assert (LeastLoaded().select(env, obs) == LeastLoadedRouter(env).select_action(obs)).all()
    a = Random(7).select(env, obs)
    assert a.shape == (16,) and a.max() < 4


def test_rule_changes(topo):
    mapping = build_mapping(topo, 0.05)
    via1 = ["h1", "leaf1", "spine1", "leaf3", "h5"]
    via2 = ["h1", "leaf1", "spine2", "leaf3", "h5"]
    assert rule_changes(None, via1, mapping) == 6  # 3 switches x 2 directions
    assert rule_changes(via1, via1, mapping) == 0
    assert rule_changes(via1, via2, mapping) == 6  # per direction: add spine2, rewrite leaf1, delete spine1
