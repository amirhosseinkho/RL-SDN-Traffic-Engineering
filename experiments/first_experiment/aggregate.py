#!/usr/bin/env python3
"""Aggregate per-seed evaluation JSON files (from evaluate.py) into a Markdown table.

Each file holds one training seed; values are averaged over that seed's evaluation
episodes. The table reports mean ± sample std across seeds.

Usage:
    python experiments/first_experiment/aggregate.py experiments/first_experiment/eval_seed_*.json
"""
import json
import statistics
import sys
from pathlib import Path

METRICS = [
    ("avg_reward", "Episode reward", "{:.2f}"),
    ("avg_latency_ms", "Avg link latency (ms)", "{:.2f}"),
    ("avg_throughput_pct", "Avg link utilization (%)", "{:.1f}"),
    ("avg_packet_loss", "Avg link loss (%)", "{:.3f}"),
]
ORDER = ["shortest_path", "ecmp", "random", "dqn", "ppo"]


def fmt(values: list[float], pattern: str) -> str:
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{pattern.format(mean)} ± {pattern.format(std)}"


def main() -> None:
    files = [Path(p) for p in sys.argv[1:]]
    if not files:
        sys.exit("usage: aggregate.py eval_seed_*.json")
    runs = [json.loads(f.read_text()) for f in files]

    per_agent: dict[str, dict[str, list[float]]] = {}
    for run in runs:
        for agent, res in run["results"].items():
            for key, _, _ in METRICS:
                per_agent.setdefault(agent, {}).setdefault(key, []).append(res[key])

    print(f"Seeds: {len(runs)} · evaluation episodes per seed: {runs[0]['episodes']} · "
          f"evaluation seed: {runs[0].get('seed')}\n")
    print("| Agent | " + " | ".join(label for _, label, _ in METRICS) + " |")
    print("|---|" + "---|" * len(METRICS))
    for agent in sorted(per_agent, key=lambda a: ORDER.index(a) if a in ORDER else len(ORDER)):
        cells = [fmt(per_agent[agent][key], pattern) for key, _, pattern in METRICS]
        print(f"| {agent} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
