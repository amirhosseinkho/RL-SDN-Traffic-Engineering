# Training Guide

> This guide documents how training is set up in the code, not what works best. Only default
> hyperparameters have been run so far (see the
> [second experiment](../experiments/second_experiment/README.md)), so no tuning advice is given yet.
> See [../STATUS.md](../STATUS.md) for what has been verified.

## Agents

| Agent | Implementation (`backend/app/rl/agents/`) |
|-------|-------------------------------------------|
| **DQN** | Dueling network, Double-DQN targets, uniform replay buffer, epsilon-greedy exploration. Q-values for the multi-discrete action are split into one slice per flow. |
| **PPO** | Shared trunk, one categorical policy head per flow, value head, GAE-Lambda advantages, clipped surrogate objective. |

Both agents act on the same multi-discrete action space: for every flow, one of `max_paths`
(default 4) precomputed shortest paths.

## Default Hyperparameters

These are the defaults in the code and the CLI scripts. They have not been tuned.

### DQN (`dqn_agent.py`, `trainer.py`, `train_dqn.py`)

```python
learning_rate = 1e-4
buffer_size = 100_000
batch_size = 64
gamma = 0.99
epsilon_decay = 50_000      # steps from 1.0 down to 0.05
learning_starts = 10_000    # no gradient updates before this step
checkpoint_freq = 50_000
```

### PPO (`ppo_agent.py`, `trainer.py`, `train_ppo.py`)

```python
learning_rate = 3e-4
n_steps = 2048
batch_size = 64
n_epochs = 10
gamma = 0.99
gae_lambda = 0.95
clip_range = 0.2
checkpoint_freq = 100_000
```

## Reward

```
reward = delivered_ratio - latency_weight · (mean_stretch - 1)
```

`delivered_ratio` is the share of total demand that gets through. `mean_stretch` is the
demand-weighted ratio of each flow's path latency to its uncongested shortest-path latency (see
[architecture.md](architecture.md#reward-function)). `latency_weight` is an argument of
`SDNRoutingEnv` (default `0.1`). Other values have not been studied.

The previous reward, built from average link utilization, rewarded detours that did not deliver more
traffic. Random routing scored as high as the trained agents under it (see the
[first experiment](../experiments/first_experiment/README.md)).

## Practical Notes

These are observations from the runs so far, not tuning advice.

1. A model can only be evaluated on the topology it was trained on: the observation size depends
   on the number of links. Loading a `fat_tree` model into a `spine_leaf` evaluation fails with a
   size mismatch.
2. `--output-dir DIR` saves the final model to `DIR/dqn_model.pt` or `DIR/ppo_model.pt` and
   checkpoints to `DIR/checkpoints/` (default `models/`).
3. `--seed N` seeds Python, NumPy, PyTorch and the simulated traffic. Two DQN runs with the same
   seed produced identical weights.
4. DQN makes no gradient updates before step 10,000 (`learning_starts`), so shorter runs leave the
   network untrained.
5. PPO trains on episodes of `n_steps` (2,048) steps, while evaluation uses 200-step episodes.
6. Precomputing the K shortest paths for `fat_tree` with `k=4` takes well under a second (0.34 s
   measured). It took about 8 minutes before the path generator was cut off after K paths.
7. No TensorBoard logging is implemented. Training progress is printed to the console log.
8. Both agents use CUDA automatically when PyTorch sees a GPU. On a GTX 1650 Ti (Windows, PyTorch
   2.11 + CUDA 12.8), 20,000 DQN steps took 153 s on the GPU vs 149 s on the CPU, and 10,240 PPO steps
   took 881 s vs 1080 s. Other jobs shared the CPU during both measurements. The networks are small
   and stepping the simulation dominates, so the GPU helps PPO a little and DQN not at all.

## Comparing Agents

After training, compare the agents with the shortest-path, ECMP, random and least-loaded baselines, using the
same topology arguments as in training and an evaluation seed that differs from the training seeds:

```bash
python experiments/scripts/evaluate.py \
    --topology spine_leaf --num-switches 6 --num-hosts 8 \
    --dqn-model models/seed_0/dqn_model.pt \
    --ppo-model models/seed_0/ppo_model.pt \
    --episodes 20 --seed 1000 \
    --output results/comparison.json
```

To repeat the second experiment (3 seeds per agent), run `bash experiments/second_experiment/run.sh`.
