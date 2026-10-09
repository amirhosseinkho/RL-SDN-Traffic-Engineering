#!/usr/bin/env python3
"""
Standalone DQN training script.

Usage:
    python experiments/scripts/train_dqn.py \
        --topology spine_leaf \
        --num-switches 6 \
        --num-hosts 8 \
        --timesteps 500000 \
        --lr 1e-4
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.database.models import TopologyType
from app.database.schemas import TopologyConfig
from app.rl.trainer import build_dqn_trainer
from app.topology.generator import TopologyGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train DQN agent for SDN routing")
    p.add_argument("--topology", default="spine_leaf", choices=["linear", "tree", "fat_tree", "spine_leaf"])
    p.add_argument("--num-switches", type=int, default=6)
    p.add_argument("--num-hosts", type=int, default=8)
    p.add_argument("--bandwidth", type=float, default=100.0)
    p.add_argument("--latency", type=float, default=5.0)
    p.add_argument("--timesteps", type=int, default=500_000)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--buffer-size", type=int, default=100_000)
    p.add_argument("--epsilon-decay", type=int, default=50_000)
    p.add_argument("--output-dir", type=Path, default=Path("models"))
    p.add_argument("--seed", type=int, default=None, help="Seed for agent, exploration and traffic")
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    cfg = TopologyConfig(
        topology_type=TopologyType(args.topology),
        num_switches=args.num_switches,
        num_hosts=args.num_hosts,
        bandwidth=args.bandwidth,
        latency=args.latency,
        loss=0.0,
        name=f"experiment-{args.topology}",
    )

    gen = TopologyGenerator()
    topo_def = gen.generate(cfg)
    logger.info(
        "Topology: %s | %d switches | %d hosts",
        args.topology,
        len(topo_def.switches),
        len(topo_def.hosts),
    )

    hyperparams = {
        "learning_rate": args.lr,
        "buffer_size": args.buffer_size,
        "batch_size": args.batch_size,
        "gamma": args.gamma,
        "epsilon_decay": args.epsilon_decay,
    }

    env, agent, trainer = build_dqn_trainer(
        topo_def,
        total_timesteps=args.timesteps,
        hyperparams=hyperparams,
        session_id="cli-session",
        seed=args.seed,
        models_dir=args.output_dir,
    )

    logger.info("Starting DQN training for %d timesteps...", args.timesteps)
    metrics = await trainer.train()

    recent = metrics.get_recent(100)
    logger.info("=== Training Complete ===")
    logger.info("Mean Reward (last 100 eps): %.4f", recent["mean_reward"])
    logger.info("Mean Latency: %.2f ms", recent["mean_latency_ms"])
    logger.info("Mean Throughput: %.2f%%", recent["mean_throughput"])
    logger.info("Mean Packet Loss: %.4f%%", recent["mean_packet_loss"])


if __name__ == "__main__":
    asyncio.run(main())
