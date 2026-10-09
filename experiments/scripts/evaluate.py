#!/usr/bin/env python3
"""
Comparative evaluation script: DQN vs PPO vs Shortest Path vs ECMP.

Usage:
    python experiments/scripts/evaluate.py \
        --topology spine_leaf \
        --dqn-model models/dqn_model.pt \
        --ppo-model models/ppo_model.pt \
        --episodes 20 \
        --output results/comparison.json
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.database.models import AgentType, TopologyType
from app.database.schemas import TopologyConfig
from app.rl.agents.dqn_agent import DQNAgent
from app.rl.agents.ppo_agent import PPOAgent
from app.rl.environment import SDNRoutingEnv
from app.simulation.evaluator import Evaluator
from app.topology.generator import TopologyGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--topology", default="spine_leaf")
    p.add_argument("--num-switches", type=int, default=6)
    p.add_argument("--num-hosts", type=int, default=8)
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--dqn-model", type=Path, default=Path("models/dqn_model.pt"))
    p.add_argument("--ppo-model", type=Path, default=Path("models/ppo_model.pt"))
    p.add_argument("--episodes", type=int, default=20)
    p.add_argument("--output", type=Path, default=Path("results/comparison.json"))
    p.add_argument("--seed", type=int, default=42, help="Seed for the evaluation traffic")
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    cfg = TopologyConfig(
        topology_type=TopologyType(args.topology),
        num_switches=args.num_switches,
        num_hosts=args.num_hosts,
        bandwidth=100.0,
        latency=5.0,
        loss=0.0,
        k=args.k,
        name="eval-topology",
    )
    topo_def = TopologyGenerator().generate(cfg)

    env_probe = SDNRoutingEnv(topo_def)
    obs_dim = env_probe.observation_space.shape[0]
    action_dims = list(env_probe.action_space.nvec)

    # Load RL agents
    agents: dict[AgentType, object] = {}

    if args.dqn_model.exists():
        dqn = DQNAgent(obs_dim=obs_dim, action_dims=action_dims)
        dqn.load(args.dqn_model)
        agents[AgentType.DQN] = dqn
        logger.info("Loaded DQN model from %s", args.dqn_model)
    else:
        logger.warning("DQN model not found at %s — skipping", args.dqn_model)

    if args.ppo_model.exists():
        ppo = PPOAgent(obs_dim=obs_dim, action_dims=action_dims)
        ppo.load(args.ppo_model)
        agents[AgentType.PPO] = ppo
        logger.info("Loaded PPO model from %s", args.ppo_model)
    else:
        logger.warning("PPO model not found at %s — skipping", args.ppo_model)

    evaluator = Evaluator(topo_def, seed=args.seed)
    logger.info("Evaluating %d agents over %d episodes each...", len(agents) + 2, args.episodes)

    results = await evaluator.compare_all(agents, num_episodes=args.episodes)
    improvements = evaluator.compute_improvements(results)

    # Print table
    print("\n" + "=" * 70)
    print(f"{'Agent':<20} {'Reward':>10} {'Latency(ms)':>12} {'Throughput%':>12} {'Loss%':>8}")
    print("=" * 70)
    for agent_type, result in results.items():
        print(
            f"{agent_type.value:<20} "
            f"{result.avg_reward:>10.4f} "
            f"{result.avg_latency_ms:>12.2f} "
            f"{result.avg_throughput_pct:>12.1f} "
            f"{result.avg_packet_loss:>8.4f}"
        )
    print("=" * 70)

    print("\nImprovements over Shortest Path:")
    for agent, impr in improvements.items():
        print(f"  {agent}: latency -{impr['latency_reduction_pct']:.1f}% | "
              f"throughput +{impr['throughput_gain_pct']:.1f}%")

    # Save JSON
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "topology": cfg.model_dump(),
        "episodes": args.episodes,
        "seed": args.seed,
        "results": {
            agent_type.value: {
                "avg_reward": result.avg_reward,
                "avg_latency_ms": result.avg_latency_ms,
                "avg_throughput_pct": result.avg_throughput_pct,
                "avg_packet_loss": result.avg_packet_loss,
                "convergence_time_s": result.convergence_time_s,
            }
            for agent_type, result in results.items()
        },
        "improvements": improvements,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Results saved to %s", args.output)


if __name__ == "__main__":
    asyncio.run(main())
