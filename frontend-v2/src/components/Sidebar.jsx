import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
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

const NAV_ITEMS = [
  { to: '/',             key: 'dashboard',    icon: GaugeCircle,    end: true },
  { to: '/markets',      key: 'markets',      icon: LineChart },
  { to: '/portfolio',    key: 'portfolio',    icon: Wallet },
  { to: '/news',         key: 'news',         icon: Newspaper },
  { to: '/intelligence', key: 'intelligence', icon: MessagesSquare },
  { to: '/backtest',     key: 'backtest',     icon: FlaskConical },
  { to: '/algo',         key: 'algorithms',   icon: GitBranch },
  { to: '/quantlib',     key: 'quantlab',     icon: Calculator },
  { to: '/risk',         key: 'risk',         icon: ShieldAlert },
  { to: '/social',       key: 'social',       icon: Radar },
  { to: '/code',         key: 'code',         icon: Code2 },
  { to: '/settings',     key: 'settings',     icon: Settings2 },
];

export default function Sidebar() {
  const { t } = useTranslation();
  return (
    <aside className="w-60 shrink-0 border-r border-steel-400 bg-ink-900 flex flex-col">
      <div className="h-14 px-5 flex items-center gap-2.5 border-b border-steel-400">
        <RavenMark />
        <div className="leading-tight">
          <div className="text-[15px] font-semibold text-steel-50 tracking-wide">{t('nav.brand')}</div>
          <div className="text-caption text-steel-200">{t('nav.tagline')}</div>
        </div>
      </div>
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map(({ to, key, icon: Icon, end }) => (
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
            <span className="text-body-sm font-medium flex-1">{t(`nav.${key}`)}</span>
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-steel-400 text-caption text-steel-300 flex items-center gap-1.5">
        <Activity size={12} className="text-bull" /> v0.1.0 · {t('nav.phaseStatus')}
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
