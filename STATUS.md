# Project Status

This file records what was actually checked, how, and what happened. Nothing here is estimated.
If a component is not listed as ✅, do not assume it works.

| | |
|---|---|
| Last checked | 2026-10-30, branch `feature/mininet-emulation` (earlier rows: 2026-10-09, branch `cleanup/honest-readme`) |
| OS | Ubuntu 24.04.1 on WSL2 (Linux 6.18.54.1 since 2026-10-30, 5.15 before), x86_64, Windows 11 host |
| Python | 3.12.3 (WSL) |
| Node / npm | 22.15.1 / 10.9.2 (Windows host) |

Legend: ✅ works · ⚠️ partial · ❌ broken / missing · ⏸ not verified

## Summary

- The backend installs from `requirements.txt`, starts, and serves the REST API and the live-metrics WebSocket.
  68 backend tests: 67 pass, 1 is skipped without os-ken installed (it passes with os-ken).
- The frontend installs with `npm ci`, passes lint and type checks, and builds. The dashboard was
  run against the backend, and its main flows were used by hand: creating and activating a
  topology, live metrics, starting a training run, viewing training progress and evaluation.
- The RL environment is a NetworkX-based simulation. Training happens only there.
- The trained agents, and the baselines, were also run zero-shot on an emulated network (Mininet,
  Open vSwitch, os-ken), with their routing installed as OpenFlow rules
  ([Mininet experiment](experiments/mininet_experiment/README.md)). The backend API itself does not
  install routes on switches.
