import { NavLink } from 'react-router-dom';
import {
  GaugeCircle,
  LineChart,
  Wallet,
  Newspaper,
  MessagesSquare,
  FlaskConical,
  GitBranch,
  Calculator,
  ShieldAlert,
  Radar,
  Code2,
  Settings2,
  Activity,
} from 'lucide-react';
import { classNames } from '../lib/format.js';

const navItems = [
  { to: '/', label: 'Dashboard', icon: GaugeCircle, end: true },
  { to: '/markets', label: 'Markets', icon: LineChart },
  { to: '/portfolio', label: 'Portfolio', icon: Wallet },
  { to: '/news', label: 'News', icon: Newspaper },
  { to: '/intelligence', label: 'AI Council', icon: MessagesSquare },
  { to: '/backtest', label: 'Backtest', icon: FlaskConical },
  { to: '/algo', label: 'Algorithms', icon: GitBranch },
  { to: '/quantlib', label: 'Quant Lab', icon: Calculator, badge: 'P8' },
  { to: '/risk', label: 'Risk', icon: ShieldAlert },
  { to: '/social', label: 'Social', icon: Radar },
  { to: '/code', label: 'Code', icon: Code2, badge: 'P9' },
  { to: '/settings', label: 'Settings', icon: Settings2 },
];

export default function Sidebar() {
  return (
    <aside className="w-60 shrink-0 border-r border-steel-400 bg-ink-900 flex flex-col">
      <div className="h-14 px-5 flex items-center gap-2.5 border-b border-steel-400">
        <RavenMark />
        <div className="leading-tight">
          <div className="text-[15px] font-semibold text-steel-50 tracking-wide">Trading Raven</div>
          <div className="text-caption text-steel-200">Quant Console</div>
        </div>
      </div>
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              classNames(
                'group flex items-center gap-3 h-9 px-3 rounded transition duration-150',
                isActive
                  ? 'bg-ink-700 text-steel-50 border-l-2 border-steel-500 pl-[10px]'
                  : 'text-steel-200 hover:bg-ink-800 hover:text-steel-50'
              )
            }
          >
            <Icon size={16} strokeWidth={1.75} />
            <span className="text-body-sm font-medium flex-1">{label}</span>
            {badge && (
              <span className="text-[9px] uppercase tracking-wider text-steel-300 font-semibold border border-steel-400 rounded-sm px-1 py-px">
                {badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-steel-400 text-caption text-steel-300 flex items-center gap-1.5">
        <Activity size={12} className="text-bull" /> v0.1.0 · backend P0–P5
      </div>
    </aside>
  );
}

function RavenMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" className="text-steel-500">
      <path
        fill="currentColor"
        d="M3 14c0-2 1-4 3-5 1-.5 2-1 3-1l3-3c1 1 2 1 3 1l4 1c1 0 2 1 3 2 2 2 3 5 1 7-1 1-2 1-2 2v3c-1 1-2 1-3 1h-2v2h-2v-2H8c-1 0-2 0-3-1l1-3c-1-1-2-2-2-3z"
      />
      <circle cx="9" cy="11" r="1" className="fill-ink-950" />
    </svg>
  );
}
