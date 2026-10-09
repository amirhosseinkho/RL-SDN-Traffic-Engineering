# Project Status

This file records what was actually checked, how, and what happened. Nothing here is estimated.
If a component is not listed as ✅, do not assume it works.

| | |
|---|---|
| Checked commit | `8712e14` (`main`), plus the README/docs changes in this branch |
| Date | 2026-10-09 |
| OS | Ubuntu 24.04.1 on WSL2 (Linux 5.15, x86_64), Windows 11 host |
| Python | 3.12.3 (WSL) |
| Node / npm | 22.15.1 / 10.9.2 (Windows host) |

Legend: ✅ works · ⚠️ partial · ❌ broken · ⏸ not verified

## Summary

- The RL core works in isolation: the simulated environment, the DQN and PPO agents, the topology
  generator and the traffic generator pass their unit tests, and the training and evaluation scripts
  run end to end on a small budget.
- The web backend does not start: `app.main` fails to import with the pinned FastAPI version.
  Because of this, the REST API, WebSocket streams, dashboard data and AI Copilot are all unusable.
- There is no live network integration. The RL environment is a NetworkX-based simulation. No code
  uses Mininet, and no RL decision is ever pushed to a switch.
- No real experiments have been run, so there are no results.

## Checks

| Component | Check performed | Command | Result | Notes / evidence |
|---|---|---|---|---|
| Backend dependencies | Install pinned requirements | `pip install -r backend/requirements.txt` | ❌ | `ResolutionImpossible`: `stable-baselines3==2.4.0` needs `numpy<2.0`, but `numpy==2.1.3` is pinned. The same step fails in CI. |
| Backend dependencies (workaround) | Install everything except `stable-baselines3` (not imported anywhere in the code); torch from the CPU wheel index | `pip install torch==2.5.1 --index-url .../whl/cpu` then the remaining pins | ✅ | All other pins install. Every check below uses this environment. |
| Module imports | Import every module under `backend/app` | `pkgutil.walk_packages` over `app` | ⚠️ 26/31 | Fails: `app.main`, `app.api.routes.topology`, `app.api.routes.flows` (`AssertionError: Status code 204 must not have a response body`), `app.api.routes.reports` (`FastAPIError: Invalid args for response field`), `app.controller.openflow_handler` (`No module named 'ryu'`). |
| Backend server | Start the API | `uvicorn app.main:app` | ❌ | Same `204 must not have a response body` error during route registration (`topology.py:102`). |
| Unit tests: `test_agents.py` | DQN/PPO agents | `pytest tests/unit` | ✅ 13/13 | |
| Unit tests: `test_rl_environment.py` | Gymnasium env | `pytest tests/unit` | ✅ 10/10 | |
| Unit tests: `test_traffic_generator.py` | Traffic generator | `pytest tests/unit` | ✅ 8/8 | |
| Unit tests: `test_topology.py` | Topology generator | `pytest tests/unit` | ⚠️ 9/10 | `test_custom_topology` builds a config with `num_hosts=1`, but the schema requires `num_hosts >= 2`. |
| Unit test run as configured | Exit status with `pytest.ini` | `pytest tests/unit` | ❌ | Besides the failure above, `--cov-fail-under=70` fails: total coverage is 45.78%. |
| Integration tests | API tests | `pytest tests/integration` | ❌ | Collection error: importing `app.main` fails (see above). The tests also need `aiosqlite`, which is not in `requirements.txt`. They use in-memory SQLite, not PostgreSQL. |
| `train_dqn.py` | `--help`; short runs with the README flags and `--timesteps 2000` and `12000` | `python experiments/scripts/train_dqn.py --topology spine_leaf --num-switches 6 --num-hosts 8 --timesteps 12000` | ✅ | Exit code 0, writes `models/dqn_model.pt`. Gradient updates start only after `learning_starts=10000` (`trainer.py:75`), so the 12000-step run is the one that exercises them. `--output-dir` is accepted but ignored (the model always goes to `models/`). |
| `train_ppo.py` | `--help`; short run with the README flags and `--timesteps 2048` | `python experiments/scripts/train_ppo.py --topology fat_tree --k 4 --timesteps 2048` | ✅ | Finishes and writes `models/ppo_model.pt`. Path precomputation for fat-tree k=4 took about 8 minutes before training began. |
| `evaluate.py` (README command) | Evaluate the two models trained above | `python experiments/scripts/evaluate.py --topology spine_leaf --dqn-model ... --ppo-model ... --episodes 2` | ❌ | `RuntimeError: size mismatch`. The README trains PPO on `fat_tree` but evaluates on `spine_leaf`, so the observation sizes differ (163 vs 67). |
| `evaluate.py` (matching topology) | DQN + baselines on the topology DQN was trained on | same, without a PPO model | ✅ | Shortest-path, ECMP and DQN are evaluated and a JSON file is written. The numbers come from a 2,000-step model and are not results. |
| Ryu dependency | Install Ryu on Python 3.12 (separate venv) | `pip install ryu` | ❌ | `ryu-4.34` fails to build (`AttributeError: ... 'get_script_args'`, a setuptools incompatibility). Ryu is also not listed in `requirements.txt`. |
| `openflow_handler.py` | Import | see module imports | ❌ | Requires `ryu`. It is also not the app started by `docker-compose.yml`, which runs Ryu's built-in REST apps instead. |
| Mininet | Search for any use | `grep -ri mininet` over code, Dockerfiles, compose, requirements | ❌ not present | No code uses Mininet. It appears only in the README and `docs/architecture.md`. |
| RL → network | Is any routing decision installed on switches? | `grep -rn install_path` | ❌ | `install_path` is defined in `openflow_handler.py` and `ryu_controller.py` but never called. `POST /flows/install` only writes a database row. |
| Frontend dependencies (clean CI-style install) | `npm ci` with the committed files | `npm ci` | ❌ | No `package-lock.json` is committed. The CI frontend job and `frontend/Dockerfile` both rely on `npm ci`. |
| Frontend dependencies | `npm install` | `npm install` | ✅ | Resolves current versions within the `^` ranges (e.g. TypeScript 5.9.3, Vite 5.4.21). |
| Frontend type check | `tsc --noEmit` | `npm run typecheck` | ❌ | 4 errors: `TopologyGraph.tsx` (lines 40 and 111), `FlowsPage.tsx:33` (`avg_bandwidth_mbps` missing), `TopologyPage.tsx:226` (`Network` is not imported). |
| Frontend build | `npm run build` (`tsc && vite build`) | `npm run build` | ❌ | Fails at `tsc`. `vite build` on its own succeeds. |
| Frontend lint | `npm run lint` | `npm run lint` | ❌ | ESLint 9 finds no `eslint.config.js`. |
| `docker-compose.yml` | Syntax | `docker compose config --quiet` | ✅ | Valid (warning: the `version` key is obsolete). |
| Docker images | Build | not run | ⏸ | Docker Desktop was not running. Both Dockerfiles run steps that fail above (`pip install -r requirements.txt`, `npm ci`), so the builds are expected to fail, but this was not executed. |
| CI on GitHub | Latest runs | GitHub Actions API | ❌ | The last 3 runs (including `8712e14`) failed: backend at "Install dependencies", frontend at "Set up Node" (that step caches npm using `frontend/package-lock.json`, which does not exist; the job log itself was not read). |

