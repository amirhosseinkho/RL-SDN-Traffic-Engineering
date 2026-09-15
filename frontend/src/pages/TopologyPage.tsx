import { useEffect, useState } from 'react';
import { topologyApi } from '../services/api';
import { TopologyGraph } from '../components/TopologyGraph';
import { useNetworkStore } from '../store';
import type { Topology, TopologyConfig, GraphData } from '../types';
import { Plus, Cpu, CheckCircle } from 'lucide-react';

const defaultConfig: TopologyConfig = {
  topology_type: 'spine_leaf',
  num_switches: 6,
  num_hosts: 8,
  bandwidth: 100,
  latency: 5,
  loss: 0,
  num_spine: 2,
  num_leaf: 4,
  name: 'my-topology',
};

export function TopologyPage() {
  const { topologies, setTopologies, linkMetrics } = useNetworkStore();
  const [selected, setSelected] = useState<Topology | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [config, setConfig] = useState<TopologyConfig>(defaultConfig);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    topologyApi.list().then(setTopologies).catch(() => {});
  }, [setTopologies]);

  const loadGraph = async (topo: Topology) => {
    setSelected(topo);
    try {
      const g = await topologyApi.graph(topo.id);
      setGraphData({ nodes: g.nodes, edges: g.edges });
    } catch {
      setGraphData(topo.graph_data);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const topo = await topologyApi.create(config);
      const updated = await topologyApi.list();
      setTopologies(updated);
      await loadGraph(topo);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  };

  const handleActivate = async (id: string) => {
    await topologyApi.activate(id);
    const updated = await topologyApi.list();
    setTopologies(updated);
  };

  return (
    <div className="flex gap-6 h-full">
      {/* Sidebar */}
      <div className="w-72 shrink-0 flex flex-col gap-4 overflow-y-auto">
        {/* Create form */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
            <Plus size={14} />
            New Topology
          </h2>
          <div className="space-y-3 text-sm">
            <div>
              <label className="text-slate-400 text-xs mb-1 block">Name</label>
              <input
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white text-sm"
                value={config.name}
                onChange={(e) => setConfig({ ...config, name: e.target.value })}
              />
            </div>
            <div>
              <label className="text-slate-400 text-xs mb-1 block">Type</label>
              <select
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white text-sm"
                value={config.topology_type}
                onChange={(e) => setConfig({ ...config, topology_type: e.target.value as any })}
              >
                <option value="linear">Linear</option>
                <option value="tree">Tree</option>
                <option value="fat_tree">Fat-Tree</option>
                <option value="spine_leaf">Spine-Leaf</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-slate-400 text-xs mb-1 block">Switches</label>
                <input
                  type="number"
                  min={2}
                  max={64}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white text-sm"
                  value={config.num_switches}
                  onChange={(e) => setConfig({ ...config, num_switches: +e.target.value })}
                />
              </div>
              <div>
                <label className="text-slate-400 text-xs mb-1 block">Hosts</label>
                <input
                  type="number"
                  min={2}
                  max={256}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white text-sm"
                  value={config.num_hosts}
                  onChange={(e) => setConfig({ ...config, num_hosts: +e.target.value })}
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-slate-400 text-xs mb-1 block">BW (Mbps)</label>
                <input
                  type="number"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm"
                  value={config.bandwidth}
                  onChange={(e) => setConfig({ ...config, bandwidth: +e.target.value })}
                />
              </div>
              <div>
                <label className="text-slate-400 text-xs mb-1 block">Lat (ms)</label>
                <input
                  type="number"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm"
                  value={config.latency}
                  onChange={(e) => setConfig({ ...config, latency: +e.target.value })}
                />
              </div>
              <div>
                <label className="text-slate-400 text-xs mb-1 block">Loss (%)</label>
                <input
                  type="number"
                  step="0.1"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm"
                  value={config.loss}
                  onChange={(e) => setConfig({ ...config, loss: +e.target.value })}
                />
              </div>
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button
              onClick={handleCreate}
              disabled={creating}
              className="w-full py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-white text-sm font-medium transition-colors"
            >
              {creating ? 'Generating...' : 'Generate Topology'}
            </button>
          </div>
        </div>

        {/* Topology list */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-200 mb-3">Saved Topologies</h2>
          <div className="space-y-2">
            {topologies.length === 0 && (
              <p className="text-slate-500 text-xs text-center py-4">No topologies yet</p>
            )}
            {topologies.map((t) => (
              <div
                key={t.id}
                onClick={() => loadGraph(t)}
                className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                  selected?.id === t.id
                    ? 'border-blue-500 bg-blue-950'
                    : 'border-slate-700 bg-slate-900 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-white font-medium truncate">{t.name}</span>
                  {t.is_active && <CheckCircle size={12} className="text-green-400 shrink-0" />}
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Cpu size={10} />
                  <span>{t.topology_type}</span>
                  <span>·</span>
                  <span>{t.num_switches}s/{t.num_hosts}h</span>
                </div>
                {selected?.id === t.id && !t.is_active && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleActivate(t.id); }}
                    className="mt-2 w-full text-xs py-1 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors"
                  >
                    Set Active
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Graph */}
      <div className="flex-1">
        {graphData ? (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-white">{selected?.name}</h2>
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <span>{graphData.nodes.filter(n => n.node_type === 'switch').length} switches</span>
                <span>·</span>
                <span>{graphData.nodes.filter(n => n.node_type === 'host').length} hosts</span>
                <span>·</span>
                <span>{graphData.edges.length} links</span>
              </div>
            </div>
            <TopologyGraph
              nodes={graphData.nodes}
              edges={graphData.edges}
              linkMetrics={linkMetrics}
              height={560}
            />
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-slate-500">
            <div className="text-center">
              <Network size={48} className="mx-auto mb-4 opacity-30" />
              <p>Select or create a topology to visualize</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
