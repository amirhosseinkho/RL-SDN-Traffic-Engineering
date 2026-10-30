"""Run the same policies in the simulator on the same traffic as the emulation runs.

    python -m emulation.sim_matched --models-dir ~/second_experiment_models \
        --out experiments/mininet_experiment/sim_matched.json

For every traffic seed: SDNRoutingEnv.reset(seed), then `epochs` steps, policies observing the
simulator's own state. This is the simulator's ranking on exactly the traffic the emulation
carried (first 20 steps), next to the second experiment's 20 x 200-step evaluation. Route churn
is counted with the same rule-change count the controller uses.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from app.rl.environment import SDNRoutingEnv

from emulation.churn import rule_changes
from emulation.mapping import build_mapping, experiment_topology
from emulation.policies import POLICIES, make_policy
from emulation.traffic import FlowSpec


def run_one(policy_name: str, traffic_seed: int, model: Path | None, epochs: int) -> dict[str, Any]:
    topo = experiment_topology()
    mapping = build_mapping(topo, 0.05)
    env = SDNRoutingEnv(topo, seed=traffic_seed)
    obs, _ = env.reset(seed=traffic_seed)
    flows = [FlowSpec(i, f.src_host, f.dst_host, mapping.hosts[f.src_host].ip, mapping.hosts[f.dst_host].ip)
             for i, f in enumerate(env.sim_state.flow_demands)]
    policy = make_policy(policy_name, env, [f.five_tuple for f in flows], traffic_seed, model)
    paths = {i: list(f.active_path) for i, f in enumerate(env.sim_state.flow_demands)}
    delivered, latency, churn = [], [], []
    for _ in range(epochs):
        action = policy.select(env, obs)
        changes = 0
        for i, f in enumerate(env.sim_state.flow_demands):
            new = env._get_paths(f.src_host, f.dst_host)[int(action[i]) % env.max_paths]
            if new != paths[i]:
                changes += rule_changes(paths[i], new, mapping)
                paths[i] = new
        obs, _, _, _, info = env.step(action)
        delivered.append(100.0 * info["delivered_ratio"])
        latency.append(info["mean_path_latency_ms"])
        churn.append(changes)
    return {
        "policy": policy_name,
        "traffic_seed": traffic_seed,
        "model": str(model) if model else None,
        "delivered_pct": float(np.mean(delivered)),
        "flow_latency_ms": float(np.mean(latency)),
        "rule_changes_per_epoch": float(np.mean(churn)),
        "per_epoch_delivered_pct": delivered,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir", type=Path, required=True)
    p.add_argument("--traffic-seeds", type=int, nargs="+", default=[1000, 1001, 1002])
    p.add_argument("--model-seeds", type=int, nargs="+", default=[0, 1, 2])
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    runs = []
    for seed in args.traffic_seeds:
        for name in POLICIES:
            if name in ("dqn", "ppo"):
                for m in args.model_seeds:
                    runs.append(run_one(name, seed, args.models_dir / f"seed_{m}" / f"{name}_model.pt", args.epochs))
            else:
                runs.append(run_one(name, seed, None, args.epochs))
    args.out.write_text(json.dumps({"epochs": args.epochs, "runs": runs}, indent=2))
    for r in runs:
        print(f"{r['policy']:<14} seed {r['traffic_seed']} {Path(r['model']).parent.name if r['model'] else '':<7} "
              f"delivered {r['delivered_pct']:5.1f}%  latency {r['flow_latency_ms']:5.1f} ms  churn {r['rule_changes_per_epoch']:5.1f}")


if __name__ == "__main__":
    main()
