import type {
  Topology,
  TopologyConfig,
  TopologyGraphResponse,
  MetricsSummary,
  LinkMetric,
  Flow,
  TrainingSession,
  TrainingProgress,
  EvaluationResult,
  ComparisonResult,
  CopilotResponse,
} from '../types';

const BASE = '/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ─── Topology ────────────────────────────────────────────────────────────────

export const topologyApi = {
  list: () => request<Topology[]>('/topology/'),
  get: (id: string) => request<Topology>(`/topology/${id}`),
  create: (config: TopologyConfig) =>
    request<Topology>('/topology/', { method: 'POST', body: JSON.stringify(config) }),
  graph: (id: string) => request<TopologyGraphResponse>(`/topology/${id}/graph`),
  activate: (id: string) =>
    request<Topology>(`/topology/${id}/activate`, { method: 'POST' }),
  delete: (id: string) =>
    request<void>(`/topology/${id}`, { method: 'DELETE' }),
};

// ─── Metrics ─────────────────────────────────────────────────────────────────

export const metricsApi = {
  summary: () => request<MetricsSummary>('/metrics/summary'),
  links: () => request<LinkMetric[]>('/metrics/links'),
  history: (topologyId: string, limit = 100) =>
    request<LinkMetric[]>(`/metrics/${topologyId}/history?limit=${limit}`),
  congestion: (topologyId: string, threshold = 0.8) =>
    request<{ congested_links: Array<{ src_dpid: number; dst_dpid: number; utilization: number; severity: string }> }>(
      `/metrics/${topologyId}/congestion?threshold=${threshold}`
    ),
};

// ─── Flows ───────────────────────────────────────────────────────────────────

export const flowsApi = {
  list: (topologyId?: string) =>
    request<Flow[]>(`/flows/${topologyId ? `?topology_id=${topologyId}` : ''}`),
  stats: (topologyId?: string) =>
    request<{
      total_active_flows: number;
      elephant_flows: number;
      mice_flows: number;
      total_bandwidth_mbps: number;
      avg_bandwidth_mbps: number;
    }>(`/flows/stats/summary${topologyId ? `?topology_id=${topologyId}` : ''}`),
  ryuFlows: () => request<{ flows: unknown }>('/flows/ryu'),
};

// ─── RL ──────────────────────────────────────────────────────────────────────

export const rlApi = {
  startTraining: (payload: {
    agent_type: string;
    topology_id: string;
    total_timesteps: number;
    hyperparameters?: Record<string, unknown>;
  }) => request<TrainingSession>('/rl/train', { method: 'POST', body: JSON.stringify(payload) }),

  stopTraining: (sessionId: string) =>
    request<TrainingSession>(`/rl/train/${sessionId}/stop`, { method: 'POST' }),

  listSessions: () => request<TrainingSession[]>('/rl/sessions'),

  getProgress: (sessionId: string) => request<TrainingProgress>(`/rl/sessions/${sessionId}`),

  evaluate: (payload: {
    topology_id: string;
    agents: string[];
    num_episodes: number;
  }) => request<EvaluationResult[]>('/rl/evaluate', { method: 'POST', body: JSON.stringify(payload) }),

  compare: (topologyId: string) => request<ComparisonResult>(`/rl/compare/${topologyId}`),
};

// ─── Reports ─────────────────────────────────────────────────────────────────

export const reportsApi = {
  generate: async (payload: {
    topology_id: string;
    session_ids: string[];
    format: 'json' | 'csv' | 'pdf';
  }) => {
    const res = await fetch(`${BASE}/reports/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Report generation failed: ${res.statusText}`);
    return res;
  },
};

// ─── Copilot ─────────────────────────────────────────────────────────────────

export const copilotApi = {
  query: (query: string, includeContext = true) =>
    request<CopilotResponse>('/copilot/query', {
      method: 'POST',
      body: JSON.stringify({ query, include_context: includeContext }),
    }),
  history: (limit = 20) => request<CopilotResponse[]>(`/copilot/history?limit=${limit}`),
};

// ─── Health ──────────────────────────────────────────────────────────────────

export const healthApi = {
  check: () => request<{ status: string; version: string }>('/health'),
};
