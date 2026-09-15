import { NavLink } from 'react-router-dom';
import {
  Network,
  BarChart2,
  GitBranch,
  Bot,
  TrendingUp,
  FileText,
  MessageSquare,
  Cpu,
} from 'lucide-react';

const navItems = [
  { to: '/', icon: Network, label: 'Topology' },
  { to: '/metrics', icon: BarChart2, label: 'Live Metrics' },
  { to: '/flows', icon: GitBranch, label: 'Active Flows' },
  { to: '/training', icon: Cpu, label: 'RL Training' },
  { to: '/progress', icon: TrendingUp, label: 'Train Progress' },
  { to: '/evaluation', icon: Bot, label: 'Evaluation' },
  { to: '/reports', icon: FileText, label: 'Reports' },
  { to: '/copilot', icon: MessageSquare, label: 'AI Copilot' },
];

export function Sidebar() {
  return (
    <aside className="w-56 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
      {/* Brand */}
      <div className="px-4 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
            <Network size={15} className="text-white" />
          </div>
          <div>
            <p className="text-sm font-bold text-white leading-none">RL-SDN</p>
            <p className="text-[10px] text-slate-400 mt-0.5">Traffic Engineering</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white font-medium'
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
              }`
            }
          >
            <Icon size={15} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-slate-800">
        <p className="text-[10px] text-slate-500">
          Powered by PyTorch & Ryu
        </p>
      </div>
    </aside>
  );
}
