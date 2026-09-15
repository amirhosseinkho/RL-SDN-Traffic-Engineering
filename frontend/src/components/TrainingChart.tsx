import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { TrainingEpisode } from '../types';

interface Props {
  episodes: TrainingEpisode[];
  agentType: string;
}

export function TrainingChart({ episodes, agentType }: Props) {
  const data = episodes
    .slice()
    .sort((a, b) => a.episode_number - b.episode_number)
    .map((ep) => ({
      episode: ep.episode_number,
      reward: parseFloat(ep.total_reward.toFixed(4)),
      latency: parseFloat(ep.avg_latency_ms.toFixed(2)),
      utilization: parseFloat((ep.avg_link_utilization * 100).toFixed(1)),
      loss: parseFloat((ep.policy_loss ?? 0).toFixed(6)),
    }));

  const isOrange = agentType === 'ppo';
  const lineColor = isOrange ? '#f97316' : '#3b82f6';

  return (
    <div className="space-y-6">
      {/* Reward curve */}
      <div>
        <h3 className="text-sm font-semibold text-slate-300 mb-3">Episode Reward</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="episode" stroke="#64748b" fontSize={11} />
            <YAxis stroke="#64748b" fontSize={11} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
              labelStyle={{ color: '#94a3b8' }}
            />
            <Line
              type="monotone"
              dataKey="reward"
              stroke={lineColor}
              strokeWidth={2}
              dot={false}
              name="Reward"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Latency & Utilization */}
      <div>
        <h3 className="text-sm font-semibold text-slate-300 mb-3">Network Performance</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="episode" stroke="#64748b" fontSize={11} />
            <YAxis stroke="#64748b" fontSize={11} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
            />
            <Legend />
            <Line type="monotone" dataKey="latency" stroke="#f59e0b" strokeWidth={2} dot={false} name="Latency (ms)" />
            <Line type="monotone" dataKey="utilization" stroke="#22c55e" strokeWidth={2} dot={false} name="Utilization (%)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
