#!/usr/bin/env bash
# Mininet experiment: the second experiment's policies on an emulated network (Mininet + os-ken).
#
# Setup
#   topology   : spine-leaf, 2 spine + 4 leaf, 8 hosts (as experiments/second_experiment/run.sh);
#                switch links 200 Mbps x 0.05 = 10 Mbps, 5 ms netem delay, 25-packet queue
#   traffic    : SDNRoutingEnv's traffic model, traffic seeds 1000, 1001, 1002; 16 flows,
#                demands x 0.05 as iperf3 UDP; 20 epochs of 10 s (+1 warm-up epoch) per run
#   policies   : shortest path, ECMP (5-tuple hash), random, least-loaded: one run per traffic seed;
#                DQN and PPO: the second experiment's models, seeds 0, 1, 2, each on every traffic seed
#   stress     : shortest path, least-loaded and DQN (model seed = traffic seed - 1000) with
#                spine1-leaf4 degraded from epoch 5 on (+20 ms delay, 2% loss, tc qdisc change)
#
# Usage (from the repository root, Linux with Mininet, Open vSwitch, iperf3, tshark, os-ken):
#   sudo bash experiments/mininet_experiment/run.sh <venv python> <models dir>
#   e.g. sudo bash experiments/mininet_experiment/run.sh ~/venvs/rlsdn/bin/python ~/second_experiment_models
#
# Runs that already have a summary.json are skipped, so the script can be resumed.
set -euo pipefail

PY="${1:?usage: run.sh <venv python> <models dir>}"
MODELS_DIR="${2:?usage: run.sh <venv python> <models dir>}"
OUT="experiments/mininet_experiment/runs"
EPOCHS="${EPOCHS:-20}"
SEEDS=(1000 1001 1002)
export OMP_NUM_THREADS=2

modprobe -a openvswitch sch_htb sch_netem sch_tbf

run() {  # run <dir> <runner args...>
  local dir="$OUT/$1"; shift
  if [ -f "$dir/summary.json" ]; then echo "skip $dir"; return; fi
  rm -rf "$dir"; mkdir -p "$dir"
  echo "$(date +%T) $dir"
  "$PY" -m emulation.runner "$@" --epochs "$EPOCHS" --out "$dir" > "$dir/runner.out" 2>&1 \
    || { echo "FAILED $dir (see $dir/runner.out)"; tail -5 "$dir/runner.out"; }
}

for seed in "${SEEDS[@]}"; do
  # Capture and verify paths in epoch 3 of the first traffic seed, once per policy
  cap=(); [ "$seed" = 1000 ] && cap=(--capture-epoch 3)
  for p in shortest_path ecmp random least_loaded; do
    run "main/${p}_t$seed" --policy "$p" --traffic-seed "$seed" "${cap[@]}"
  done
  for m in 0 1 2; do
    c=(); [ "$m" = 0 ] && c=("${cap[@]}")
    for p in dqn ppo; do
      run "main/${p}_m${m}_t$seed" --policy "$p" --model "$MODELS_DIR/seed_$m/${p}_model.pt" --traffic-seed "$seed" "${c[@]}"
    done
  done
done

stress=(--stress-link spine1-leaf4 --stress-from-epoch 5 --stress-extra-delay-ms 20 --stress-loss-pct 2)
for i in 0 1 2; do
  seed="${SEEDS[$i]}"
  run "stress/shortest_path_t$seed" --policy shortest_path --traffic-seed "$seed" "${stress[@]}"
  run "stress/least_loaded_t$seed" --policy least_loaded --traffic-seed "$seed" "${stress[@]}"
  run "stress/dqn_m${i}_t$seed" --policy dqn --model "$MODELS_DIR/seed_$i/dqn_model.pt" --traffic-seed "$seed" "${stress[@]}"
done

# Simulator on the same traffic, and the tables
"$PY" -m emulation.sim_matched --models-dir "$MODELS_DIR" --out experiments/mininet_experiment/sim_matched.json > /dev/null
"$PY" -m emulation.analyze experiments/mininet_experiment
chown -R "${SUDO_UID:-0}:${SUDO_GID:-0}" experiments/mininet_experiment
