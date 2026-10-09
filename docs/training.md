# Training Guide

> No full training runs have been done yet, so this guide documents how training is set up in the
> code, not what works best. Hyperparameter advice will be added once experiments exist.
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

## Reward Weights

The reward weights are set through the `reward_weights` argument of `SDNRoutingEnv`. The default is:

```python
reward_weights = {"throughput": 1.0, "latency": 0.3, "congestion": 0.5, "packet_loss": 0.4}
```

The effect of other weightings has not been studied yet.

## Practical Notes

These are observations from short runs, not tuning advice.

1. A model can only be evaluated on the topology it was trained on: the observation size depends
   on the number of links. Loading a `fat_tree` model into a `spine_leaf` evaluation fails with a
   size mismatch.
2. Final models are always written to `models/dqn_model.pt` and `models/ppo_model.pt`, and checkpoints
   to `models/checkpoints/`. The `--output-dir` flag of `train_dqn.py` is currently ignored.
3. For `fat_tree` with `k=4`, precomputing the K shortest paths between all host pairs took about
   8 minutes before training started.
4. No TensorBoard logging is implemented. Training progress is printed to the console log.

## Comparing Agents

After training, compare the agents with the shortest-path and ECMP baselines, using the same
topology arguments as in training:

```bash
python experiments/scripts/evaluate.py \
    --topology spine_leaf --num-switches 6 --num-hosts 8 \
    --dqn-model models/dqn_model.pt \
    --episodes 50 \
    --output results/comparison.json
```

There are no results yet.
