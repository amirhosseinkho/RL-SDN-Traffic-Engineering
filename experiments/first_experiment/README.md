# First Experiment: DQN and PPO vs Baselines (simulation)

> **Superseded.** This experiment used the original utilization-based reward and a traffic model in
> which demand grew without bound during each episode (from about 0.5 Gbps to about 1 Tbps over 200
> steps, found afterwards), so the network was saturated for most of every episode. Both were fixed
> in commit `572c111`. See the [second experiment](../second_experiment/README.md). This page is
> kept as a record. To reproduce it, check out commit `e241345`.

Run on 2026-10-09 with commit `e241345` (branch `cleanup/honest-readme`). Everything below happens
inside `SDNRoutingEnv`, the NetworkX simulation. No real or emulated network is involved.

## Setup

| | |
|---|---|
| Topology | spine-leaf, 2 spine + 4 leaf switches, 8 hosts, 100 Mbps / 5 ms links |
| Agents | DQN and PPO with the default hyperparameters ([docs/training.md](../../docs/training.md)) |
| Training | 300,000 steps per run, seeds 0, 1, 2 for each agent |
| Baselines | shortest path, ECMP (round-robin over each flow's K = 4 precomputed paths), random path per flow |
| Evaluation | 20 episodes × 200 steps per trained model; evaluation traffic seed 1000, different from all training seeds; every policy sees the same traffic |
| Metrics | per episode, averaged over all steps: reward, mean link latency, mean link utilization, mean link loss; then averaged over episodes |
| Hardware | CPU only (WSL2, 12 cores), 6 runs in parallel; wall time about 75 minutes |

Reproduce from the repository root (WSL/Linux, backend requirements installed):

```bash
bash experiments/first_experiment/run.sh
```

Raw per-seed results are in `eval_seed_0.json`, `eval_seed_1.json` and `eval_seed_2.json`. The
table below is `summary.md`, produced by `aggregate.py`.

## Results

Mean ± sample standard deviation across the 3 training seeds. The baselines do not depend on the
training seed, so their standard deviation is 0. The random baseline uses the evaluation seed, so it
is one realization of random routing, not an average over many.

| Agent | Episode reward | Avg link latency (ms) | Avg link utilization (%) | Avg link loss (%) |
|---|---|---|---|---|
| shortest_path | 18.22 ± 0.00 | 12.11 ± 0.00 | 48.5 ± 0.0 | 0.461 ± 0.000 |
| ecmp | 27.11 ± 0.00 | 14.76 ± 0.00 | 66.5 ± 0.0 | 0.633 ± 0.000 |
| random | 42.58 ± 0.00 | 17.82 ± 0.00 | 89.2 ± 0.0 | 0.810 ± 0.000 |
| dqn | 42.97 ± 0.90 | 16.99 ± 1.00 | 84.8 ± 5.2 | 0.745 ± 0.082 |
| ppo | 42.87 ± 0.27 | 18.03 ± 0.05 | 90.5 ± 0.3 | 0.825 ± 0.005 |

Training curves (from the training logs, not committed):

- DQN: the mean reward over the last 100 episodes was about 42.4–42.8 at step 20,000 (ε = 0.62) and
  43.0–45.0 at step 300,000, depending on the seed. Only seed 0 shows a clear increase.
- PPO: the reward per training episode (2,048 steps) was 410.9–412.4 at step 10,240 and 410.0–410.6
  at the end (mean of the last 50 episodes), depending on the seed, so it did not increase.

## What this shows

1. **The agents did not learn a policy that beats random routing on the reward they were trained on.**
   DQN (42.97 ± 0.90) and PPO (42.87 ± 0.27) are within one standard deviation of random routing (42.58).
2. **The reward function favors spreading traffic over many links, not good routing.** Random
   routing earns more than twice the reward of shortest path (42.58 vs 18.22), even though shortest
   path has the lowest latency (12.11 ms) and the lowest loss (0.461%) of all policies. The reward's
   largest term grows with average link utilization. Longer paths put the same traffic on more links,
   which raises utilization without delivering more traffic.
3. On latency and loss, every alternative to shortest path is worse in this environment, including
   ECMP. Average link utilization does not measure delivered throughput here and should not be read
   as "higher is better".

This is a negative result about the current environment and reward, not about DQN or PPO in general.

## Limitations

- Simulation only; the queueing, latency and loss model is a hand-written approximation.
- One small topology, one traffic model, default hyperparameters, 300,000 steps, 3 seeds.
- PPO trains on 2,048-step episodes but is evaluated on 200-step episodes.
- The latency and loss metrics are averages over links, not over flows or packets.

## Next steps suggested by these results

- Redesign the reward around per-flow outcomes (delivered demand, path latency, drops) so that
  utilization on unused capacity is not rewarded.
- Add a metric for delivered traffic (e.g. the fraction of demand that fits through the bottleneck link of each path).
- Repeat with more seeds and a hyperparameter search only after the reward is fixed.