- Two experiments have been run in the simulation (see [Experiments](#experiments)). With the
  current per-flow reward, DQN and PPO beat shortest-path, ECMP and random routing but not a simple
  least-loaded heuristic. On the emulated network, the ranking against the baselines is mostly
  the same as in the simulator on the same traffic (Spearman 0.94).

## Checks

### Backend

| Component | Check | Command | Result | Notes |
|---|---|---|---|---|
| Dependencies | Install pinned requirements | `pip install -r backend/requirements.txt`, then `pip check` | ✅ | `No broken requirements found`. PyTorch was installed from the CPU wheel index first, to avoid the CUDA download. |
| Module imports | Import every module under `backend/app` | `pkgutil.walk_packages` over `app` | ✅ 30/31 | Only `app.controller.openflow_handler` fails (`No module named 'ryu'`). It is a Ryu app meant to run under `ryu-manager`, not inside the backend. |
| Lint | Same command as CI | `ruff check app/ --select=E,F,W,I --ignore=E501` (and on `emulation/`) | ✅ | 2026-10-30. |
| Server | Start the API | `uvicorn app.main:app` | ✅ | `/health` and `/api/v1/docs` return 200. Tested with `DATABASE_URL=sqlite+aiosqlite:///...`; PostgreSQL was not used. |
| Unit tests | | `pytest tests/unit` | ✅ 57/58, 1 skipped | 2026-10-30. Includes tests for the reward (detours without congestion lower it; spreading load off an overloaded link raises it), for bounded demand, and 14 for OpenFlow rule building (`test_flow_rules.py`). The skipped test serializes a real os-ken FlowMod; it passes when os-ken is importable (14/14 with the system os-ken 2.8.1). |
| Integration tests | API tests on in-memory SQLite | `pytest tests/integration` | ✅ 10/10 | 2026-10-30. |
| Coverage gate | `pytest tests` with `pytest.ini` | `pytest tests` | ✅ | 62.80% total, gate is 60% (2026-10-30). |
| API by hand | Topology create/activate/delete, metrics summary/links/congestion, flows, training start + progress, evaluation + comparison, reports (JSON/CSV/PDF), copilot query + history | `curl` against the running server | ✅ | Reports returned `application/json`, `text/csv` and `application/pdf`. Without Ollama, the copilot answers from its keyword fallback and labels the answer `rule-based`. |
| Training WebSocket | `/ws/training/{session_id}` | not used | ⏸ | The dashboard reads training progress from `GET /rl/sessions/{id}`. |
| Training scripts | Train with seeds and an output directory | `train_dqn.py` / `train_ppo.py --seed N --output-dir DIR` | ✅ | Same seed gives identical weights, a different seed gives different weights (checked on DQN). |
| Evaluation script | DQN, PPO, shortest path, ECMP, random, least-loaded | `evaluate.py --seed N` | ✅ | A model can only be evaluated on the topology it was trained on (the observation size depends on the topology). |
| Emulation unit tests | Mapping, traffic/iperf3 parsing, tc parsing, observation, policies, tshark path check | `cd emulation && pytest` | ✅ 31/32, 1 skipped | 2026-10-30, Linux and Windows (Python 3.12.8, no Mininet). The skipped test is the Mininet integration test below. |
| Emulation integration test | Topology + os-ken controller, install a path, 3 s of iperf3, tshark confirms the path | `sudo <venv>/bin/python -m pytest emulation/tests -m mininet` | ✅ 1/1 | 2026-10-30, as root in WSL2. |

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
| GitHub Actions | Run on this branch | ⏸ | Not pushed yet. The commands CI runs were run locally (see above). `ci.yml` now also lints `emulation/` and runs its unit tests (no Mininet needed). `emulation.yml` (manual trigger only) installs Mininet, OVS, iperf3, tshark and os-ken on a hosted runner and runs the integration test; it has not been run, and whether hosted runners can load the `openvswitch` kernel module is not verified, so it is kept out of the push/PR workflow. |
| Ryu dependency / controller | `apt install python3-os-ken` (os-ken 2.8.1, the maintained Ryu fork, system Python 3.12); Ryu 4.34 in a separate Python 3.9 env (`conda create -p ~/venvs/ryu39 python=3.9`, `pip install setuptools<58 pbr`, `pip install --no-build-isolation ryu==4.34 eventlet==0.30.2`) | ✅ | 2026-10-30. `pip install ryu` on Python 3.12 still fails. The emulation runs on **os-ken**; Ryu 4.34 was installed only to test `FlowManager` against Ryu's `ofctl_rest`, which os-ken does not ship (neither the apt package nor PyPI `os-ken` 4.2.2 contains `ofctl_rest`, `rest_topology` or any wsgi app). `openflow_handler.py` and `emulation/controller_app.py` import os-ken or Ryu through a small shim. |
| Live os-ken / OpenFlow | `sudo python -m emulation.milestone --out experiments/mininet_experiment/phase1` | ✅ | os-ken app `emulation/controller_app.py` with 6 OVS switches (OpenFlow 1.3, kernel datapath) in Mininet. All 6 switches connect; LLDP discovery finds the 16 directed links with exactly the mapped ports; port statistics are collected every second. Paths installed through its REST API appear in `ovs-ofctl dump-flows` on every hop, and tshark on all 8 spine interfaces shows 4/4 flows only on their installed paths, before and after a path change (old spine's rules deleted). Evidence: `experiments/mininet_experiment/phase1/`. The metrics collector in the backend still reads only Ryu's REST API (not tested against a live controller). |
| Mininet | `sudo mn --link tc --test pingall`; `emulation/topology.py` builds the spine-leaf network from the simulator's `TopologyDefinition` | ✅ | 2026-10-30, Mininet 2.3.0, Open vSwitch 3.3.9, WSL2 kernel 6.18.54.1 (modules `openvswitch`, `sch_htb`, `sch_netem`, `sch_tbf`). pingall: 0% dropped. Switch links are `TCLink` (htb rate + netem delay/limit; `phase1/tc_spine1-eth1.txt`). The [Mininet experiment](experiments/mininet_experiment/README.md) ran on it: 39 runs, 2 h 30 min, 0 failed runs. |
| RL → switches | `FlowManager.install_path` against Ryu 4.34 `ofctl_rest` + `rest_topology` (`phase1/flowmanager_*.txt`); agents' decisions through `emulation/runner.py` | ⚠️ | Unchanged, `FlowManager` installed nothing: Ryu reports dpids and ports as hex strings, which it misread (spine1 = `0000000000000065` became dpid 65, leaf dpids were skipped), it skipped the egress switch, and a 404 escaped as an exception. Fixed (hex parsing, IPv4 match, permanent rules, cookies, egress-first via `app/controller/flow_rules.py`): rules on all 3 hops, ping 3/3. 2026-10-30: the DQN and PPO agents' decisions (and the baselines') were installed every epoch by the emulation runner through the os-ken app in 39 runs; FlowMods sent always equalled the predicted rule changes, and tshark confirmed 16/16 flows on their installed paths for every policy. Partial because this goes through the emulation runner, not the backend: `POST /flows/install` still only records a flow in the database. |

## Known issues

1. The agents' observation does not include which hosts a flow connects or which links its candidate
   paths use, so they cannot see what the least-loaded heuristic uses. This is a likely reason they
   fall short of it.
2. `EvaluationResult.avg_throughput_mbps` and `TrainingEpisode.avg_throughput_mbps` hold average
   link utilization in percent, not Mbps. The dashboard labels it correctly, but the column names are wrong.
3. During PPO training an episode is `n_steps` long (2048 by default), while evaluation uses
   200-step episodes.
4. Ryu 4.34 does not install on Python 3.12 (os-ken, the maintained fork, is used instead). The backend's
   flow routes and metrics collector still target Ryu's REST API, which os-ken does not ship; the
   emulation uses its own os-ken app (`emulation/controller_app.py`).
5. Docker images have not been built.
6. The simulator's link model underestimates delivered demand under load: it shares one capacity
   between both directions of a link, and it does not remove dropped traffic from downstream links.
   On the emulated network this made it 5.9 points pessimistic on average (up to 30 in single
   epochs); a fluid model without these two simplifications is within 0.27 points. Its loss and
   queue features also differ from measured ones (loss never above 1%; queues half full at half
   load). See the [Mininet experiment](experiments/mininet_experiment/README.md#the-gap-between-simulator-and-emulation).
7. In the stress runs (2% netem loss), iperf3's UDP setup datagram was occasionally lost, so 29 of
   2,880 flow-epochs have no measurement and are left out of delivered demand.

## Experiments

| Experiment | Status | Result |
|---|---|---|
| [Mininet experiment](experiments/mininet_experiment/README.md): the second experiment's models (3 seeds each) and the 4 baselines, zero-shot on Mininet + Open vSwitch + os-ken (10 Mbit/s links, iperf3 UDP), 3 traffic seeds × 20 epochs, plus 9 netem stress runs | ✅ run (2026-10-30) | Delivered demand, emulation (simulator on the same traffic): least-loaded 87.6% (83.0%), DQN 80.7% (75.5%), ECMP 79.1% (76.4%), PPO 75.5% (71.5%), random 75.1% (66.3%), shortest path 68.0% (60.0%). Rank correlation 0.94; DQN and ECMP swap. No policy consistently moved traffic off a degraded link. |
| [Second experiment](experiments/second_experiment/README.md): per-flow reward, stationary traffic; DQN and PPO (3 seeds × 300,000 steps) vs shortest path, ECMP, random and least-loaded; spine-leaf 6×8; simulation only | ✅ run | Delivered demand: DQN 80.8% ± 0.7%, PPO 75.1% ± 1.9%, shortest path 63.1%, random 65.5%, ECMP 56.0%, least-loaded 88.4%. |
| [First experiment](experiments/first_experiment/README.md): original utilization reward | superseded | The agents scored the same as random routing. The reward and a traffic bug (demand growing without bound) were fixed afterwards. |
