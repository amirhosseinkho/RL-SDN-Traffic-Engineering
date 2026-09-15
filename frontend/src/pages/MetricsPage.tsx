import { useEffect, useState, useRef } from 'react';
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { useNetworkStore } from '../store';
import { MetricsCards } from '../components/MetricsCards';
import { metricsApi } from '../services/api';
import { metricsWS } from '../services/websocket';
import type { MetricsSummary, LinkMetric } from '../types';

interface MetricPoint {
  time: string;
  avg_util: number;
  max_util: number;
  latency: number;
  throughput: number;
  packet_loss: number;
}

export function MetricsPage() {
  const { metricsSummary, linkMetrics, isConnected, setMetricsSummary, setLinkMetrics, setConnected } =
    useNetworkStore();
  const [history, setHistory] = useState<MetricPoint[]>([]);
  const maxHistory = 60;

  useEffect(() => {
    // Initial fetch
    metricsApi.summary().then(setMetricsSummary).catch(() => {});
    metricsApi.links().then(setLinkMetrics).catch(() => {});

    // WebSocket streaming
    metricsWS.connect();

    const offConnected = metricsWS.on('connected', () => setConnected(true));
    const offDisconnected = metricsWS.on('disconnected', () => setConnected(false));
    const offMetrics = metricsWS.on<LinkMetric[]>('metrics_update', (data) => {
      if (!Array.isArray(data)) return;
      setLinkMetrics(data);

      const utils = data.map((d) => d.utilization);
      const latencies = data.map((d) => d.latency_ms);
      const throughputs = data.map((d) => d.throughput_mbps);
      const losses = data.map((d) => d.packet_loss);

      const avg = (arr: number[]) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
      const max = (arr: number[]) => arr.length ? Math.max(...arr) : 0;

      const point: MetricPoint = {
        time: new Date().toLocaleTimeString(),
        avg_util: parseFloat((avg(utils) * 100).toFixed(1)),
        max_util: parseFloat((max(utils) * 100).toFixed(1)),
        latency: parseFloat(avg(latencies).toFixed(2)),
        throughput: parseFloat(avg(throughputs).toFixed(2)),
        packet_loss: parseFloat((avg(losses) * 100).toFixed(4)),
      };

      setHistory((prev) => [...prev.slice(-(maxHistory - 1)), point]);

      // Build summary
      const summary: MetricsSummary = {
        avg_utilization: avg(utils),
        max_utilization: max(utils),
        avg_latency_ms: avg(latencies),
        avg_throughput_mbps: avg(throughputs),
        total_throughput_mbps: throughputs.reduce((a, b) => a + b, 0),
        avg_packet_loss: avg(losses),
        congested_links: utils.filter((u) => u > 0.8).length,
        total_links: utils.length,
        timestamp: new Date().toISOString(),
      };
      setMetricsSummary(summary);
    });

    return () => {
      offConnected();
      offDisconnected();
      offMetrics();
    };
  }, [setConnected, setLinkMetrics, setMetricsSummary]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Live Network Metrics</h1>
        <div className="flex items-center gap-2 text-sm">
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
          <span className="text-slate-400">{isConnected ? 'Live' : 'Reconnecting...'}</span>
        </div>
      </div>

      <MetricsCards summary={metricsSummary} isConnected={isConnected} />

      {/* Utilization over time */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-200 mb-4">Link Utilization Over Time</h2>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={history} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <defs>
              <linearGradient id="gradAvg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gradMax" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#ef4444" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="time" stroke="#64748b" fontSize={10} />
            <YAxis stroke="#64748b" fontSize={10} unit="%" />
            <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
            <Legend />
            <Area type="monotone" dataKey="avg_util" stroke="#3b82f6" fill="url(#gradAvg)" name="Avg %" />
            <Area type="monotone" dataKey="max_util" stroke="#ef4444" fill="url(#gradMax)" name="Max %" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Latency */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-200 mb-4">Latency (ms)</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={history} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" fontSize={10} />
              <YAxis stroke="#64748b" fontSize={10} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
              <Line type="monotone" dataKey="latency" stroke="#f59e0b" strokeWidth={2} dot={false} name="ms" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Throughput */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-200 mb-4">Avg Throughput (Mbps)</h2>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={history} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
              <defs>
                <linearGradient id="gradTp" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" fontSize={10} />
              <YAxis stroke="#64748b" fontSize={10} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
              <Area type="monotone" dataKey="throughput" stroke="#22c55e" fill="url(#gradTp)" name="Mbps" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Per-link bar chart */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-200 mb-4">Per-Link Utilization</h2>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart
            data={linkMetrics.slice(0, 20).map((m) => ({
              link: `${m.src_dpid}→${m.dst_dpid}`,
              utilization: parseFloat((m.utilization * 100).toFixed(1)),
            }))}
            margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="link" stroke="#64748b" fontSize={9} />
            <YAxis stroke="#64748b" fontSize={10} unit="%" />
            <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
            <Bar
              dataKey="utilization"
              fill="#3b82f6"
              radius={[4, 4, 0, 0]}
              name="Utilization %"
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
