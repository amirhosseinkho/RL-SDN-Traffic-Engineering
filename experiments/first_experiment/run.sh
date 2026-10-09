#!/usr/bin/env bash
# First experiment: DQN and PPO vs shortest-path and ECMP in the simulated environment.
#
# Setup
#   topology   : spine-leaf, 6 switches, 8 hosts, 100 Mbps / 5 ms links
#   training   : 300,000 steps per run, seeds 0, 1, 2 for each algorithm
#   evaluation : 20 episodes x 200 steps, evaluation traffic seed 1000
#                (different from every training seed)
#
# Usage (from the repository root):
#   bash experiments/first_experiment/run.sh [MODELS_DIR]
#
# Model weights go to MODELS_DIR (default: models/first_experiment, git-ignored).
# Per-seed evaluation results are written next to this script.
set -euo pipefail

MODELS_DIR="${1:-models/first_experiment}"
OUT_DIR="experiments/first_experiment"
SEEDS=(0 1 2)
STEPS="${STEPS:-300000}"
TOPO=(--topology spine_leaf --num-switches 6 --num-hosts 8)
export OMP_NUM_THREADS=2
mkdir -p "$MODELS_DIR"

for seed in "${SEEDS[@]}"; do
  python experiments/scripts/train_dqn.py "${TOPO[@]}" --timesteps "$STEPS" --seed "$seed" \
    --output-dir "$MODELS_DIR/seed_$seed" > "$MODELS_DIR/dqn_seed_$seed.log" 2>&1 &
  python experiments/scripts/train_ppo.py "${TOPO[@]}" --timesteps "$STEPS" --seed "$seed" \
    --output-dir "$MODELS_DIR/seed_$seed" > "$MODELS_DIR/ppo_seed_$seed.log" 2>&1 &
done
wait

# `wait` does not report failures of background jobs; check every model exists
for seed in "${SEEDS[@]}"; do
  for algo in dqn ppo; do
    [ -f "$MODELS_DIR/seed_$seed/${algo}_model.pt" ] || { echo "missing $algo model for seed $seed (see $MODELS_DIR/${algo}_seed_$seed.log)"; exit 1; }
  done
done

for seed in "${SEEDS[@]}"; do
  python experiments/scripts/evaluate.py "${TOPO[@]}" \
    --dqn-model "$MODELS_DIR/seed_$seed/dqn_model.pt" \
    --ppo-model "$MODELS_DIR/seed_$seed/ppo_model.pt" \
    --episodes 20 --seed 1000 \
    --output "$OUT_DIR/eval_seed_$seed.json"
done

python experiments/first_experiment/aggregate.py "$OUT_DIR"/eval_seed_*.json > "$OUT_DIR/summary.md"
cat "$OUT_DIR/summary.md"
