"""Proximal Policy Optimization (PPO) agent for SDN traffic engineering."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical


class ActorCriticNetwork(nn.Module):
    """Shared trunk with separate policy heads per action dimension and a value head."""

    def __init__(
        self,
        obs_dim: int,
        action_dims: list[int],
        hidden_size: int = 256,
    ) -> None:
        super().__init__()
        self.action_dims = action_dims

        self.shared = nn.Sequential(
            nn.Linear(obs_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.Tanh(),
        )

        # One head per flow (action dimension)
        self.policy_heads = nn.ModuleList([
            nn.Sequential(nn.Linear(hidden_size, 64), nn.Tanh(), nn.Linear(64, dim))
            for dim in action_dims
        ])

        self.value_head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.Tanh(),
            nn.Linear(64, 1),
        )

    def forward(
        self, x: torch.Tensor
    ) -> tuple[list[torch.Tensor], torch.Tensor]:
        feat = self.shared(x)
        logits = [head(feat) for head in self.policy_heads]
        value = self.value_head(feat).squeeze(-1)
        return logits, value

    def get_action(
        self, obs: torch.Tensor, action: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Sample action and compute log-prob and entropy."""
        logits_list, value = self.forward(obs)

        log_probs = []
        entropies = []
        actions = []

        for i, logits in enumerate(logits_list):
            dist = Categorical(logits=logits)
            if action is not None:
                a = action[:, i]
            else:
                a = dist.sample()
            actions.append(a)
            log_probs.append(dist.log_prob(a))
            entropies.append(dist.entropy())

        total_log_prob = torch.stack(log_probs, dim=-1).sum(dim=-1)
        total_entropy = torch.stack(entropies, dim=-1).mean(dim=-1)
        action_tensor = torch.stack(actions, dim=-1)

        return action_tensor, total_log_prob, total_entropy, value


class RolloutBuffer:
    """On-policy rollout buffer for PPO."""

    def __init__(self, n_steps: int, obs_dim: int, action_dim: int, gamma: float, gae_lambda: float) -> None:
        self.n_steps = n_steps
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.pos = 0
        self.full = False

        self.obs = np.zeros((n_steps, obs_dim), dtype=np.float32)
        self.actions = np.zeros((n_steps, action_dim), dtype=np.int64)
        self.rewards = np.zeros(n_steps, dtype=np.float32)
        self.values = np.zeros(n_steps, dtype=np.float32)
        self.log_probs = np.zeros(n_steps, dtype=np.float32)
        self.dones = np.zeros(n_steps, dtype=np.float32)
        self.advantages = np.zeros(n_steps, dtype=np.float32)
        self.returns = np.zeros(n_steps, dtype=np.float32)

    def add(
        self,
        obs: np.ndarray,
        action: np.ndarray,
        reward: float,
        value: float,
        log_prob: float,
        done: bool,
    ) -> None:
        self.obs[self.pos] = obs
        self.actions[self.pos] = action
        self.rewards[self.pos] = reward
        self.values[self.pos] = value
        self.log_probs[self.pos] = log_prob
        self.dones[self.pos] = float(done)
        self.pos = (self.pos + 1) % self.n_steps
        if self.pos == 0:
            self.full = True

    def compute_returns_and_advantages(self, last_value: float, last_done: bool) -> None:
        """Compute GAE-Lambda advantages."""
        last_gae = 0.0
        size = self.n_steps if self.full else self.pos

        for t in reversed(range(size)):
            if t == size - 1:
                next_non_terminal = 1.0 - float(last_done)
                next_value = last_value
            else:
                next_non_terminal = 1.0 - self.dones[t + 1]
                next_value = self.values[t + 1]

            delta = self.rewards[t] + self.gamma * next_value * next_non_terminal - self.values[t]
            last_gae = delta + self.gamma * self.gae_lambda * next_non_terminal * last_gae
            self.advantages[t] = last_gae

        self.returns[:size] = self.advantages[:size] + self.values[:size]

    def get_batches(self, batch_size: int, device: torch.device) -> list[dict[str, torch.Tensor]]:
        size = self.n_steps if self.full else self.pos
        indices = np.random.permutation(size)
        batches = []
        for start in range(0, size, batch_size):
            idx = indices[start : start + batch_size]
            adv = self.advantages[idx]
            adv = (adv - adv.mean()) / (adv.std() + 1e-8)
            batches.append({
                "obs": torch.FloatTensor(self.obs[idx]).to(device),
                "actions": torch.LongTensor(self.actions[idx]).to(device),
                "log_probs": torch.FloatTensor(self.log_probs[idx]).to(device),
                "advantages": torch.FloatTensor(adv).to(device),
                "returns": torch.FloatTensor(self.returns[idx]).to(device),
            })
        return batches

    def reset(self) -> None:
        self.pos = 0
        self.full = False


