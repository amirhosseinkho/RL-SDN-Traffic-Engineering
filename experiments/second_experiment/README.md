# Second Experiment: Per-Flow Reward (simulation)

Run on 2026-10-09/10 with commit `572c111` (branch `cleanup/honest-readme`). Everything below happens
inside `SDNRoutingEnv`, the NetworkX simulation. No real or emulated network is involved.

## What changed since the first experiment

The [first experiment](../first_experiment/README.md) showed two problems, both fixed in `572c111`:

1. **Reward.** The old reward paid for average link utilization, so random routing scored as high as
   the trained agents. The new reward is
   `r = delivered_ratio − 0.1 · (mean_stretch − 1)`: the share of total demand that gets through,
   minus a penalty for flow latency above the uncongested shortest-path latency
   (definition in [docs/architecture.md](../../docs/architecture.md#reward-function)).
2. **Traffic.** Demand grew without bound during each episode (from about 0.5 Gbps to about 1 Tbps
   in 200 steps). Demand now fluctuates around each flow's base demand.

The evaluation also adds a congestion-aware heuristic, **least-loaded**: flows are routed one by one,
largest first, each on the candidate path whose most loaded link would be least loaded.

## Setup

Same as the first experiment:

| | |
|---|---|
| Topology | spine-leaf, 2 spine + 4 leaf switches, 8 hosts; 200 Mbps leaf–spine links, 5 ms |
| Agents | DQN and PPO with the default hyperparameters ([docs/training.md](../../docs/training.md)) |
| Training | 300,000 steps per run, seeds 0, 1, 2 for each agent |
| Baselines | shortest path, ECMP (round-robin over each flow's 4 precomputed paths), random path per flow, least-loaded |
| Evaluation | 20 episodes × 200 steps per trained model; evaluation traffic seed 1000, different from all training seeds; every policy sees the same traffic |
| Metrics | per episode, averaged over all steps: reward (summed over the episode), share of demand delivered, demand-weighted flow path latency, mean link utilization |
| Hardware | CPU only (WSL2), 6 runs in parallel; wall time about 2 h 45 min, while other jobs shared the CPU |

Reproduce from the repository root (WSL/Linux, backend requirements installed):

```bash
bash experiments/second_experiment/run.sh
```

Raw per-seed results are in `eval_seed_0.json`, `eval_seed_1.json` and `eval_seed_2.json`. The
table below is `summary.md`, produced by `experiments/scripts/aggregate.py`.

## Results

Mean ± sample standard deviation across the 3 training seeds. The baselines do not depend on the
training seed, so their standard deviation is 0. The random baseline is one realization of random
routing (it uses the evaluation seed).

| Agent | Episode reward | Delivered demand (%) | Mean flow latency (ms) | Avg link utilization (%) |
|---|---|---|---|---|
| shortest_path | 79.9 ± 0.0 | 63.1 ± 0.0 | 32.27 ± 0.00 | 40.5 ± 0.0 |
| ecmp | 31.5 ± 0.0 | 56.0 ± 0.0 | 49.38 ± 0.00 | 56.1 ± 0.0 |
| random | 58.6 ± 0.0 | 65.5 ± 0.0 | 45.43 ± 0.00 | 67.7 ± 0.0 |
| least_loaded | 144.3 ± 0.0 | 88.4 ± 0.0 | 25.46 ± 0.00 | 59.3 ± 0.0 |
| dqn | 124.6 ± 1.7 | 80.8 ± 0.7 | 27.71 ± 0.11 | 55.3 ± 0.2 |
| ppo | 106.9 ± 9.2 | 75.1 ± 1.9 | 30.89 ± 2.70 | 55.9 ± 3.9 |

Per seed (reward / delivered %): DQN 125.8 / 81.4, 125.3 / 81.2, 122.7 / 80.0;
PPO 107.7 / 75.6, 97.3 / 73.0, 115.6 / 76.8.

Training curves (from the training logs, not committed):

- DQN: the mean reward over the last 100 episodes rose from 63.4–78.1 at step 20,000 (ε = 0.62) to
  117.7–123.3 at step 300,000.
- PPO: the reward per 2,048-step training episode rose from 783.5–800.5 at step 10,240 to a mean of
  938.6–1144.0 over the last 50 episodes, with a large spread between episodes (std 445–507).

## What this shows

1. **The new reward can be learned, and it ranks policies sensibly.** Random routing now scores below
   shortest path (58.6 vs 79.9), and both agents improve on their training reward.
2. **Both agents beat shortest path, ECMP and random routing on every seed.** DQN delivers
   80.8% ± 0.7% of demand vs 63.1% for shortest path, with lower flow latency (27.71 vs 32.27 ms).
   PPO is lower and much more variable across seeds.
3. **Neither agent reaches the least-loaded heuristic** (88.4% delivered, 25.46 ms). A simple greedy
   rule that knows each flow's candidate paths still does better than both learned policies.

## Limitations

- Simulation only; the link sharing, queueing and latency model is a hand-written approximation, and
  host access links are not modelled.
- The observation does not say which hosts a flow connects or which links its candidate paths use;
  the least-loaded heuristic has this information and the agents do not. This is a likely reason the
  agents fall short of it.
- One small topology, one traffic model, default hyperparameters, 300,000 steps, 3 seeds.
- PPO trains on 2,048-step episodes but is evaluated on 200-step episodes.

## Next steps suggested by these results

- Add per-flow, per-candidate-path features to the observation (e.g. the load on each path's
  bottleneck link) and check whether the agents then reach or beat least-loaded.
- Tune hyperparameters (PPO in particular) only after that, with more seeds.
- Repeat on larger topologies (fat-tree) and other traffic patterns.
