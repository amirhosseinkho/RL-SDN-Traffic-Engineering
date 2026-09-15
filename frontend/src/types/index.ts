// ─── Topology ────────────────────────────────────────────────────────────────

export type TopologyType = 'linear' | 'tree' | 'fat_tree' | 'spine_leaf' | 'custom';

export interface TopologyConfig {
  topology_type: TopologyType;
  num_switches: number;
  num_hosts: number;
  bandwidth: number;
  latency: number;
  loss: number;
  k?: number;
  depth?: number;
  fanout?: number;
  num_spine?: number;
  num_leaf?: number;
  name: string;
}

export interface Topology {
  id: string;
  name: string;
  topology_type: TopologyType;
  num_switches: number;
  num_hosts: number;
  config: Record<string, unknown>;
  graph_data: GraphData | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface GraphNode {
  id: string;
  label: string;
  node_type: 'switch' | 'host';
  dpid?: number;
  ip?: string;
  position?: { x: number; y: number };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  bandwidth: number;
  latency: number;
  loss: number;
  utilization: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TopologyGraphResponse {
  topology_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ─── Metrics ─────────────────────────────────────────────────────────────────

export interface LinkMetric {
  src_dpid: number;
  dst_dpid: number;
  utilization: number;
  throughput_mbps: number;
  latency_ms: number;
  packet_loss: number;
  queue_occupancy: number;
  dropped_packets: number;
  timestamp: string;
}

export interface MetricsSummary {
  avg_utilization: number;
  max_utilization: number;
  avg_latency_ms: number;
  avg_throughput_mbps: number;
  total_throughput_mbps: number;
  avg_packet_loss: number;
  congested_links: number;
  total_links: number;
  timestamp: string;
}

// ─── Flows ───────────────────────────────────────────────────────────────────

export interface Flow {
  id: string;
  topology_id: string;
  flow_id: string;
  src_host: string;
  dst_host: string;
  src_ip?: string;
  dst_ip?: string;
  protocol?: string;
  bandwidth_mbps: number;
  path?: string[];
  is_elephant: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ─── RL ──────────────────────────────────────────────────────────────────────

export type AgentType = 'dqn' | 'ppo' | 'shortest_path' | 'ecmp';
export type TrainingStatus = 'pending' | 'running' | 'completed' | 'failed' | 'paused';

export interface TrainingSession {
  id: string;
  agent_type: AgentType;
  status: TrainingStatus;
  topology_id?: string;
  hyperparameters: Record<string, unknown>;
  total_timesteps: number;
  current_timestep: number;
  best_reward: number;
  model_path?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface TrainingEpisode {
  id: string;
  session_id: string;
  episode_number: number;
  total_reward: number;
  avg_latency_ms: number;
  avg_throughput_mbps: number;
  avg_packet_loss: number;
  avg_link_utilization: number;
  steps: number;
  epsilon?: number;
  policy_loss?: number;
  value_loss?: number;
  timestamp: string;
}

export interface TrainingProgress {
  session: TrainingSession;
  recent_episodes: TrainingEpisode[];
  progress_pct: number;
}

export interface EvaluationResult {
  id: string;
  agent_type: AgentType;
  topology_id: string;
  session_id?: string;
  avg_latency_ms: number;
  avg_throughput_mbps: number;
  avg_packet_loss: number;
  avg_link_utilization: number;
  convergence_time_s?: number;
  num_episodes: number;
  raw_metrics: Record<string, unknown>;
  created_at: string;
}

export interface ComparisonResult {
  topology_id: string;
  results: EvaluationResult[];
  best_agent: AgentType;
  improvement_over_shortest_path: Record<string, number>;
}

// ─── WebSocket ───────────────────────────────────────────────────────────────

export interface WSMessage<T = unknown> {
  event: string;
  data: T;
  timestamp?: string;
}

export interface TrainingUpdate {
  session_id: string;
  status: TrainingStatus;
  current_timestep: number;
  total_timesteps: number;
  progress_pct: number;
  best_reward: number;
  latest_episode?: {
    total_reward: number;
    avg_latency_ms: number;
    episode_number: number;
  } | null;
}

// ─── Copilot ─────────────────────────────────────────────────────────────────

export interface CopilotResponse {
  query: string;
  response: string;
  context_used: boolean;
  model_used: string;
  latency_ms: number;
}