## Known issues

1. `backend/requirements.txt`: `numpy==2.1.3` conflicts with `stable-baselines3==2.4.0`. `stable-baselines3`, `structlog`, `alembic` and `redis` are listed but not imported anywhere in `backend/app`.
2. `backend/app/api/routes/topology.py:102` and `backend/app/api/routes/flows.py:68`: `DELETE` routes with status 204 declare a response body, so FastAPI 0.115.5 refuses to register them.
3. `backend/app/api/routes/reports.py`: the `/generate` return annotation is not a valid response model.
4. `backend/tests/unit/test_topology.py::test_custom_topology` uses `num_hosts=1`, which the schema rejects.
5. `backend/pytest.ini`: `--cov-fail-under=70` cannot pass while API modules cannot be imported (coverage 45.78%).
6. `aiosqlite` (needed by the integration tests) is missing from `requirements.txt`.
7. `experiments/scripts/train_dqn.py`: `--output-dir` is never used.
8. `experiments/scripts/evaluate.py`: models trained on one topology cannot be loaded on another. The README's example commands mix `fat_tree` and `spine_leaf`.
9. `backend/app/rl/agents/dqn_agent.py:59`: the class docstring says "Prioritized experience replay" and the network docstring mentions "noisy heads", but sampling is uniform and there are no noisy layers.
10. Ryu 4.34 does not install on Python 3.12, and Ryu is not in `requirements.txt`.
11. `docker-compose.yml` runs Ryu's built-in apps with `--wsapi-port 8081` while mapping and configuring port 8080 for the REST API. This was not run, so it is not confirmed whether the backend can reach Ryu.
12. Frontend: no `package-lock.json`, 4 TypeScript errors, no ESLint config.

## Not verified, and why

- **Live Ryu + OpenFlow switches, LLDP topology discovery**: Ryu could not be installed on Python 3.12, and no switches or Mininet were available.
- **REST API, WebSocket streams, report export (JSON/CSV/PDF), AI Copilot**: the backend does not start. The code for these exists but was never run.
- **Dashboard pages**: the bundle builds with `vite build`, but there is no working backend to serve data.
- **Docker images and `docker compose up`**: not run (Docker Desktop stopped).
- **PostgreSQL**: not used by any check that could run.
- **Python 3.13+**: only 3.12.3 was tested.
- **Learning quality of DQN/PPO**: only runs of a few thousand steps were done, to check that the scripts work. No conclusions about performance can be drawn from them.
