"""Training orchestrator for DQN and PPO agents."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

import numpy as np

from app.config import get_settings
from app.database.models import AgentType
from app.rl.agents.dqn_agent import DQNAgent
from app.rl.agents.ppo_agent import PPOAgent
from app.rl.environment import SDNRoutingEnv
from app.topology.generator import TopologyDefinition

logger = logging.getLogger(__name__)
settings = get_settings()


class TrainingMetrics:
    def __init__(self) -> None:
        self.episode_rewards: list[float] = []
        self.episode_lengths: list[int] = []
        self.avg_latencies: list[float] = []
        self.avg_throughputs: list[float] = []
        self.avg_losses: list[float] = []
        self.avg_utilizations: list[float] = []
        self.policy_losses: list[float] = []
        self.value_losses: list[float] = []
        self.epsilons: list[float] = []
        self.timestamps: list[float] = []

    def record_episode(
        self,
        reward: float,
        length: int,
        info: dict[str, Any],
        train_info: dict[str, Any] | None = None,
    ) -> None:
        self.episode_rewards.append(reward)
        self.episode_lengths.append(length)
        self.avg_latencies.append(info.get("avg_latency_ms", 0.0))
        self.avg_throughputs.append(info.get("avg_utilization", 0.0) * 100.0)
        self.avg_losses.append(info.get("avg_packet_loss", 0.0))
        self.avg_utilizations.append(info.get("avg_utilization", 0.0))
        self.timestamps.append(time.time())
        if train_info:
            self.policy_losses.append(train_info.get("policy_loss", train_info.get("loss", 0.0)))
            self.value_losses.append(train_info.get("value_loss", 0.0))
            self.epsilons.append(train_info.get("epsilon", 0.0))

    def get_recent(self, n: int = 100) -> dict[str, float]:
        rewards = self.episode_rewards[-n:]
        return {
            "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
            "std_reward": float(np.std(rewards)) if rewards else 0.0,
            "mean_latency_ms": float(np.mean(self.avg_latencies[-n:])) if self.avg_latencies else 0.0,
            "mean_throughput": float(np.mean(self.avg_throughputs[-n:])) if self.avg_throughputs else 0.0,
            "mean_packet_loss": float(np.mean(self.avg_losses[-n:])) if self.avg_losses else 0.0,
            "mean_utilization": float(np.mean(self.avg_utilizations[-n:])) if self.avg_utilizations else 0.0,
        }


class DQNTrainer:
    """Trains the DQN agent on the SDN routing environment."""

    def __init__(
        self,
        env: SDNRoutingEnv,
        agent: DQNAgent,
        total_timesteps: int = 500_000,
        learning_starts: int = 10_000,
        train_freq: int = 4,
        checkpoint_freq: int = 50_000,
        checkpoint_dir: Path | None = None,
        session_id: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.env = env
        self.agent = agent
        self.total_timesteps = total_timesteps
        self.learning_starts = learning_starts
        self.train_freq = train_freq
        self.checkpoint_freq = checkpoint_freq
        self.checkpoint_dir = checkpoint_dir or settings.rl_checkpoints_dir
        self.session_id = session_id
        self.progress_callback = progress_callback
        self.metrics = TrainingMetrics()
        self._stop_flag = False

    def stop(self) -> None:
        self._stop_flag = True

    async def train(self) -> TrainingMetrics:
        """Run DQN training loop."""
        obs, _ = self.env.reset()
        episode_reward = 0.0
        episode_steps = 0
        episode_num = 0
        last_info: dict[str, Any] = {}

        logger.info(
            "Starting DQN training | steps=%d | session=%s",
            self.total_timesteps,
            self.session_id,
        )

        for step in range(self.total_timesteps):
            if self._stop_flag:
                logger.info("DQN training stopped at step %d", step)
                break

            # Select action
            action = self.agent.select_action(obs)
            next_obs, reward, terminated, truncated, info = self.env.step(action)

            # Store transition
            self.agent.replay_buffer.add(obs, action, reward, next_obs, terminated or truncated)

            obs = next_obs
            episode_reward += reward
            episode_steps += 1
            last_info = info

            # Train
            train_info = None
            if step >= self.learning_starts and step % self.train_freq == 0:
                train_info = self.agent.update()

            # Episode end
            if terminated or truncated:
                self.metrics.record_episode(episode_reward, episode_steps, last_info, train_info)
                episode_num += 1

                if episode_num % 10 == 0:
                    recent = self.metrics.get_recent()
                    logger.info(
                        "DQN Ep %d | Step %d/%d | Reward: %.3f | Latency: %.1fms | ε: %.3f",
                        episode_num,
                        step,
                        self.total_timesteps,
                        recent["mean_reward"],
                        recent["mean_latency_ms"],
                        self.agent.epsilon,
                    )
                    if self.progress_callback:
                        self.progress_callback(
                            {
                                "step": step,
                                "episode": episode_num,
                                "session_id": self.session_id,
                                **recent,
                                "epsilon": self.agent.epsilon,
                            }
                        )

                obs, _ = self.env.reset()
                episode_reward = 0.0
                episode_steps = 0

            # Checkpoint
            if step > 0 and step % self.checkpoint_freq == 0:
                ckpt_path = self.checkpoint_dir / f"dqn_step_{step}.pt"
                self.agent.save(ckpt_path)
                logger.info("DQN checkpoint saved: %s", ckpt_path)

            # Yield control so async tasks can run
            if step % 1000 == 0:
                await asyncio.sleep(0)

        # Final save
        final_path = settings.rl_models_dir / "dqn_model.pt"
        self.agent.save(final_path)
        logger.info("DQN training complete. Model saved to %s", final_path)
        return self.metrics


class PPOTrainer:
    """Trains the PPO agent on the SDN routing environment."""

    def __init__(
        self,
        env: SDNRoutingEnv,
        agent: PPOAgent,
        total_timesteps: int = 1_000_000,
        n_steps: int = 2048,
        checkpoint_freq: int = 100_000,
        checkpoint_dir: Path | None = None,
        session_id: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.env = env
        self.agent = agent
        self.total_timesteps = total_timesteps
        self.n_steps = n_steps
        self.checkpoint_freq = checkpoint_freq
        self.checkpoint_dir = checkpoint_dir or settings.rl_checkpoints_dir
        self.session_id = session_id
        self.progress_callback = progress_callback
        self.metrics = TrainingMetrics()
        self._stop_flag = False

    def stop(self) -> None:
        self._stop_flag = True

    async def train(self) -> TrainingMetrics:
        """Run PPO training loop."""
        obs, _ = self.env.reset()
        episode_reward = 0.0
        episode_steps = 0
        episode_num = 0
        total_steps = 0
        last_info: dict[str, Any] = {}

        logger.info(
            "Starting PPO training | steps=%d | session=%s",
            self.total_timesteps,
            self.session_id,
        )

        while total_steps < self.total_timesteps and not self._stop_flag:
            # Collect rollout
            for _ in range(self.n_steps):
                action, log_prob, value = self.agent.select_action(obs)
                next_obs, reward, terminated, truncated, info = self.env.step(action)

                self.agent.store_transition(obs, action, reward, value, log_prob, terminated or truncated)

                obs = next_obs
                episode_reward += reward
                episode_steps += 1
                total_steps += 1
                last_info = info

                if terminated or truncated:
                    self.metrics.record_episode(episode_reward, episode_steps, last_info)
                    episode_num += 1
                    obs, _ = self.env.reset()
                    episode_reward = 0.0
                    episode_steps = 0

                if total_steps >= self.total_timesteps:
                    break

            # Update
            last_value = self.agent.compute_last_value(obs)
            train_info = self.agent.update(last_value, False)

            if self.metrics.episode_rewards:
                self.metrics.policy_losses.append(train_info["policy_loss"])
                self.metrics.value_losses.append(train_info["value_loss"])

            if episode_num % 5 == 0 and episode_num > 0:
                recent = self.metrics.get_recent()
                logger.info(
                    "PPO Ep %d | Step %d/%d | Reward: %.3f | PolicyLoss: %.4f | ValueLoss: %.4f",
                    episode_num,
                    total_steps,
                    self.total_timesteps,
                    recent["mean_reward"],
                    train_info["policy_loss"],
                    train_info["value_loss"],
                )
                if self.progress_callback:
                    self.progress_callback(
                        {
                            "step": total_steps,
                            "episode": episode_num,
                            "session_id": self.session_id,
                            **recent,
                            **train_info,
                        }
                    )

            # Checkpoint
            if total_steps > 0 and total_steps % self.checkpoint_freq < self.n_steps:
                ckpt_path = self.checkpoint_dir / f"ppo_step_{total_steps}.pt"
                self.agent.save(ckpt_path)
                logger.info("PPO checkpoint saved: %s", ckpt_path)

            await asyncio.sleep(0)

        # Final save
        final_path = settings.rl_models_dir / "ppo_model.pt"
        self.agent.save(final_path)
        logger.info("PPO training complete. Model saved to %s", final_path)
        return self.metrics


def build_dqn_trainer(
    topology: TopologyDefinition,
    total_timesteps: int = 500_000,
    hyperparams: dict[str, Any] | None = None,
    session_id: str | None = None,
    progress_callback: Callable | None = None,
) -> tuple[SDNRoutingEnv, DQNAgent, DQNTrainer]:
    hp = hyperparams or {}
    env = SDNRoutingEnv(topology, max_steps=200)
    obs_dim = env.observation_space.shape[0]
    action_dims = list(env.action_space.nvec)

    agent = DQNAgent(
        obs_dim=obs_dim,
        action_dims=action_dims,
        learning_rate=hp.get("learning_rate", settings.dqn_learning_rate),
        buffer_size=hp.get("buffer_size", settings.dqn_buffer_size),
        batch_size=hp.get("batch_size", settings.dqn_batch_size),
        gamma=hp.get("gamma", settings.dqn_gamma),
        tau=hp.get("tau", settings.dqn_tau),
        epsilon_start=hp.get("epsilon_start", settings.dqn_epsilon_start),
        epsilon_end=hp.get("epsilon_end", settings.dqn_epsilon_end),
        epsilon_decay=hp.get("epsilon_decay", settings.dqn_epsilon_decay),
        target_update_freq=hp.get("target_update_freq", settings.dqn_target_update_freq),
    )

    trainer = DQNTrainer(
        env=env,
        agent=agent,
        total_timesteps=total_timesteps,
        session_id=session_id,
        progress_callback=progress_callback,
    )
    return env, agent, trainer


def build_ppo_trainer(
    topology: TopologyDefinition,
    total_timesteps: int = 1_000_000,
    hyperparams: dict[str, Any] | None = None,
    session_id: str | None = None,
    progress_callback: Callable | None = None,
) -> tuple[SDNRoutingEnv, PPOAgent, PPOTrainer]:
    hp = hyperparams or {}
    n_steps = hp.get("n_steps", settings.ppo_n_steps)
    env = SDNRoutingEnv(topology, max_steps=n_steps)
    obs_dim = env.observation_space.shape[0]
    action_dims = list(env.action_space.nvec)

    agent = PPOAgent(
        obs_dim=obs_dim,
        action_dims=action_dims,
        learning_rate=hp.get("learning_rate", settings.ppo_learning_rate),
        n_steps=n_steps,
        batch_size=hp.get("batch_size", settings.ppo_batch_size),
        n_epochs=hp.get("n_epochs", settings.ppo_n_epochs),
        gamma=hp.get("gamma", settings.ppo_gamma),
        gae_lambda=hp.get("gae_lambda", settings.ppo_gae_lambda),
        clip_range=hp.get("clip_range", settings.ppo_clip_range),
    )

    trainer = PPOTrainer(
        env=env,
        agent=agent,
        total_timesteps=total_timesteps,
        n_steps=n_steps,
        session_id=session_id,
        progress_callback=progress_callback,
    )
    return env, agent, trainer
