// Command Palette registry — pages and actions surfaced via Cmd+K.
//
// Page entries mirror Sidebar.jsx slugs so labels reuse the existing
// `nav.<slug>` translations. Actions resolve their own dedicated keys under
// `cmdk.actions.<id>`.
import {
  LayoutDashboard,
  TrendingUp,
  Briefcase,
  BookOpen,
  Activity,
  Newspaper,
  Calculator,
  Crosshair,
  Brain,
  FlaskConical,
  Workflow,
  Atom,
  Shield,
  MessageCircle,
  Code as CodeIcon,
  Settings as SettingsIcon,
  Globe,
  Languages,
  RefreshCw,
} from 'lucide-react';

export const PAGES = [
  { id: 'dashboard',    to: '/',             icon: LayoutDashboard, navKey: 'nav.dashboard' },
  { id: 'markets',      to: '/markets',      icon: TrendingUp,      navKey: 'nav.markets' },
  { id: 'portfolio',    to: '/portfolio',    icon: Briefcase,       navKey: 'nav.portfolio' },
  { id: 'journal',      to: '/journal',      icon: BookOpen,        navKey: 'nav.journal' },
  { id: 'macro',        to: '/macro',        icon: Activity,        navKey: 'nav.macro' },
  { id: 'news',         to: '/news',         icon: Newspaper,       navKey: 'nav.news' },
  { id: 'valuation',    to: '/valuation',    icon: Calculator,      navKey: 'nav.valuation' },
  { id: 'options',      to: '/options',      icon: Crosshair,       navKey: 'nav.options' },
  { id: 'intelligence', to: '/intelligence', icon: Brain,           navKey: 'nav.intelligence' },
  { id: 'backtest',     to: '/backtest',     icon: FlaskConical,    navKey: 'nav.backtest' },
  { id: 'algorithms',   to: '/algo',         icon: Workflow,        navKey: 'nav.algorithms' },
  { id: 'quantlab',     to: '/quantlib',     icon: Atom,            navKey: 'nav.quantlab' },
  { id: 'risk',         to: '/risk',         icon: Shield,          navKey: 'nav.risk' },
  { id: 'social',       to: '/social',       icon: MessageCircle,   navKey: 'nav.social' },
  { id: 'code',         to: '/code',         icon: CodeIcon,        navKey: 'nav.code' },
  { id: 'settings',     to: '/settings',     icon: SettingsIcon,    navKey: 'nav.settings' },
];

// Actions take a `ctx` argument: { i18n, queryClient, navigate }.
export const ACTIONS = [
  {
    id: 'switchLanguageEn',
    icon: Globe,
    run: (ctx) => ctx.i18n.changeLanguage('en'),
  },
  {
    id: 'switchLanguageZh',
    icon: Languages,
    run: (ctx) => ctx.i18n.changeLanguage('zh'),
  },
  {
    id: 'switchLanguageDe',
    icon: Languages,
    run: (ctx) => ctx.i18n.changeLanguage('de'),
  },
  {
    id: 'switchLanguageFr',
    icon: Languages,
    run: (ctx) => ctx.i18n.changeLanguage('fr'),
  },
  {
    id: 'refreshAll',
    icon: RefreshCw,
    run: (ctx) => ctx.queryClient.invalidateQueries(),
  },
  {
    id: 'openSettings',
    icon: SettingsIcon,
    run: (ctx) => ctx.navigate('/settings'),
  },
];

// localStorage key for recent items (page id or `action:<id>`).
export const RECENT_KEY = 'nb:cmdk:recent';
export const RECENT_LIMIT = 5;

export function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

export function pushRecent(itemKey) {
  const current = loadRecent().filter((k) => k !== itemKey);
  current.unshift(itemKey);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(current.slice(0, RECENT_LIMIT)));
  } catch {
    // localStorage may be unavailable (private mode etc.) — ignore.
  }
}
