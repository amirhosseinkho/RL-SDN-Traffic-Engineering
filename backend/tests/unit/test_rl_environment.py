"""Unit tests for the SDN RL environment."""
import numpy as np
import pytest

from app.database.models import TopologyType
from app.database.schemas import TopologyConfig
from app.rl.environment import SDNRoutingEnv
from app.topology.generator import TopologyGenerator


@pytest.fixture
def env() -> SDNRoutingEnv:
    generator = TopologyGenerator()
    cfg = TopologyConfig(
        topology_type=TopologyType.LINEAR, num_switches=4, num_hosts=4, name="test-env"
    )
    topo = generator.generate(cfg)
    return SDNRoutingEnv(topo, max_flows=8, max_steps=50)


def test_observation_space_shape(env: SDNRoutingEnv) -> None:
    obs, _ = env.reset()
    assert obs.shape == env.observation_space.shape


def test_observation_bounds(env: SDNRoutingEnv) -> None:
    obs, _ = env.reset()
    assert (obs >= 0.0).all()
    assert (obs <= 1.0).all()


def test_action_space_shape(env: SDNRoutingEnv) -> None:
    assert len(env.action_space.nvec) == env.max_flows


def test_step_returns_valid_obs(env: SDNRoutingEnv) -> None:
    env.reset()
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    assert obs.shape == env.observation_space.shape
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert isinstance(info, dict)


def test_episode_terminates(env: SDNRoutingEnv) -> None:
    env.reset()
    done = False
    steps = 0
    while not done and steps < 1000:
        action = env.action_space.sample()
        _, _, terminated, truncated, _ = env.step(action)
        done = terminated or truncated
        steps += 1
    assert done, "Episode should terminate within max_steps"


def test_reward_is_finite(env: SDNRoutingEnv) -> None:
    env.reset()
    for _ in range(10):
        action = env.action_space.sample()
        _, reward, _, _, _ = env.step(action)
        assert np.isfinite(reward)


def test_reset_clears_state(env: SDNRoutingEnv) -> None:
    obs1, _ = env.reset()
    for _ in range(5):
        env.step(env.action_space.sample())
    obs2, _ = env.reset()
    assert env.sim_state.step_count == 0
    assert env.sim_state.episode_reward == 0.0


def test_info_dict_keys(env: SDNRoutingEnv) -> None:
    obs, info = env.reset()
    expected_keys = {
        "step", "episode_reward", "avg_utilization", "max_utilization",
        "avg_latency_ms", "avg_packet_loss", "num_congested_links", "num_active_flows",
    }
    assert expected_keys.issubset(info.keys())


def test_link_utilization_bounded(env: SDNRoutingEnv) -> None:
    env.reset()
    for _ in range(20):
        env.step(env.action_space.sample())
    for ls in env.sim_state.link_states.values():
        assert 0.0 <= ls.utilization <= 1.0


def test_random_seed_reproducibility() -> None:
    generator = TopologyGenerator()
    cfg = TopologyConfig(topology_type=TopologyType.LINEAR, num_switches=3, num_hosts=3, name="seed-test")
    topo = generator.generate(cfg)
    env1 = SDNRoutingEnv(topo, max_flows=4, max_steps=20)
    env2 = SDNRoutingEnv(topo, max_flows=4, max_steps=20)
    obs1, _ = env1.reset(seed=42)
    obs2, _ = env2.reset(seed=42)
    np.testing.assert_array_equal(obs1, obs2)
