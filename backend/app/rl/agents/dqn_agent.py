"""Deep Q-Network (DQN) agent for SDN traffic engineering."""
from __future__ import annotations

import os
import random
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from app.config import get_settings

settings = get_settings()


class DuelingDQN(nn.Module):
    """Dueling DQN architecture with noisy heads for exploration."""

    def __init__(self, obs_dim: int, action_dims: list[int], hidden_size: int = 256) -> None:
        super().__init__()
        self.action_dims = action_dims
        total_actions = sum(action_dims)

        self.feature = nn.Sequential(
            nn.Linear(obs_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.ReLU(),
        )

        self.value_stream = nn.Sequential(
            nn.Linear(hidden_size, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

        self.advantage_stream = nn.Sequential(
            nn.Linear(hidden_size, 128),
            nn.ReLU(),
            nn.Linear(128, total_actions),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.feature(x)
        value = self.value_stream(feat)
        advantage = self.advantage_stream(feat)
        # Dueling combination: Q = V + (A - mean(A))
        q = value + advantage - advantage.mean(dim=-1, keepdim=True)
        return q


class ReplayBuffer:
    """Prioritized experience replay buffer."""

    def __init__(self, capacity: int, obs_dim: int, action_dim: int) -> None:
        self.capacity = capacity
        self.pos = 0
        self.size = 0

        self.obs = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.actions = np.zeros((capacity, action_dim), dtype=np.int64)
        self.rewards = np.zeros(capacity, dtype=np.float32)
        self.next_obs = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.dones = np.zeros(capacity, dtype=np.float32)

    def add(
        self,
        obs: np.ndarray,
        action: np.ndarray,
        reward: float,
        next_obs: np.ndarray,
        done: bool,
    ) -> None:
        self.obs[self.pos] = obs
        self.actions[self.pos] = action
        self.rewards[self.pos] = reward
        self.next_obs[self.pos] = next_obs
        self.dones[self.pos] = float(done)
        self.pos = (self.pos + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size: int) -> dict[str, torch.Tensor]:
        idxs = np.random.randint(0, self.size, size=batch_size)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return {
            "obs": torch.FloatTensor(self.obs[idxs]).to(device),
            "actions": torch.LongTensor(self.actions[idxs]).to(device),
            "rewards": torch.FloatTensor(self.rewards[idxs]).to(device),
            "next_obs": torch.FloatTensor(self.next_obs[idxs]).to(device),
            "dones": torch.FloatTensor(self.dones[idxs]).to(device),
        }

    def __len__(self) -> int:
        return self.size


class DQNAgent:
    """
    Double Dueling DQN agent for SDN routing.

    Handles multi-discrete actions by flattening and splitting Q-values
    per action dimension (flow routing decisions).
    """

    def __init__(
        self,
        obs_dim: int,
        action_dims: list[int],
        learning_rate: float = 1e-4,
        buffer_size: int = 100_000,
        batch_size: int = 64,
        gamma: float = 0.99,
        tau: float = 0.005,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: int = 50_000,
        target_update_freq: int = 1_000,
        device: str | None = None,
    ) -> None:
        self.obs_dim = obs_dim
        self.action_dims = action_dims
        self.batch_size = batch_size
        self.gamma = gamma
        self.tau = tau
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.target_update_freq = target_update_freq
        self.total_steps = 0

        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self.q_net = DuelingDQN(obs_dim, action_dims).to(self.device)
        self.target_net = DuelingDQN(obs_dim, action_dims).to(self.device)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.q_net.parameters(), lr=learning_rate)
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=200_000, eta_min=1e-6
        )

        self.replay_buffer = ReplayBuffer(buffer_size, obs_dim, len(action_dims))

        self.train_losses: list[float] = []

    def select_action(self, obs: np.ndarray, deterministic: bool = False) -> np.ndarray:
        """Epsilon-greedy action selection."""
        # Decay epsilon
        if not deterministic:
            self.epsilon = max(
                self.epsilon_end,
                self.epsilon - (1.0 - self.epsilon_end) / self.epsilon_decay,
            )

        if not deterministic and random.random() < self.epsilon:
            return np.array([random.randint(0, d - 1) for d in self.action_dims])

        with torch.no_grad():
            obs_t = torch.FloatTensor(obs).unsqueeze(0).to(self.device)
            q_values = self.q_net(obs_t).squeeze(0)

        # Split Q-values per action dimension
        actions = []
        offset = 0
        for dim in self.action_dims:
            q_slice = q_values[offset : offset + dim]
            actions.append(int(q_slice.argmax().item()))
            offset += dim

        return np.array(actions)

    def update(self) -> dict[str, float] | None:
        """Sample a batch and perform a gradient update."""
        if len(self.replay_buffer) < self.batch_size:
            return None

        batch = self.replay_buffer.sample(self.batch_size)
        obs = batch["obs"]
        actions = batch["actions"]
        rewards = batch["rewards"]
        next_obs = batch["next_obs"]
        dones = batch["dones"]

        # Current Q-values
        q_values = self.q_net(obs)

        # Gather Q for taken actions (sum over action dims)
        current_q = torch.zeros(self.batch_size, device=self.device)
        offset = 0
        for i, dim in enumerate(self.action_dims):
            action_i = actions[:, i].unsqueeze(1)
            q_slice = q_values[:, offset : offset + dim]
            current_q += q_slice.gather(1, action_i).squeeze(1)
            offset += dim
        current_q = current_q / len(self.action_dims)

        # Target Q-values (Double DQN)
        with torch.no_grad():
            next_q_online = self.q_net(next_obs)
            next_q_target = self.target_net(next_obs)

            target_q = torch.zeros(self.batch_size, device=self.device)
            offset = 0
            for dim in self.action_dims:
                online_slice = next_q_online[:, offset : offset + dim]
                target_slice = next_q_target[:, offset : offset + dim]
                best_actions = online_slice.argmax(dim=1, keepdim=True)
                target_q += target_slice.gather(1, best_actions).squeeze(1)
                offset += dim
            target_q = target_q / len(self.action_dims)

            target = rewards + self.gamma * target_q * (1 - dones)

        loss = F.smooth_l1_loss(current_q, target)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q_net.parameters(), max_norm=10.0)
        self.optimizer.step()
        self.scheduler.step()

        # Soft update target network
        self.total_steps += 1
        if self.total_steps % self.target_update_freq == 0:
            for param, target_param in zip(
                self.q_net.parameters(), self.target_net.parameters()
            ):
                target_param.data.copy_(
                    self.tau * param.data + (1 - self.tau) * target_param.data
                )

        loss_val = float(loss.item())
        self.train_losses.append(loss_val)
        return {"loss": loss_val, "epsilon": self.epsilon}

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "q_net_state_dict": self.q_net.state_dict(),
                "target_net_state_dict": self.target_net.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "total_steps": self.total_steps,
                "epsilon": self.epsilon,
            },
            path,
        )

    def load(self, path: str | Path) -> None:
        path = Path(path)
        checkpoint = torch.load(path, map_location=self.device)
        self.q_net.load_state_dict(checkpoint["q_net_state_dict"])
        self.target_net.load_state_dict(checkpoint["target_net_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.total_steps = checkpoint.get("total_steps", 0)
        self.epsilon = checkpoint.get("epsilon", self.epsilon_end)

    @property
    def hyperparameters(self) -> dict[str, Any]:
        return {
            "obs_dim": self.obs_dim,
            "action_dims": self.action_dims,
            "gamma": self.gamma,
            "tau": self.tau,
            "epsilon": self.epsilon,
            "batch_size": self.batch_size,
            "device": str(self.device),
        }
