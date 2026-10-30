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
- Two experiments have been run in the simulation (see [Experiments](#experiments)). With the
  current per-flow reward, DQN and PPO beat shortest-path, ECMP and random routing but not a simple
  least-loaded heuristic.

## Checks

### Backend

| Component | Check | Command | Result | Notes |
|---|---|---|---|---|
| Dependencies | Install pinned requirements | `pip install -r backend/requirements.txt`, then `pip check` | ✅ | `No broken requirements found`. PyTorch was installed from the CPU wheel index first, to avoid the CUDA download. |
| Module imports | Import every module under `backend/app` | `pkgutil.walk_packages` over `app` | ✅ 30/31 | Only `app.controller.openflow_handler` fails (`No module named 'ryu'`). It is a Ryu app meant to run under `ryu-manager`, not inside the backend. |
| Lint | Same command as CI | `ruff check app/ --select=E,F,W,I --ignore=E501` | ✅ | |
| Server | Start the API | `uvicorn app.main:app` | ✅ | `/health` and `/api/v1/docs` return 200. Tested with `DATABASE_URL=sqlite+aiosqlite:///...`; PostgreSQL was not used. |
| Unit tests | | `pytest tests/unit` | ✅ 44/44 | Includes tests for the reward (detours without congestion lower it; spreading load off an overloaded link raises it) and for bounded demand. |
| Integration tests | API tests on in-memory SQLite | `pytest tests/integration` | ✅ 10/10 | |
| Coverage gate | `pytest tests` with `pytest.ini` | `pytest tests` | ✅ | 61.09% total, gate is 60%. |
| API by hand | Topology create/activate/delete, metrics summary/links/congestion, flows, training start + progress, evaluation + comparison, reports (JSON/CSV/PDF), copilot query + history | `curl` against the running server | ✅ | Reports returned `application/json`, `text/csv` and `application/pdf`. Without Ollama, the copilot answers from its keyword fallback and labels the answer `rule-based`. |
| Training WebSocket | `/ws/training/{session_id}` | not used | ⏸ | The dashboard reads training progress from `GET /rl/sessions/{id}`. |
| Training scripts | Train with seeds and an output directory | `train_dqn.py` / `train_ppo.py --seed N --output-dir DIR` | ✅ | Same seed gives identical weights, a different seed gives different weights (checked on DQN). |
| Evaluation script | DQN, PPO, shortest path, ECMP, random, least-loaded | `evaluate.py --seed N` | ✅ | A model can only be evaluated on the topology it was trained on (the observation size depends on the topology). |

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
| Ryu dependency / controller | `apt install python3-os-ken` (os-ken 2.8.1, the maintained Ryu fork, system Python 3.12); Ryu 4.34 in a separate Python 3.9 env (`conda create -p ~/venvs/ryu39 python=3.9`, `pip install setuptools<58 pbr`, `pip install --no-build-isolation ryu==4.34 eventlet==0.30.2`) | ✅ | 2026-10-30. `pip install ryu` on Python 3.12 still fails. The emulation runs on **os-ken**; Ryu 4.34 was installed only to test `FlowManager` against Ryu's `ofctl_rest`, which os-ken does not ship (neither the apt package nor PyPI `os-ken` 4.2.2 contains `ofctl_rest`, `rest_topology` or any wsgi app). `openflow_handler.py` and `emulation/controller_app.py` import os-ken or Ryu through a small shim. |
| Live os-ken / OpenFlow | `sudo python -m emulation.milestone --out experiments/mininet_experiment/phase1` | ✅ | os-ken app `emulation/controller_app.py` with 6 OVS switches (OpenFlow 1.3, kernel datapath) in Mininet. All 6 switches connect; LLDP discovery finds the 16 directed links with exactly the mapped ports; port statistics are collected every second. Paths installed through its REST API appear in `ovs-ofctl dump-flows` on every hop, and tshark on all 8 spine interfaces shows 4/4 flows only on their installed paths, before and after a path change (old spine's rules deleted). Evidence: `experiments/mininet_experiment/phase1/`. The metrics collector in the backend still reads only Ryu's REST API (not tested against a live controller). |
| Mininet | `sudo mn --link tc --test pingall`; `emulation/topology.py` builds the spine-leaf network from the simulator's `TopologyDefinition` | ✅ | 2026-10-30, Mininet 2.3.0, Open vSwitch 3.3.9, WSL2 kernel 6.18.54.1 (modules `openvswitch`, `sch_htb`, `sch_netem`, `sch_tbf`). pingall: 0% dropped. Switch links are `TCLink` (htb rate + netem delay/limit; `phase1/tc_spine1-eth1.txt`). The experiment on it is a later phase. |
| RL → switches | `FlowManager.install_path` against Ryu 4.34 `ofctl_rest` + `rest_topology` (`phase1/flowmanager_*.txt`) | ⚠️ | Unchanged, it installed nothing: Ryu reports dpids and ports as hex strings, which it misread (spine1 = `0000000000000065` became dpid 65, leaf dpids were skipped), it skipped the egress switch, and a 404 escaped as an exception. Fixed (hex parsing, IPv4 match, permanent rules, cookies, egress-first via `app/controller/flow_rules.py`): rules on all 3 hops, ping 3/3. Routing decisions of the agents are not yet installed (later phase). `POST /flows/install` still only records a flow in the database. |

## Known issues

1. The agents' observation does not include which hosts a flow connects or which links its candidate
   paths use, so they cannot see what the least-loaded heuristic uses. This is a likely reason they
   fall short of it.
2. `EvaluationResult.avg_throughput_mbps` and `TrainingEpisode.avg_throughput_mbps` hold average
   link utilization in percent, not Mbps. The dashboard labels it correctly, but the column names are wrong.
3. During PPO training an episode is `n_steps` long (2048 by default), while evaluation uses
   200-step episodes.
4. Ryu 4.34 does not install on Python 3.12 (os-ken, the maintained fork, is used instead). The agents' decisions are not yet installed on switches.
5. Docker images have not been built.

## Experiments

| Experiment | Status | Result |
|---|---|---|
| [Second experiment](experiments/second_experiment/README.md): per-flow reward, stationary traffic; DQN and PPO (3 seeds × 300,000 steps) vs shortest path, ECMP, random and least-loaded; spine-leaf 6×8; simulation only | ✅ run | Delivered demand: DQN 80.8% ± 0.7%, PPO 75.1% ± 1.9%, shortest path 63.1%, random 65.5%, ECMP 56.0%, least-loaded 88.4%. |
| [First experiment](experiments/first_experiment/README.md): original utilization reward | superseded | The agents scored the same as random routing. The reward and a traffic bug (demand growing without bound) were fixed afterwards. |
