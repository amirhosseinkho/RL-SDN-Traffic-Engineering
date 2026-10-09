#!/usr/bin/env python3
"""
Standalone PPO training script.

Usage:
    python experiments/scripts/train_ppo.py \
        --topology fat_tree \
        --k 4 \
        --timesteps 1000000
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.database.models import TopologyType
from app.database.schemas import TopologyConfig
from app.rl.trainer import build_ppo_trainer
from app.topology.generator import TopologyGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train PPO agent for SDN routing")
    p.add_argument("--topology", default="fat_tree", choices=["linear", "tree", "fat_tree", "spine_leaf"])
    p.add_argument("--k", type=int, default=4, help="Fat-tree k value")
    p.add_argument("--num-switches", type=int, default=20)
    p.add_argument("--num-hosts", type=int, default=16)
    p.add_argument("--bandwidth", type=float, default=100.0)
    p.add_argument("--timesteps", type=int, default=1_000_000)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--n-steps", type=int, default=2048)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--n-epochs", type=int, default=10)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--clip-range", type=float, default=0.2)
    p.add_argument("--output-dir", type=Path, default=Path("models"))
    p.add_argument("--seed", type=int, default=None, help="Seed for agent, sampling and traffic")
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    cfg = TopologyConfig(
        topology_type=TopologyType(args.topology),
        num_switches=args.num_switches,
        num_hosts=args.num_hosts,
        bandwidth=args.bandwidth,
        latency=5.0,
        loss=0.0,
        k=args.k,
        name=f"ppo-{args.topology}",
    )

    gen = TopologyGenerator()
    topo_def = gen.generate(cfg)
    logger.info("Topology: %s | %d switches | %d hosts", args.topology, len(topo_def.switches), len(topo_def.hosts))

    hyperparams = {
        "learning_rate": args.lr,
        "n_steps": args.n_steps,
        "batch_size": args.batch_size,
        "n_epochs": args.n_epochs,
        "gamma": args.gamma,
        "clip_range": args.clip_range,
    }

    env, agent, trainer = build_ppo_trainer(
        topo_def,
        total_timesteps=args.timesteps,
        hyperparams=hyperparams,
        session_id="ppo-cli",
        seed=args.seed,
        models_dir=args.output_dir,
    )

    logger.info("Starting PPO training for %d timesteps...", args.timesteps)
    metrics = await trainer.train()

    recent = metrics.get_recent(50)
    logger.info("=== Training Complete ===")
    logger.info("Mean Reward: %.4f ± %.4f", recent["mean_reward"], recent["std_reward"])
    logger.info("Mean Latency: %.2f ms", recent["mean_latency_ms"])
    logger.info("Mean Throughput: %.2f%%", recent["mean_throughput"])


if __name__ == "__main__":
    asyncio.run(main())
