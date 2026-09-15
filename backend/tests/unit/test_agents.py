"""Unit tests for DQN and PPO agents."""
import numpy as np
import pytest
import torch

from app.rl.agents.dqn_agent import DQNAgent, ReplayBuffer, DuelingDQN
from app.rl.agents.ppo_agent import PPOAgent, ActorCriticNetwork, RolloutBuffer


# ─── DQN Tests ────────────────────────────────────────────────────────────────

class TestDuelingDQN:
    def test_forward_shape(self) -> None:
        net = DuelingDQN(obs_dim=20, action_dims=[4, 4], hidden_size=64)
        x = torch.randn(8, 20)
        q = net(x)
        assert q.shape == (8, 8)  # sum of action_dims

    def test_dueling_advantage_centering(self) -> None:
        net = DuelingDQN(obs_dim=10, action_dims=[3], hidden_size=32)
        x = torch.randn(1, 10)
        q = net(x)
        assert q.shape == (1, 3)


class TestReplayBuffer:
    def test_add_and_sample(self) -> None:
        buf = ReplayBuffer(capacity=1000, obs_dim=10, action_dim=4)
        for _ in range(100):
            buf.add(np.zeros(10), np.zeros(4, dtype=np.int64), 1.0, np.ones(10), False)
        assert len(buf) == 100
        batch = buf.sample(32)
        assert batch["obs"].shape == (32, 10)
        assert batch["actions"].shape == (32, 4)

    def test_capacity_wrapping(self) -> None:
        buf = ReplayBuffer(capacity=50, obs_dim=5, action_dim=2)
        for i in range(100):
            buf.add(np.zeros(5), np.zeros(2, dtype=np.int64), float(i), np.zeros(5), False)
        assert len(buf) == 50


class TestDQNAgent:
    @pytest.fixture
    def agent(self) -> DQNAgent:
        return DQNAgent(obs_dim=20, action_dims=[4, 4], buffer_size=1000, batch_size=16, device="cpu")

    def test_select_action_shape(self, agent: DQNAgent) -> None:
        obs = np.zeros(20, dtype=np.float32)
        action = agent.select_action(obs)
        assert action.shape == (2,)
        assert all(0 <= a < 4 for a in action)

    def test_update_returns_loss(self, agent: DQNAgent) -> None:
        obs = np.zeros(20, dtype=np.float32)
        action = np.array([0, 0], dtype=np.int64)
        for _ in range(20):
            agent.replay_buffer.add(obs, action, 1.0, obs, False)
        result = agent.update()
        assert result is not None
        assert "loss" in result

    def test_save_load(self, agent: DQNAgent, tmp_path) -> None:
        path = tmp_path / "dqn.pt"
        agent.save(path)
        agent2 = DQNAgent(obs_dim=20, action_dims=[4, 4], device="cpu")
        agent2.load(path)
        obs = np.zeros(20, dtype=np.float32)
        a1 = agent.select_action(obs, deterministic=True)
        a2 = agent2.select_action(obs, deterministic=True)
        np.testing.assert_array_equal(a1, a2)

    def test_epsilon_decays(self, agent: DQNAgent) -> None:
        initial_eps = agent.epsilon
        obs = np.zeros(20, dtype=np.float32)
        for _ in range(100):
            agent.select_action(obs)
        assert agent.epsilon < initial_eps


# ─── PPO Tests ────────────────────────────────────────────────────────────────

class TestActorCriticNetwork:
    def test_get_action_shape(self) -> None:
        net = ActorCriticNetwork(obs_dim=20, action_dims=[4, 4], hidden_size=64)
        obs = torch.randn(1, 20)
        action, log_prob, entropy, value = net.get_action(obs)
        assert action.shape == (1, 2)
        assert log_prob.shape == (1,)
        assert value.shape == (1,)


class TestRolloutBuffer:
    def test_add_and_get_batches(self) -> None:
        buf = RolloutBuffer(n_steps=32, obs_dim=10, action_dim=4, gamma=0.99, gae_lambda=0.95)
        for _ in range(32):
            buf.add(np.zeros(10), np.zeros(4, dtype=np.int64), 1.0, 0.5, -0.1, False)
        buf.compute_returns_and_advantages(0.0, False)
        device = torch.device("cpu")
        batches = buf.get_batches(8, device)
        assert len(batches) == 4


class TestPPOAgent:
    @pytest.fixture
    def agent(self) -> PPOAgent:
        return PPOAgent(
            obs_dim=20, action_dims=[4, 4], n_steps=32, batch_size=8, n_epochs=2, device="cpu"
        )

    def test_select_action(self, agent: PPOAgent) -> None:
        obs = np.zeros(20, dtype=np.float32)
        action, log_prob, value = agent.select_action(obs)
        assert action.shape == (2,)
        assert isinstance(log_prob, float)
        assert isinstance(value, float)

    def test_update_returns_metrics(self, agent: PPOAgent) -> None:
        obs = np.zeros(20, dtype=np.float32)
        for _ in range(32):
            action, log_prob, value = agent.select_action(obs)
            agent.store_transition(obs, action, 1.0, value, log_prob, False)
        metrics = agent.update(0.0, False)
        assert "policy_loss" in metrics
        assert "value_loss" in metrics

    def test_save_load(self, agent: PPOAgent, tmp_path) -> None:
        path = tmp_path / "ppo.pt"
        agent.save(path)
        agent2 = PPOAgent(obs_dim=20, action_dims=[4, 4], device="cpu")
        agent2.load(path)
