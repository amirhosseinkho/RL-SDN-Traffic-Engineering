# System Architecture

## Overview

> Status: the RL core, the backend and the dashboard run. The Ryu path is untested, and there is
> no Mininet integration. See [../STATUS.md](../STATUS.md).

The intended design is layered:

```
┌─────────────────────────────────────────────────────────┐
│                   React Dashboard                        │
│  Topology | Metrics | Flows | Training | Copilot        │
└───────────────────┬─────────────────────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼─────────────────────────────────────┐
│                 FastAPI Backend                          │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌─────────────┐ │
│  │Topology  │ │Metrics   │ │  RL    │ │  AI Copilot │ │
│  │Generator │ │Collector │ │Trainer │ │  (Ollama)   │ │
│  └──────────┘ └──────────┘ └────────┘ └─────────────┘ │
└─────────────┬──────────────────────────────────────────┘
              │
   ┌──────────▼──────────┐    ┌──────────────────────────┐
   │   RL Environment     │    │    Ryu SDN Controller    │
   │  (Gymnasium,         │    │   (OpenFlow 1.3)         │
   │   NetworkX sim)      │    │   REST API               │
   │  DQN / PPO Agents   │    │   [not verified]         │
   └──────────────────────┘    └──────────────────────────┘
```

The RL environment is self-contained: it simulates link load, queueing, latency and loss on a
NetworkX graph and does not read from or write to Ryu. Connecting the agents to a live network
(installing their paths on switches and emulating the network in Mininet) is planned, not implemented.

## Component Design

### Backend (Clean Architecture)

```
app/
├── config.py           # Settings boundary
├── main.py             # Composition root
├── api/                # Interface adapters (FastAPI)
├── database/           # Infrastructure (SQLAlchemy, Pydantic)
├── controller/         # Infrastructure (Ryu HTTP client)
├── topology/           # Domain: topology generation
├── rl/                 # Domain: RL training
├── monitoring/         # Domain: metrics collection
└── simulation/         # Domain: traffic + evaluation
```

### RL Environment State Space

```
Observation vector (obs_dim = num_links × 4 + max_flows × 2 + 3):

Links (per link):
  [0] utilization     ∈ [0, 1]
  [1] latency_norm    ∈ [0, 1]  (latency / 50ms)
  [2] packet_loss     ∈ [0, 1]  (loss / 5%)
  [3] queue_occupancy ∈ [0, 1]

Flows (per flow, padded to max_flows):
  [0] demand_norm     ∈ [0, 1]  (demand / 200 Mbps)
  [1] active          ∈ {0, 1}

Global:
  [0] avg_utilization ∈ [0, 1]
  [1] max_utilization ∈ [0, 1]
  [2] congestion_ratio ∈ [0, 1]
```

### Action Space

Multi-discrete: `[max_paths] × max_flows`

Each action selects one of K pre-computed shortest paths for each active flow.
K=4 by default (k-shortest paths via NetworkX).

### Reward Function

```
reward = w₁ · throughput_gain
       - w₂ · latency_penalty
       - w₃ · congestion_penalty
       - w₄ · packet_loss_penalty

where:
  throughput_gain     = avg_util × (1 - max(0, max_util - 0.9))
  latency_penalty     = min(1, avg_latency_ms / 50)
  congestion_penalty  = congestion_ratio   (share of links above 0.8 utilization)
  packet_loss_penalty = min(1, avg_loss / 5)

(see SDNRoutingEnv._compute_reward in backend/app/rl/environment.py)

Default weights: w₁=1.0, w₂=0.3, w₃=0.5, w₄=0.4
```

## Data Flow

RL training and evaluation (verified with the CLI scripts):

```
1. TopologyGenerator builds the graph
2. SDNRoutingEnv generates synthetic flows and simulates link state
3. Agent selects one of K paths per flow → env updates utilization → reward computed
4. Training loop → model saved to models/ → loaded by evaluate.py
5. Evaluator compares agents with shortest-path, ECMP and random baselines in the same simulation
```

Monitoring path:

```
1. MetricsCollector tries Ryu's REST API for links and port stats every
   metrics_collection_interval (1.0 s in config.py)            [not verified]
2. If Ryu is unreachable, it advances a simulation of the active topology by
   one step (shortest-path routing) and reads its link state  [verified]
3. Snapshots are broadcast to the dashboard over /ws/metrics   [verified]
```

Activating a topology (`POST /topology/{id}/activate`, or the active topology at startup) sets
which topology the collector simulates.

## Database Schema

```sql
topologies       -- Network topology definitions
switches         -- Switch nodes with DPIDs
links            -- Inter-switch links with capacity/delay
flows            -- Active network flows (elephant/mice)
link_metrics     -- Time-series link utilization data
training_sessions-- RL agent training runs
training_episodes-- Per-episode metrics during training
evaluation_results-- Comparative evaluation results
copilot_queries  -- AI copilot query history
```
