import { useEffect, useState } from 'react';
import { rlApi } from '../services/api';
import { TrainingChart } from '../components/TrainingChart';
import type { TrainingProgress, TrainingSession } from '../types';
import { TrendingUp, Cpu } from 'lucide-react';

export function ProgressPage() {
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [progress, setProgress] = useState<TrainingProgress | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    rlApi.listSessions().then(setSessions).catch(() => {});
  }, []);

  const loadProgress = async (id: string) => {
    setSelected(id);
    setLoading(true);
    try {
      const p = await rlApi.getProgress(id);
      setProgress(p);
    } catch {}
    setLoading(false);
  };

  return (
    <div className="flex gap-6 h-full">
      {/* Sessions sidebar */}
      <div className="w-64 shrink-0">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">Sessions</h2>
        <div className="space-y-2">
          {sessions.length === 0 && (
            <p className="text-slate-500 text-xs text-center py-6">No sessions yet</p>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => loadProgress(s.id)}
              className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                selected === s.id
                  ? 'border-blue-500 bg-blue-950'
                  : 'border-slate-700 bg-slate-800 hover:border-slate-600'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <Cpu size={12} className="text-slate-400" />
                <span className="text-sm font-semibold text-white uppercase">{s.agent_type}</span>
              </div>
              <div className="text-xs text-slate-400 space-y-0.5">
                <p>Status: <span className={s.status === 'completed' ? 'text-green-400' : s.status === 'running' ? 'text-blue-400' : 'text-slate-400'}>{s.status}</span></p>
                <p>Steps: {s.current_timestep.toLocaleString()}/{s.total_timesteps.toLocaleString()}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Progress charts */}
      <div className="flex-1">
        <h1 className="text-xl font-bold text-white flex items-center gap-2 mb-4">
          <TrendingUp size={20} className="text-blue-400" />
          Training Progress
        </h1>

        {loading && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-8 text-center text-slate-400">
            Loading training data...
          </div>
        )}

        {!loading && progress && (
          <div className="space-y-4">
            {/* Summary */}
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: 'Progress', value: `${progress.progress_pct.toFixed(1)}%` },
                { label: 'Episodes', value: progress.recent_episodes.length },
                { label: 'Best Reward', value: progress.session.best_reward.toFixed(4) },
                { label: 'Status', value: progress.session.status },
              ].map(({ label, value }) => (
                <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
                  <p className="text-xs text-slate-400 mb-1">{label}</p>
                  <p className="text-lg font-bold text-white">{value}</p>
                </div>
              ))}
            </div>

            {/* Progress bar */}
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
              <div className="flex justify-between text-xs text-slate-400 mb-2">
                <span>{progress.session.current_timestep.toLocaleString()} / {progress.session.total_timesteps.toLocaleString()} steps</span>
                <span>{progress.progress_pct.toFixed(1)}% complete</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-600 to-blue-400 rounded-full transition-all duration-700"
                  style={{ width: `${progress.progress_pct}%` }}
                />
              </div>
            </div>

            {/* Charts */}
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-200 mb-4">Learning Curves</h2>
              <TrainingChart
                episodes={progress.recent_episodes}
                agentType={progress.session.agent_type}
              />
            </div>
          </div>
        )}

        {!loading && !progress && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center text-slate-500">
            <TrendingUp size={40} className="mx-auto mb-3 opacity-30" />
            <p>Select a training session to view its progress</p>
          </div>
        )}
      </div>
    </div>
  );
}
