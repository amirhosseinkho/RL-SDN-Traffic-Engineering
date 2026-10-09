import { useEffect, useState } from 'react';
import { rlApi, topologyApi } from '../services/api';
import type { Topology, ComparisonResult } from '../types';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Trophy, BarChart2 } from 'lucide-react';

const AGENT_COLORS: Record<string, string> = {
  dqn: '#3b82f6',
  ppo: '#f97316',
  shortest_path: '#64748b',
  ecmp: '#8b5cf6',
};

export function EvaluationPage() {
  const [topologies, setTopologies] = useState<Topology[]>([]);
  const [selectedTopo, setSelectedTopo] = useState('');
  const [numEpisodes, setNumEpisodes] = useState(5);
  const [selectedAgents, setSelectedAgents] = useState<string[]>(['dqn', 'ppo', 'shortest_path', 'ecmp']);
  const [running, setRunning] = useState(false);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    topologyApi.list().then((list) => {
      setTopologies(list);
      if (list.length > 0) setSelectedTopo(list[0].id);
    });
  }, []);

  useEffect(() => {
    if (selectedTopo) {
      rlApi.compare(selectedTopo).then(setComparison).catch(() => {});
    }
  }, [selectedTopo]);

  const handleEvaluate = async () => {
    if (!selectedTopo) return;
    setRunning(true);
    setError(null);
    try {
      await rlApi.evaluate({
        topology_id: selectedTopo,
        agents: selectedAgents,
        num_episodes: numEpisodes,
      });
      const comp = await rlApi.compare(selectedTopo);
      setComparison(comp);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const toggleAgent = (agent: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agent) ? prev.filter((a) => a !== agent) : [...prev, agent]
    );
  };

  // Prepare chart data
  const barData = comparison?.results.map((r) => ({
    name: r.agent_type.replace('_', ' ').toUpperCase(),
    'Throughput (Mbps)': parseFloat(r.avg_throughput_mbps.toFixed(2)),
    'Latency (ms)': parseFloat(r.avg_latency_ms.toFixed(2)),
    'Packet Loss %': parseFloat((r.avg_packet_loss * 100).toFixed(4)),
    'Utilization %': parseFloat((r.avg_link_utilization * 100).toFixed(1)),
  }));

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <BarChart2 size={20} className="text-violet-400" />
        Performance Comparison
      </h1>

      {/* Controls */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-slate-400 text-xs mb-1.5 block">Topology</label>
            <select
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm"
              value={selectedTopo}
              onChange={(e) => setSelectedTopo(e.target.value)}
            >
              {topologies.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-slate-400 text-xs mb-1.5 block">Episodes: {numEpisodes}</label>
            <input
              type="range" min={3} max={50} value={numEpisodes}
              onChange={(e) => setNumEpisodes(+e.target.value)}
              className="accent-violet-500 w-32"
            />
          </div>

          <div>
            <label className="text-slate-400 text-xs mb-1.5 block">Agents</label>
            <div className="flex gap-2">
              {['dqn', 'ppo', 'shortest_path', 'ecmp'].map((a) => (
                <button
                  key={a}
                  onClick={() => toggleAgent(a)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    selectedAgents.includes(a)
                      ? 'text-white border-transparent'
                      : 'text-slate-400 border-slate-700 bg-slate-900'
                  }`}
                  style={selectedAgents.includes(a) ? { backgroundColor: AGENT_COLORS[a], borderColor: AGENT_COLORS[a] } : {}}
                >
                  {a.replace('_', ' ').toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleEvaluate}
            disabled={running || !selectedTopo}
            className="px-5 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg text-white text-sm font-medium transition-colors"
          >
            {running ? 'Running...' : 'Run Evaluation'}
          </button>
        </div>
        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
      </div>

      {comparison && (
        <>
          {/* Winner banner */}
          <div className="bg-gradient-to-r from-amber-900/40 to-amber-800/20 border border-amber-700/50 rounded-xl p-4 flex items-center gap-3">
            <Trophy size={20} className="text-amber-400 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-white">
                Best performing agent: <span className="text-amber-400 uppercase">{comparison.best_agent}</span>
              </p>
              <div className="flex gap-4 mt-1 text-xs text-slate-400">
                {Object.entries(comparison.improvement_over_shortest_path).map(([agent, improvement]) => (
                  <span key={agent}>
                    <span className="uppercase text-slate-300">{agent}</span>: {improvement > 0 ? '+' : ''}{improvement}% throughput
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Bar chart comparison */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-slate-200 mb-4">Throughput Comparison</h2>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={barData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} />
                <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                <Legend />
                <Bar dataKey="Throughput (Mbps)" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Latency & Loss */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-200 mb-4">Latency Comparison</h2>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={barData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                  <YAxis stroke="#64748b" fontSize={10} />
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                  <Bar dataKey="Latency (ms)" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Summary table */}
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-200 mb-4">Results Summary</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-400 border-b border-slate-700">
                      <th className="text-left py-2 pr-3">Agent</th>
                      <th className="text-right py-2 pr-3">Throughput</th>
                      <th className="text-right py-2 pr-3">Latency</th>
                      <th className="text-right py-2">Loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.results.map((r) => (
                      <tr key={r.id} className="border-b border-slate-800 hover:bg-slate-900/50">
                        <td className="py-2 pr-3 font-semibold uppercase" style={{ color: AGENT_COLORS[r.agent_type] }}>
                          {r.agent_type}
                        </td>
                        <td className="text-right py-2 pr-3 text-white">{r.avg_throughput_mbps.toFixed(1)} Mbps</td>
                        <td className="text-right py-2 pr-3 text-white">{r.avg_latency_ms.toFixed(1)} ms</td>
                        <td className="text-right py-2 text-white">{(r.avg_packet_loss * 100).toFixed(4)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
