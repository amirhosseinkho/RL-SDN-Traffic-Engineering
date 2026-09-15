# RL-SDN Traffic Engineering

An AI-powered Software Defined Networking platform that uses **Reinforcement Learning** to optimize routing decisions and traffic engineering in a Software Defined Network.

[![CI](https://github.com/your-username/rl-sdn-traffic-engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/rl-sdn-traffic-engineering/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-blue.svg)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Architecture

```mermaid
graph TB
    subgraph Frontend["Frontend (React + TypeScript)"]
        UI[Dashboard UI]
        WS[WebSocket Client]
    end

    subgraph Backend["Backend (FastAPI + Python)"]
        API[REST API]
        WSS[WebSocket Server]
        RL[RL Training Engine]
        MON[Metrics Collector]
        COP[AI Copilot]
    end

    subgraph RL_Stack["RL Stack (PyTorch)"]
        ENV[SDN Gym Environment]
        DQN[DQN Agent]
        PPO[PPO Agent]
    end

    subgraph Network["Network Layer"]
        RYU[Ryu Controller]
        OF[OpenFlow 1.3]
        MN[Mininet Topology]
    end

    subgraph Storage["Storage"]
        PG[(PostgreSQL)]
        RD[(Redis)]
        MD[/Model Files/]
    end

    subgraph AI["AI Copilot"]
        OL[Ollama LLM]
    end

    UI --> API
    UI --> WS
    WS --> WSS
    API --> RL
    API --> MON
    API --> COP
    RL --> ENV
    ENV --> DQN
    ENV --> PPO
    MON --> RYU
    RYU --> OF
    OF --> MN
    API --> PG
    RL --> MD
    WSS --> RD
    COP --> OL
```

---

## Project Structure

```
rl-sdn-traffic-engineering/
├── backend/
│   ├── app/
│   │   ├── config.py               # Centralized settings (pydantic-settings)
│   │   ├── main.py                 # FastAPI app + lifespan
│   │   ├── controller/
│   │   │   ├── ryu_controller.py   # Ryu REST API client
│   │   │   ├── flow_manager.py     # OpenFlow flow installation
│   │   │   └── openflow_handler.py # Ryu app (OpenFlow 1.3)
│   │   ├── topology/
│   │   │   └── generator.py        # Topology generator (5 types)
│   │   ├── monitoring/
│   │   │   └── collector.py        # Real-time metrics collector
│   │   ├── rl/
│   │   │   ├── environment.py      # SDNRoutingEnv (Gymnasium)
│   │   │   ├── trainer.py          # DQN + PPO trainers
│   │   │   └── agents/
│   │   │       ├── dqn_agent.py    # Dueling Double DQN
│   │   │       └── ppo_agent.py    # PPO with GAE-Lambda
│   │   ├── api/
│   │   │   ├── routes/             # FastAPI routers
│   │   │   └── websocket.py        # WS endpoints
│   │   ├── database/
│   │   │   ├── models.py           # SQLAlchemy ORM models
│   │   │   ├── schemas.py          # Pydantic schemas
│   │   │   └── session.py          # Async DB session
│   │   └── simulation/
│   │       ├── traffic_generator.py # Traffic pattern generator
│   │       └── evaluator.py         # Performance comparator
│   ├── tests/
│   │   ├── unit/                    # Unit tests (pytest)
│   │   └── integration/             # API integration tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── components/              # Reusable UI components
│       ├── pages/                   # 8 dashboard pages
│       ├── services/                # API + WebSocket clients
│       ├── store/                   # Zustand state
│       └── types/                   # TypeScript types
├── experiments/
│   └── scripts/
│       ├── train_dqn.py            # Standalone DQN training
│       ├── train_ppo.py            # Standalone PPO training
│       └── evaluate.py             # Comparative evaluation
├── models/                         # Saved model weights
├── docs/                           # Architecture and API docs
├── docker-compose.yml
└── .github/workflows/ci.yml
```

---

## Features

### Phase 1: Network Emulation
- **5 topology types**: Linear, Tree, Fat-Tree (k-port), Spine-Leaf, Custom JSON
- Configurable: bandwidth, latency, packet loss per link
- NetworkX graph with automatic visualization data

### Phase 2: SDN Controller
- Ryu OpenFlow 1.3 controller with LLDP topology discovery
- Async REST client for topology, flows, and port statistics
- MAC learning L2 switch with path installation

### Phase 3: RL Environment
- `SDNRoutingEnv` — fully compliant with Gymnasium API
- **State**: link utilization, latency, packet loss, queue occupancy, flow demands
- **Actions**: multi-discrete path selection per flow
- **Reward**: `throughput_gain - λ₁·latency - λ₂·congestion - λ₃·packet_loss`

### Phase 4: RL Agents
- **DQN**: Dueling network + double Q-learning + prioritized replay
- **PPO**: Actor-Critic with GAE-Lambda, shared trunk + per-flow policy heads
- TensorBoard-compatible training logs, checkpointing

### Phase 5: Traffic Engineering
- Elephant/Mice flows, bursty traffic, gravity model, diurnal pattern
- Dynamic load balancing, congestion-aware rerouting

### Phase 6: Dashboard
| Page | Description |
|------|-------------|
| Topology | D3.js network graph with congestion heatmap |
| Live Metrics | Real-time charts via WebSocket |
| Active Flows | Flow table with elephant/mice classification |
| RL Training | Start/stop DQN or PPO training |
| Train Progress | Learning curves, reward plots |
| Evaluation | Multi-agent comparison charts |
| Reports | Export JSON/CSV/PDF |
| AI Copilot | Natural language network Q&A |

### Phase 7: Evaluation
Compares: **DQN vs PPO vs Shortest Path vs ECMP**
- Average latency, throughput, packet loss, convergence time

### Phase 8: Reports
- JSON, CSV, PDF export
- Topology summary, training stats, performance metrics

---

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker & Docker Compose (for full stack)
- PostgreSQL 16 (or use Docker)

### 1. Docker (Recommended)

```bash
# Clone the repo
git clone https://github.com/your-username/rl-sdn-traffic-engineering
cd rl-sdn-traffic-engineering

# Start the full stack
docker compose up -d

# Optional: with Ollama AI copilot (requires GPU)
docker compose --profile ai up -d

# Access:
# Dashboard: http://localhost:3000
# API docs:  http://localhost:8000/api/v1/docs
```

### 2. Local Development

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://sdn:sdn_password@localhost:5432/sdn_db"
export DEBUG=true

# Run
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## Training Guide

### Via Dashboard
1. Open `http://localhost:3000`
2. Go to **Topology** → create a `spine_leaf` topology (2 spine, 4 leaf, 8 hosts)
3. Go to **RL Training** → select DQN or PPO → set timesteps → click **Train**
4. Monitor progress in **Train Progress** page

### Via CLI

```bash
# Train DQN
python experiments/scripts/train_dqn.py \
    --topology spine_leaf \
    --num-switches 6 \
    --num-hosts 8 \
    --timesteps 500000 \
    --lr 1e-4

# Train PPO
python experiments/scripts/train_ppo.py \
    --topology fat_tree \
    --k 4 \
    --timesteps 1000000

# Evaluate and compare
python experiments/scripts/evaluate.py \
    --topology spine_leaf \
    --dqn-model models/dqn_model.pt \
    --ppo-model models/ppo_model.pt \
    --episodes 20 \
    --output results/comparison.json
```

---

## Evaluation Results (Example)

| Agent | Avg Reward | Latency (ms) | Throughput (%) | Packet Loss |
|-------|-----------|-------------|---------------|------------|
| Shortest Path | 0.31 | 18.4 | 42.1 | 0.021% |
| ECMP | 0.44 | 14.2 | 58.7 | 0.009% |
| **DQN** | **0.61** | **10.8** | **71.3%** | **0.003%** |
| **PPO** | **0.67** | **9.9** | **75.8%** | **0.002%** |

PPO achieves **~75% throughput improvement** and **46% latency reduction** vs. shortest-path.

---

## API Reference

### Topology
```
POST   /api/v1/topology/            Create topology
GET    /api/v1/topology/            List topologies
GET    /api/v1/topology/{id}/graph  Get graph data
POST   /api/v1/topology/{id}/activate  Set active
```

### Metrics
```
GET    /api/v1/metrics/summary      Current network summary
GET    /api/v1/metrics/links        Per-link metrics
GET    /api/v1/metrics/{id}/congestion  Congestion heatmap
```

### RL
```
POST   /api/v1/rl/train             Start training session
POST   /api/v1/rl/train/{id}/stop   Stop training
GET    /api/v1/rl/sessions          List sessions
GET    /api/v1/rl/sessions/{id}     Training progress
POST   /api/v1/rl/evaluate          Run evaluation
GET    /api/v1/rl/compare/{topo_id} Comparison results
```

### WebSocket
```
WS     /ws/metrics                  Live metrics stream
WS     /ws/training/{session_id}    Training progress stream
```

### AI Copilot
```
POST   /api/v1/copilot/query        Ask a network question
GET    /api/v1/copilot/history      Query history
```

---

## Testing

```bash
cd backend

# Unit tests
pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=app --cov-report=html
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async) |
| RL | PyTorch, Gymnasium, NumPy |
| Controller | Ryu 4.x, OpenFlow 1.3 |
| Network sim | Mininet, NetworkX |
| Frontend | React 18, TypeScript, TailwindCSS |
| Charts | Recharts, D3.js |
| Database | PostgreSQL 16, asyncpg |
| Caching | Redis 7 |
| AI Copilot | Ollama + Llama 3.2 |
| Deployment | Docker, Docker Compose |
| CI/CD | GitHub Actions |

---

## Screenshots

> Add screenshots of your running dashboard here.

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Citation

If you use this project in research, please cite:

```bibtex
@software{rl_sdn_traffic_engineering,
  title  = {RL-SDN Traffic Engineering},
  author = {Your Name},
  year   = {2025},
  url    = {https://github.com/your-username/rl-sdn-traffic-engineering}
}
```
