import { useEffect, useState } from 'react';
import { rlApi, topologyApi } from '../services/api';
import { useNetworkStore } from '../store';
import type { Topology, AgentType } from '../types';
import { Play, Square, Brain } from 'lucide-react';

interface TrainConfig {
  agent_type: AgentType;
  topology_id: string;
  total_timesteps: number;
  learning_rate: number;
  batch_size: number;
  gamma: number;
}

export function TrainingPage() {
  const { trainingSessions, setTrainingSessions, addTrainingSession } = useNetworkStore();
  const [topologies, setTopologies] = useState<Topology[]>([]);
  const [config, setConfig] = useState<TrainConfig>({
    agent_type: 'dqn',
    topology_id: '',
    total_timesteps: 100000,
    learning_rate: 1e-4,
    batch_size: 64,
    gamma: 0.99,
  });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    topologyApi.list().then(setTopologies).catch(() => {});
    rlApi.listSessions().then(setTrainingSessions).catch(() => {});
  }, [setTrainingSessions]);

  useEffect(() => {
    if (topologies.length > 0 && !config.topology_id) {
      setConfig((c) => ({ ...c, topology_id: topologies[0].id }));
    }
  }, [topologies, config.topology_id]);

  const handleStart = async () => {
    if (!config.topology_id) return;
    setStarting(true);
    setError(null);
    try {
      const session = await rlApi.startTraining({
        agent_type: config.agent_type,
        topology_id: config.topology_id,
        total_timesteps: config.total_timesteps,
        hyperparameters: {
          learning_rate: config.learning_rate,
          batch_size: config.batch_size,
          gamma: config.gamma,
        },
      });
      addTrainingSession(session);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async (sessionId: string) => {
    await rlApi.stopTraining(sessionId).catch(() => {});
    const updated = await rlApi.listSessions();
    setTrainingSessions(updated);
  };

  const statusColor: Record<string, string> = {
    pending: 'text-slate-400',
    running: 'text-blue-400',
    completed: 'text-green-400',
    failed: 'text-red-400',
    paused: 'text-amber-400',
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Brain size={20} className="text-blue-400" />
        RL Agent Training
      </h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Config panel */}
        <div className="lg:col-span-1 bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-4">Training Configuration</h2>
          <div className="space-y-4 text-sm">
            <div>
              <label className="text-slate-400 text-xs mb-1.5 block">Agent Algorithm</label>
              <div className="grid grid-cols-2 gap-2">
                {(['dqn', 'ppo'] as AgentType[]).map((a) => (
                  <button
                    key={a}
                    onClick={() => setConfig({ ...config, agent_type: a })}
                    className={`py-2 rounded-lg text-sm font-medium border transition-colors ${
                      config.agent_type === a
                        ? 'bg-blue-600 border-blue-500 text-white'
                        : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600'
                    }`}
                  >
                    {a.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-slate-400 text-xs mb-1.5 block">Topology</label>
              <select
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm"
                value={config.topology_id}
                onChange={(e) => setConfig({ ...config, topology_id: e.target.value })}
              >
                {topologies.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.topology_type})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-slate-400 text-xs mb-1.5 block">
                Total Timesteps: {config.total_timesteps.toLocaleString()}
              </label>
              <input
                type="range"
                min={10000}
                max={1000000}
                step={10000}
                value={config.total_timesteps}
                onChange={(e) => setConfig({ ...config, total_timesteps: +e.target.value })}
                className="w-full accent-blue-500"
              />
              <div className="flex justify-between text-xs text-slate-500 mt-1">
                <span>10K</span><span>1M</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-slate-400 text-xs mb-1.5 block">Learning Rate</label>
                <input
                  type="number"
                  step="0.00001"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm"
                  value={config.learning_rate}
                  onChange={(e) => setConfig({ ...config, learning_rate: +e.target.value })}
                />
              </div>
              <div>
                <label className="text-slate-400 text-xs mb-1.5 block">Batch Size</label>
                <input
                  type="number"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm"
                  value={config.batch_size}
                  onChange={(e) => setConfig({ ...config, batch_size: +e.target.value })}
                />
              </div>
            </div>

            <div>
              <label className="text-slate-400 text-xs mb-1.5 block">Gamma (discount): {config.gamma}</label>
              <input
                type="range"
                min={0.9}
                max={0.999}
                step={0.001}
                value={config.gamma}
                onChange={(e) => setConfig({ ...config, gamma: +e.target.value })}
                className="w-full accent-blue-500"
              />
            </div>

            {error && <p className="text-red-400 text-xs">{error}</p>}

            <button
              onClick={handleStart}
              disabled={starting || !config.topology_id}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-white font-medium transition-colors"
            >
              <Play size={14} />
              {starting ? 'Starting...' : `Train ${config.agent_type.toUpperCase()}`}
            </button>
          </div>
        </div>

        {/* Sessions list */}
        <div className="lg:col-span-2 bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-4">Training Sessions</h2>
          <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
            {trainingSessions.length === 0 && (
              <div className="text-center py-8 text-slate-500">
                <Brain size={32} className="mx-auto mb-2 opacity-30" />
                <p>No training sessions yet. Start one to the left.</p>
              </div>
            )}
            {trainingSessions.map((s) => {
              const progress = s.total_timesteps > 0
                ? Math.round((s.current_timestep / s.total_timesteps) * 100)
                : 0;
              return (
                <div
                  key={s.id}
                  className="bg-slate-900 border border-slate-700 rounded-lg p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white uppercase">{s.agent_type}</span>
                      <span className={`text-xs font-medium ${statusColor[s.status] || 'text-slate-400'}`}>
                        {s.status}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-400 font-mono">{s.id.slice(0, 8)}...</span>
                      {s.status === 'running' && (
                        <button
                          onClick={() => handleStop(s.id)}
                          className="p-1 text-red-400 hover:text-red-300 transition-colors"
                          title="Stop training"
                        >
                          <Square size={12} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="mb-2">
                    <div className="flex justify-between text-xs text-slate-400 mb-1">
                      <span>{s.current_timestep.toLocaleString()} steps</span>
                      <span>{progress}%</span>
                    </div>
                    <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all duration-500"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span>Best reward: <span className="text-white font-mono">{s.best_reward?.toFixed(4) ?? '—'}</span></span>
                    {s.started_at && (
                      <span>Started: {new Date(s.started_at).toLocaleTimeString()}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
