import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { classNames } from '../lib/format.js';

// `key` is reserved by React (used for list reconciliation and never
// passed through as a prop), so we use `slug` instead for the i18n
// translation key. This was the root cause of the "nav.undefined" bug.
const NAV_ITEMS = [
  { to: '/',             slug: 'dashboard',    end: true },
  { to: '/markets',      slug: 'markets' },
  { to: '/portfolio',    slug: 'portfolio' },
  { to: '/journal',      slug: 'journal' },
  { to: '/macro',        slug: 'macro' },
  { to: '/news',         slug: 'news' },
  { to: '/valuation',    slug: 'valuation' },
  { to: '/options',      slug: 'options' },
  { to: '/intelligence', slug: 'intelligence' },
  { to: '/backtest',     slug: 'backtest' },
  { to: '/algo',         slug: 'algorithms' },
  { to: '/quantlib',     slug: 'quantlab' },
  { to: '/risk',         slug: 'risk' },
  { to: '/social',       slug: 'social' },
  { to: '/code',         slug: 'code' },
];

const SYS_ITEMS = [
  { to: '/settings',     slug: 'settings', tag: 'SY' },
];

export default function Sidebar() {
  const { t } = useTranslation();
  return (
    <aside
      className="w-[220px] shrink-0 bg-surface border-r border-border-subtle py-7 px-4 flex flex-col gap-1"
    >
      {/* Brand */}
      <div className="px-3 pb-7 mb-6 border-b border-border-subtle flex items-center gap-2.5">
        <span className="w-2 h-2 bg-cyan shadow-glow-cyan" />
        <span
          className="text-[18px] font-display font-semibold tracking-[0.15em] text-text-primary uppercase"
        >
          {t('nav.brand')}
        </span>
      </div>

      <SectionLabel>Navigation</SectionLabel>
      {NAV_ITEMS.map((item, i) => (
        <NavItem
          key={item.to}
          to={item.to}
          slug={item.slug}
          end={item.end}
          num={String(i + 1).padStart(2, '0')}
          t={t}
        />
      ))}

      <SectionLabel className="mt-4">System</SectionLabel>
      {SYS_ITEMS.map((item) => (
        <NavItem
          key={item.to}
          to={item.to}
          slug={item.slug}
          num={item.tag}
          t={t}
        />
      ))}

      <div className="mt-auto pt-6 px-3">
        <div
          className="font-mono text-[10px] tracking-[0.15em] text-text-muted uppercase"
        >
          v0.1.0 · {t('nav.phaseStatus')}
        </div>
      </div>
    </aside>
  );
}

function SectionLabel({ children, className = '' }) {
  return (
    <div
      className={classNames(
        'font-mono text-[10px] tracking-[0.2em] text-text-muted uppercase px-3 pt-4 pb-2',
        className,
      )}
    >
      {children}
    </div>
  );
}

function NavItem({ to, slug, num, end, t }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        classNames(
          'group flex items-center gap-3 h-9 px-3 relative transition duration-150',
          'font-sans text-[13px] tracking-[0.02em]',
          isActive
            ? 'text-cyan bg-elevated'
            : 'text-text-secondary hover:text-text-primary hover:bg-elevated',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute left-0 top-0 bottom-0 w-[2px] bg-cyan shadow-glow-cyan"
            />
          )}
          <span
            className={classNames(
              'font-mono text-[10px] w-5',
              isActive ? 'text-cyan' : 'text-text-muted',
            )}
          >
            {num}
          </span>
          <span className="flex-1">{t(`nav.${slug}`)}</span>
        </>
      )}
    </NavLink>
  );
}
