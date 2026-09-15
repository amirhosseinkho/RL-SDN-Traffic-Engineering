import { useEffect, useState } from 'react';
import { reportsApi, topologyApi, rlApi } from '../services/api';
import type { Topology, TrainingSession } from '../types';
import { FileText, Download } from 'lucide-react';

export function ReportsPage() {
  const [topologies, setTopologies] = useState<Topology[]>([]);
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [selectedTopo, setSelectedTopo] = useState('');
  const [selectedSessions, setSelectedSessions] = useState<string[]>([]);
  const [format, setFormat] = useState<'json' | 'csv' | 'pdf'>('json');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([topologyApi.list(), rlApi.listSessions()]).then(([t, s]) => {
      setTopologies(t);
      setSessions(s);
      if (t.length > 0) setSelectedTopo(t[0].id);
    });
  }, []);

  const handleGenerate = async () => {
    if (!selectedTopo) return;
    setGenerating(true);
    setError(null);
    try {
      const resp = await reportsApi.generate({
        topology_id: selectedTopo,
        session_ids: selectedSessions,
        format,
      });
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sdn_report.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const toggleSession = (id: string) => {
    setSelectedSessions((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <FileText size={20} className="text-slate-400" />
        Report Generation
      </h1>

      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-5">
        <div>
          <label className="text-slate-400 text-sm mb-2 block font-medium">Topology</label>
          <select
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-white"
            value={selectedTopo}
            onChange={(e) => setSelectedTopo(e.target.value)}
          >
            {topologies.map((t) => (
              <option key={t.id} value={t.id}>{t.name} ({t.topology_type})</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-slate-400 text-sm mb-2 block font-medium">
            Include Training Sessions (optional)
          </label>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {sessions.length === 0 ? (
              <p className="text-slate-500 text-sm">No training sessions available</p>
            ) : (
              sessions.map((s) => (
                <label key={s.id} className="flex items-center gap-3 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={selectedSessions.includes(s.id)}
                    onChange={() => toggleSession(s.id)}
                    className="accent-blue-500 w-4 h-4"
                  />
                  <div>
                    <span className="text-sm text-white uppercase font-semibold">{s.agent_type}</span>
                    <span className="text-xs text-slate-400 ml-2">
                      {s.status} · {s.current_timestep.toLocaleString()} steps
                    </span>
                  </div>
                </label>
              ))
            )}
          </div>
        </div>

        <div>
          <label className="text-slate-400 text-sm mb-2 block font-medium">Export Format</label>
          <div className="flex gap-3">
            {(['json', 'csv', 'pdf'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={`px-5 py-2 rounded-lg text-sm font-medium border transition-colors ${
                  format === f
                    ? 'bg-blue-600 border-blue-500 text-white'
                    : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          onClick={handleGenerate}
          disabled={generating || !selectedTopo}
          className="w-full flex items-center justify-center gap-2 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-xl text-white font-medium transition-colors"
        >
          <Download size={16} />
          {generating ? 'Generating...' : `Export ${format.toUpperCase()} Report`}
        </button>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-200 mb-3">Report Contents</h2>
        <ul className="space-y-2 text-sm text-slate-400">
          {[
            'Topology summary (type, switches, hosts)',
            'Evaluation results for all tested agents',
            'Performance comparison (latency, throughput, packet loss)',
            'Training session statistics (if sessions selected)',
            'Routing decision logs',
            'Improvement metrics over shortest-path baseline',
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <span className="text-blue-400 mt-0.5">·</span>
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
