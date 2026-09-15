# System Architecture

## Overview

The RL-SDN Traffic Engineering platform is a layered system:

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
   │  (Gymnasium)         │    │   (OpenFlow 1.3)         │
   │  DQN / PPO Agents   │    │   REST API + WebSocket   │
   └──────────────────────┘    └────────────┬─────────────┘
                                             │ OpenFlow
                                ┌────────────▼─────────────┐
                                │    Mininet Network       │
                                │  (Virtual switches/hosts)│
                                └──────────────────────────┘
```

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
  throughput_gain   = avg_util × (1 - max(0, max_util - 0.9))
  latency_penalty   = normalized_latency × w₂
  congestion_penalty = congestion_ratio × w₃
  packet_loss_penalty = normalized_loss × w₄

Default weights: w₁=1.0, w₂=0.3, w₃=0.5, w₄=0.4
```

## Data Flow

```
1. Traffic arrives → Mininet → Ryu learns topology via LLDP
2. Ryu REST API → MetricsCollector polls port stats every 1s
3. MetricsCollector → broadcasts via WebSocket to dashboard
4. RL agent observes state from SDNRoutingEnv
5. Agent selects routing paths → env applies routing → reward computed
6. Training loop → model saved → can be loaded for evaluation
```

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
