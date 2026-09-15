import { create } from 'zustand';
import type {
  Topology,
  MetricsSummary,
  LinkMetric,
  Flow,
  TrainingSession,
  EvaluationResult,
} from '../types';

interface NetworkState {
  // Topology
  topologies: Topology[];
  activeTopology: Topology | null;
  setTopologies: (topologies: Topology[]) => void;
  setActiveTopology: (topology: Topology | null) => void;

  // Metrics
  metricsSummary: MetricsSummary | null;
  linkMetrics: LinkMetric[];
  isConnected: boolean;
  setMetricsSummary: (summary: MetricsSummary) => void;
  setLinkMetrics: (metrics: LinkMetric[]) => void;
  setConnected: (connected: boolean) => void;

  // Flows
  flows: Flow[];
  setFlows: (flows: Flow[]) => void;

  // RL
  trainingSessions: TrainingSession[];
  activeSessions: TrainingSession[];
  evaluationResults: EvaluationResult[];
  setTrainingSessions: (sessions: TrainingSession[]) => void;
  addTrainingSession: (session: TrainingSession) => void;
  updateSessionStatus: (sessionId: string, updates: Partial<TrainingSession>) => void;
  setEvaluationResults: (results: EvaluationResult[]) => void;

  // UI
  selectedTopologyId: string | null;
  setSelectedTopologyId: (id: string | null) => void;
}

export const useNetworkStore = create<NetworkState>((set) => ({
  // Topology
  topologies: [],
  activeTopology: null,
  setTopologies: (topologies) => set({ topologies }),
  setActiveTopology: (activeTopology) => set({ activeTopology }),

  // Metrics
  metricsSummary: null,
  linkMetrics: [],
  isConnected: false,
  setMetricsSummary: (metricsSummary) => set({ metricsSummary }),
  setLinkMetrics: (linkMetrics) => set({ linkMetrics }),
  setConnected: (isConnected) => set({ isConnected }),

  // Flows
  flows: [],
  setFlows: (flows) => set({ flows }),

  // RL
  trainingSessions: [],
  activeSessions: [],
  evaluationResults: [],
  setTrainingSessions: (sessions) =>
    set({
      trainingSessions: sessions,
      activeSessions: sessions.filter((s) => s.status === 'running'),
    }),
  addTrainingSession: (session) =>
    set((state) => ({
      trainingSessions: [session, ...state.trainingSessions],
      activeSessions:
        session.status === 'running'
          ? [session, ...state.activeSessions]
          : state.activeSessions,
    })),
  updateSessionStatus: (sessionId, updates) =>
    set((state) => ({
      trainingSessions: state.trainingSessions.map((s) =>
        s.id === sessionId ? { ...s, ...updates } : s
      ),
      activeSessions: state.trainingSessions
        .map((s) => (s.id === sessionId ? { ...s, ...updates } : s))
        .filter((s) => s.status === 'running'),
    })),
  setEvaluationResults: (evaluationResults) => set({ evaluationResults }),

  // UI
  selectedTopologyId: null,
  setSelectedTopologyId: (selectedTopologyId) => set({ selectedTopologyId }),
}));
