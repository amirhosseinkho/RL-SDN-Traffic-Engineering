# Project Status

This file records what was actually checked, how, and what happened. Nothing here is estimated.
If a component is not listed as ✅, do not assume it works.

| | |
|---|---|
| Last checked | 2026-10-09, branch `cleanup/honest-readme` |
| OS | Ubuntu 24.04.1 on WSL2 (Linux 5.15, x86_64), Windows 11 host |
| Python | 3.12.3 (WSL) |
| Node / npm | 22.15.1 / 10.9.2 (Windows host) |

Legend: ✅ works · ⚠️ partial · ❌ broken / missing · ⏸ not verified

## Summary

- The backend installs from `requirements.txt`, starts, and serves the REST API and the live-metrics WebSocket.
  All 51 backend tests pass (unit + integration).
- The frontend installs with `npm ci`, passes lint and type checks, and builds. The dashboard was
  run against the backend, and its main flows were used by hand: creating and activating a
  topology, live metrics, starting a training run, viewing training progress and evaluation.
- The RL environment is a NetworkX-based simulation. There is no Mininet integration, and no
  routing decision is pushed to switches.
- A first experiment in the simulation has been run (see [Experiments](#experiments)). Its main
  finding is that the current reward function does not separate the trained agents from random routing.

## Checks

### Backend

| Component | Check | Command | Result | Notes |
|---|---|---|---|---|
| Dependencies | Install pinned requirements | `pip install -r backend/requirements.txt`, then `pip check` | ✅ | `No broken requirements found`. PyTorch was installed from the CPU wheel index first, to avoid the CUDA download. |
| Module imports | Import every module under `backend/app` | `pkgutil.walk_packages` over `app` | ✅ 30/31 | Only `app.controller.openflow_handler` fails (`No module named 'ryu'`). It is a Ryu app meant to run under `ryu-manager`, not inside the backend. |
| Lint | Same command as CI | `ruff check app/ --select=E,F,W,I --ignore=E501` | ✅ | |
| Server | Start the API | `uvicorn app.main:app` | ✅ | `/health` and `/api/v1/docs` return 200. Tested with `DATABASE_URL=sqlite+aiosqlite:///...`; PostgreSQL was not used. |
| Unit tests | | `pytest tests/unit` | ✅ 41/41 | |
| Integration tests | API tests on in-memory SQLite | `pytest tests/integration` | ✅ 10/10 | |
| Coverage gate | `pytest tests` with `pytest.ini` | `pytest tests` | ✅ | 61.10% total, gate is 60%. |
| API by hand | Topology create/activate/delete, metrics summary/links/congestion, flows, training start + progress, evaluation + comparison, reports (JSON/CSV/PDF), copilot query + history | `curl` against the running server | ✅ | Reports returned `application/json`, `text/csv` and `application/pdf`. Without Ollama, the copilot answers from its keyword fallback and labels the answer `rule-based`. |
| Training WebSocket | `/ws/training/{session_id}` | not used | ⏸ | The dashboard reads training progress from `GET /rl/sessions/{id}`. |
| Training scripts | Train with seeds and an output directory | `train_dqn.py` / `train_ppo.py --seed N --output-dir DIR` | ✅ | Same seed gives identical weights, a different seed gives different weights (checked on DQN). |
| Evaluation script | DQN, PPO, shortest path, ECMP, random | `evaluate.py --seed N` | ✅ | A model can only be evaluated on the topology it was trained on (the observation size depends on the topology). |

### Frontend

| Component | Check | Command | Result | Notes |
|---|---|---|---|---|
| Clean install | With the committed lockfile | `npm ci` | ✅ | |
| Lint | | `npm run lint` | ✅ | ESLint 9 flat config. |
| Type check | | `npm run typecheck` | ✅ | |
| Build | | `npm run build` | ✅ | |
| Dashboard by hand | Vite dev server + backend, in a browser | `npm run dev` | ⚠️ | Used: Topology (create, activate, d3 graph), Live Metrics (WebSocket stream, charts), RL Training, Train Progress, Evaluation. Not opened: Active Flows, Reports and AI Copilot pages (their API endpoints were tested with `curl`). |

### Infrastructure and network

| Component | Check | Result | Notes |
|---|---|---|---|
| `docker-compose.yml` | `docker compose config --quiet` | ✅ | Valid (warning: the `version` key is obsolete). |
| Docker images | Build | ⏸ | Docker Desktop was not running. |
| GitHub Actions | Run on this branch | ⏸ | Not pushed yet. The commands CI runs were run locally (see above). |
| Ryu dependency | `pip install ryu` on Python 3.12 | ❌ | `ryu-4.34` fails to build (setuptools incompatibility). Ryu needs its own, older Python environment; docker-compose uses the `osrg/ryu` image. |
| Live Ryu / OpenFlow | | ⏸ | No Ryu controller or switches were available. When Ryu is unreachable, the metrics collector simulates the active topology. |
| Mininet | Search for any use | ❌ | No code uses Mininet. |
| RL → switches | | ❌ | `install_path` (in `openflow_handler.py` and `ryu_controller.py`) is never called, and `POST /flows/install` only records a flow in the database. |

## Known issues

1. The reward function rewards high average link utilization. Longer paths put the same traffic on
   more links and raise it, so random routing scores almost as well as the trained agents, while
   latency and loss get worse than with shortest-path routing (see [Experiments](#experiments)).
2. `EvaluationResult.avg_throughput_mbps` and `TrainingEpisode.avg_throughput_mbps` hold average
   link utilization in percent, not Mbps. The dashboard labels it correctly, but the column names are wrong.
3. During PPO training an episode is `n_steps` long (2048 by default), while evaluation uses
   200-step episodes.
4. Ryu does not install on Python 3.12, and nothing connects the agents to a live network.
5. Docker images have not been built.

## Experiments

| Experiment | Status | Result |
|---|---|---|
| [First experiment](experiments/first_experiment/README.md): DQN and PPO (3 seeds × 300,000 steps) vs shortest path, ECMP and random routing, spine-leaf 6×8, simulation only | ✅ run | DQN and PPO reach the same reward as random routing (42.97 ± 0.90 and 42.87 ± 0.27 vs 42.58). Shortest path has the lowest latency (12.11 ms) and loss (0.461%). The reward function needs to be redesigned before agent performance means anything. |
