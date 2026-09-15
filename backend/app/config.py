"""Central configuration for the RL-SDN platform."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "RL-SDN Traffic Engineering"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://sdn:sdn_password@localhost:5432/sdn_db"
    )

    # Ryu Controller
    ryu_host: str = "127.0.0.1"
    ryu_port: int = 8080
    ryu_wsapi_port: int = 8081
    openflow_port: int = 6653

    # Redis (for pub/sub and caching)
    redis_url: str = "redis://localhost:6379/0"

    # RL Training
    rl_models_dir: Path = ROOT_DIR / "models"
    rl_logs_dir: Path = ROOT_DIR / "logs"
    rl_checkpoints_dir: Path = ROOT_DIR / "models" / "checkpoints"

    # Training hyperparameters
    dqn_learning_rate: float = 1e-4
    dqn_buffer_size: int = 100_000
    dqn_batch_size: int = 64
    dqn_gamma: float = 0.99
    dqn_tau: float = 0.005
    dqn_epsilon_start: float = 1.0
    dqn_epsilon_end: float = 0.05
    dqn_epsilon_decay: int = 50_000
    dqn_target_update_freq: int = 1_000
    dqn_total_timesteps: int = 500_000

    ppo_learning_rate: float = 3e-4
    ppo_n_steps: int = 2048
    ppo_batch_size: int = 64
    ppo_n_epochs: int = 10
    ppo_gamma: float = 0.99
    ppo_gae_lambda: float = 0.95
    ppo_clip_range: float = 0.2
    ppo_total_timesteps: int = 1_000_000

    # Monitoring
    metrics_collection_interval: float = 1.0  # seconds
    websocket_broadcast_interval: float = 0.5

    # Topology defaults
    default_link_bandwidth: int = 100  # Mbps
    default_link_latency: int = 5  # ms
    default_link_loss: float = 0.0  # %

    # AI Copilot
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    copilot_enabled: bool = True

    @field_validator("rl_models_dir", "rl_logs_dir", "rl_checkpoints_dir", mode="before")
    @classmethod
    def create_dirs(cls, v: Any) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
