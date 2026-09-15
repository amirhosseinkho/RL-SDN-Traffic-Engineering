import type { MetricsSummary } from '../types';
import { Activity, Wifi, Clock, AlertTriangle, TrendingUp, Zap } from 'lucide-react';

interface Props {
  summary: MetricsSummary | null;
  isConnected: boolean;
}

function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  color,
  subtext,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  unit?: string;
  color: string;
  subtext?: string;
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex flex-col gap-2 animate-fade-in">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-400 font-medium">{label}</span>
        <Icon size={16} className={color} />
      </div>
      <div className="flex items-end gap-1">
        <span className="text-2xl font-bold text-white font-mono">{value}</span>
        {unit && <span className="text-sm text-slate-400 mb-0.5">{unit}</span>}
      </div>
      {subtext && <span className="text-xs text-slate-500">{subtext}</span>}
    </div>
  );
}

export function MetricsCards({ summary, isConnected }: Props) {
  if (!summary) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-4 h-24 animate-pulse" />
        ))}
      </div>
    );
  }

  const avgUtilPct = (summary.avg_utilization * 100).toFixed(1);
  const maxUtilPct = (summary.max_utilization * 100).toFixed(1);
  const congestionRatio = `${summary.congested_links}/${summary.total_links}`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <MetricCard
        icon={isConnected ? Wifi : AlertTriangle}
        label="Connection"
        value={isConnected ? 'Live' : 'Offline'}
        color={isConnected ? 'text-green-400' : 'text-red-400'}
        subtext="WebSocket stream"
      />
      <MetricCard
        icon={Activity}
        label="Avg Utilization"
        value={avgUtilPct}
        unit="%"
        color="text-blue-400"
        subtext={`Max: ${maxUtilPct}%`}
      />
      <MetricCard
        icon={TrendingUp}
        label="Throughput"
        value={summary.total_throughput_mbps.toFixed(1)}
        unit="Mbps"
        color="text-emerald-400"
        subtext={`Avg: ${summary.avg_throughput_mbps.toFixed(1)} Mbps`}
      />
      <MetricCard
        icon={Clock}
        label="Avg Latency"
        value={summary.avg_latency_ms.toFixed(1)}
        unit="ms"
        color="text-amber-400"
        subtext="End-to-end delay"
      />
      <MetricCard
        icon={Zap}
        label="Packet Loss"
        value={(summary.avg_packet_loss * 100).toFixed(3)}
        unit="%"
        color="text-red-400"
        subtext="Average across links"
      />
      <MetricCard
        icon={AlertTriangle}
        label="Congested Links"
        value={congestionRatio}
        color={summary.congested_links > 0 ? 'text-orange-400' : 'text-green-400'}
        subtext="Links > 80% util."
      />
    </div>
  );
}