class PPOAgent:
    """
    PPO agent for SDN routing with clipped surrogate objective.

    Uses a shared actor-critic network with per-flow policy heads,
    enabling joint optimization over all routing decisions.
    """

    def __init__(
        self,
        obs_dim: int,
        action_dims: list[int],
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_range: float = 0.2,
        value_coeff: float = 0.5,
        entropy_coeff: float = 0.01,
        max_grad_norm: float = 0.5,
        device: str | None = None,
    ) -> None:
        self.obs_dim = obs_dim
        self.action_dims = action_dims
        self.batch_size = batch_size
        self.n_epochs = n_epochs
        self.clip_range = clip_range
        self.value_coeff = value_coeff
        self.entropy_coeff = entropy_coeff
        self.max_grad_norm = max_grad_norm
        self.total_steps = 0

        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self.policy = ActorCriticNetwork(obs_dim, action_dims).to(self.device)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=learning_rate, eps=1e-5)
        self.scheduler = optim.lr_scheduler.LinearLR(
            self.optimizer, start_factor=1.0, end_factor=0.1, total_iters=500
        )

        self.rollout_buffer = RolloutBuffer(n_steps, obs_dim, len(action_dims), gamma, gae_lambda)

        self.policy_losses: list[float] = []
        self.value_losses: list[float] = []
        self.entropy_losses: list[float] = []

    @torch.no_grad()
    def select_action(
        self, obs: np.ndarray, deterministic: bool = False
    ) -> tuple[np.ndarray, float, float]:
        """Select action, returning (action, log_prob, value)."""
        obs_t = torch.FloatTensor(obs).unsqueeze(0).to(self.device)
        action_t, log_prob_t, _, value_t = self.policy.get_action(obs_t)

        if deterministic:
            # Greedy: pick argmax of each head
            logits_list, value_t = self.policy(obs_t)
            action_t = torch.stack([l.argmax(dim=-1) for l in logits_list], dim=-1)

        action = action_t.squeeze(0).cpu().numpy()
        log_prob = float(log_prob_t.item())
        value = float(value_t.item())
        return action, log_prob, value

    def store_transition(
        self,
        obs: np.ndarray,
        action: np.ndarray,
        reward: float,
        value: float,
        log_prob: float,
        done: bool,
    ) -> None:
        self.rollout_buffer.add(obs, action, reward, value, log_prob, done)

    @torch.no_grad()
    def compute_last_value(self, obs: np.ndarray) -> float:
        obs_t = torch.FloatTensor(obs).unsqueeze(0).to(self.device)
        _, value_t = self.policy(obs_t)
        return float(value_t.item())

    def update(self, last_value: float, last_done: bool) -> dict[str, float]:
        """Run PPO update epochs over the collected rollout."""
        self.rollout_buffer.compute_returns_and_advantages(last_value, last_done)

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        num_batches = 0

        for _ in range(self.n_epochs):
            batches = self.rollout_buffer.get_batches(self.batch_size, self.device)
            for batch in batches:
                obs = batch["obs"]
                actions = batch["actions"]
                old_log_probs = batch["log_probs"]
                advantages = batch["advantages"]
                returns = batch["returns"]

                _, new_log_probs, entropy, values = self.policy.get_action(obs, actions)

                # Ratio for importance sampling
                ratio = torch.exp(new_log_probs - old_log_probs)
                clipped_ratio = torch.clamp(ratio, 1.0 - self.clip_range, 1.0 + self.clip_range)

                policy_loss = -torch.min(
                    ratio * advantages, clipped_ratio * advantages
                ).mean()

                value_loss = nn.functional.mse_loss(values, returns)

                loss = policy_loss + self.value_coeff * value_loss - self.entropy_coeff * entropy.mean()

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
                self.optimizer.step()

                total_policy_loss += float(policy_loss.item())
                total_value_loss += float(value_loss.item())
                total_entropy += float(entropy.mean().item())
                num_batches += 1

        self.scheduler.step()
        self.rollout_buffer.reset()
        self.total_steps += 1

        n = max(num_batches, 1)
        metrics = {
            "policy_loss": total_policy_loss / n,
            "value_loss": total_value_loss / n,
            "entropy": total_entropy / n,
        }
        self.policy_losses.append(metrics["policy_loss"])
        self.value_losses.append(metrics["value_loss"])
        return metrics

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "policy_state_dict": self.policy.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "total_steps": self.total_steps,
            },
            path,
        )

    def load(self, path: str | Path) -> None:
        path = Path(path)
        checkpoint = torch.load(path, map_location=self.device)
        self.policy.load_state_dict(checkpoint["policy_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.total_steps = checkpoint.get("total_steps", 0)

    @property
    def hyperparameters(self) -> dict[str, Any]:
        return {
            "obs_dim": self.obs_dim,
            "action_dims": self.action_dims,
            "clip_range": self.clip_range,
            "n_epochs": self.n_epochs,
            "batch_size": self.batch_size,
            "device": str(self.device),
        }
