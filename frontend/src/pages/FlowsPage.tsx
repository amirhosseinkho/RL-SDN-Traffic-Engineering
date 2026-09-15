import { useEffect, useState } from 'react';
import { flowsApi, topologyApi } from '../services/api';
import type { Flow, Topology } from '../types';
import { GitBranch, Fish, Zap } from 'lucide-react';

export function FlowsPage() {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [stats, setStats] = useState<{
    total_active_flows: number;
    elephant_flows: number;
    mice_flows: number;
    total_bandwidth_mbps: number;
    avg_bandwidth_mbps: number;
  } | null>(null);
  const [topologies, setTopologies] = useState<Topology[]>([]);
  const [selectedTopo, setSelectedTopo] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    topologyApi.list().then((list) => {
      setTopologies(list);
      if (list.length > 0) setSelectedTopo(list[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedTopo) return;
    setLoading(true);
    Promise.all([
      flowsApi.list(selectedTopo),
      flowsApi.stats(selectedTopo),
    ])
      .then(([f, s]) => { setFlows(f); setStats(s); })
      .finally(() => setLoading(false));
  }, [selectedTopo]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <GitBranch size={20} className="text-blue-400" />
          Active Flows
        </h1>
        <select
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm"
          value={selectedTopo}
          onChange={(e) => setSelectedTopo(e.target.value)}
        >
          {topologies.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: 'Active Flows', value: stats.total_active_flows, color: 'text-blue-400' },
            { label: 'Elephant Flows', value: stats.elephant_flows, color: 'text-orange-400', icon: Fish },
            { label: 'Mice Flows', value: stats.mice_flows, color: 'text-emerald-400', icon: Zap },
            { label: 'Total BW (Mbps)', value: stats.total_bandwidth_mbps.toFixed(1), color: 'text-violet-400' },
            { label: 'Avg BW (Mbps)', value: stats.avg_bandwidth_mbps.toFixed(2), color: 'text-amber-400' },
          ].map(({ label, value, color, icon: Icon }) => (
            <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
              <p className="text-xs text-slate-400 mb-1">{label}</p>
              <div className="flex items-center gap-1.5">
                {Icon && <Icon size={14} className={color} />}
                <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Flow table */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-700">
          <h2 className="text-sm font-semibold text-slate-200">Flow Table</h2>
        </div>
        {loading ? (
          <div className="p-8 text-center text-slate-500">Loading flows...</div>
        ) : flows.length === 0 ? (
          <div className="p-8 text-center text-slate-500">
            <GitBranch size={32} className="mx-auto mb-2 opacity-30" />
            <p>No active flows. Start a simulation to generate traffic.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b border-slate-700 bg-slate-900/50">
                  <th className="text-left px-5 py-3">Flow ID</th>
                  <th className="text-left px-4 py-3">Source</th>
                  <th className="text-left px-4 py-3">Destination</th>
                  <th className="text-left px-4 py-3">Protocol</th>
                  <th className="text-right px-4 py-3">BW (Mbps)</th>
                  <th className="text-center px-4 py-3">Type</th>
                  <th className="text-center px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {flows.map((flow) => (
                  <tr key={flow.id} className="border-b border-slate-800 hover:bg-slate-900/40">
                    <td className="px-5 py-3 font-mono text-xs text-slate-400">{flow.flow_id}</td>
                    <td className="px-4 py-3 text-white">{flow.src_host}</td>
                    <td className="px-4 py-3 text-white">{flow.dst_host}</td>
                    <td className="px-4 py-3 text-slate-300">{flow.protocol || '—'}</td>
                    <td className="px-4 py-3 text-right font-mono text-white">{flow.bandwidth_mbps.toFixed(2)}</td>
                    <td className="px-4 py-3 text-center">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          flow.is_elephant
                            ? 'bg-orange-900/50 text-orange-400'
                            : 'bg-emerald-900/50 text-emerald-400'
                        }`}
                      >
                        {flow.is_elephant ? '🐘 Elephant' : '🐭 Mice'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          flow.is_active
                            ? 'bg-blue-900/50 text-blue-400'
                            : 'bg-slate-700 text-slate-500'
                        }`}
                      >
                        {flow.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
