# Training Guide

## Choosing an Agent

| Agent | Strengths | When to Use |
|-------|-----------|-------------|
| **DQN** | Sample efficient, good with sparse rewards | Small topologies, quick experiments |
| **PPO** | Stable, works well with continuous action spaces | Large topologies, long training runs |

## Hyperparameter Tuning

### DQN Recommendations

```python
# Small topology (≤ 8 switches)
learning_rate = 1e-4
buffer_size = 50_000
batch_size = 64
gamma = 0.99
epsilon_decay = 20_000

# Large topology (> 16 switches)
learning_rate = 5e-5
buffer_size = 200_000
batch_size = 128
gamma = 0.995
epsilon_decay = 100_000
```

### PPO Recommendations

```python
# Standard (works for most topologies)
learning_rate = 3e-4
n_steps = 2048
batch_size = 64
n_epochs = 10
gamma = 0.99
gae_lambda = 0.95
clip_range = 0.2
```

## Reward Shaping

Adjust `reward_weights` in `SDNRoutingEnv` to change agent behavior:

```python
# Latency-focused (minimize delay)
reward_weights = {"throughput": 0.5, "latency": 1.0, "congestion": 0.3, "packet_loss": 0.2}

# Throughput-focused (maximize flow completion)
reward_weights = {"throughput": 1.5, "latency": 0.1, "congestion": 0.3, "packet_loss": 0.1}

# Balanced (default)
reward_weights = {"throughput": 1.0, "latency": 0.3, "congestion": 0.5, "packet_loss": 0.4}
```

## Training Tips

1. **Start with small topologies** (linear 4 switches) to verify the agent learns
2. **Monitor epsilon decay** — if it decays too fast, the agent won't explore
3. **Watch for reward plateau** — if reward doesn't improve after 100k steps, adjust learning rate
4. **Use TensorBoard** — training metrics are logged to `logs/` directory
5. **Save checkpoints** — models are checkpointed every 50k steps

## Convergence Indicators

- **DQN**: Reward should start improving after ~20k steps (after learning starts)
- **PPO**: Reward should improve steadily from the first update
- **Both**: Average latency should decrease and throughput increase as training progresses

## Comparing Results

After training, run evaluation to compare agents:

```bash
python experiments/scripts/evaluate.py \
    --dqn-model models/dqn_model.pt \
    --ppo-model models/ppo_model.pt \
    --episodes 50 \
    --output results/comparison.json
```

Expected improvements over shortest-path baseline:
- Latency: 15-40% reduction
- Throughput: 20-50% improvement  
- Packet loss: 50-80% reduction
