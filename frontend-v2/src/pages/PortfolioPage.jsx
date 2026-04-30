import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { XCircle, Square, ChevronRight } from 'lucide-react';
import {
  getPositions,
  getOrders,
  getTrades,
  cancelOrders,
  closePositions,
  getStrategyHealth,
  listBrokerAccounts,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
  StatusBadge,
} from '../components/primitives.jsx';
import { fmtUsd, fmtSignedUsd, fmtPct, fmtRelativeTime, fmtAbsTime, classNames } from '../lib/format.js';

const TABS = [
  { id: 'positions', label: 'Positions' },
  { id: 'orders', label: 'Orders' },
  { id: 'trades', label: 'Closed trades' },
];

export default function PortfolioPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState('positions');
  const [orderStatus, setOrderStatus] = useState('all');

  const positionsQ = useQuery({ queryKey: ['positions'], queryFn: getPositions, refetchInterval: 15_000 });
  const ordersQ = useQuery({ queryKey: ['orders', orderStatus], queryFn: () => getOrders(orderStatus), refetchInterval: 15_000 });
  const tradesQ = useQuery({ queryKey: ['trades'], queryFn: getTrades, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['strategy-health'], queryFn: getStrategyHealth, refetchInterval: 30_000 });

  const cancelMut = useMutation({
    mutationFn: cancelOrders,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['orders'] }),
  });
  const closeMut = useMutation({
    mutationFn: closePositions,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['positions'] }),
  });

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={3}
        title={t('portfolio.title')}
        segments={[{ label: t('portfolio.subtitle') }]}
      />

      <AccountsSection />

      {/* Sidebar stats */}
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-9">
          <div className="card">
            {/* Tab switcher */}
            <div className="flex items-center gap-6 border-b border-steel-400 -mx-5 px-5 mb-4">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  className={classNames(
                    'h-10 -mb-px border-b-2 text-body-sm font-medium transition duration-150',
                    tab === t.id
                      ? 'border-steel-500 text-steel-50'
                      : 'border-transparent text-steel-200 hover:text-steel-50'
                  )}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
              <div className="ml-auto flex items-center gap-2">
                {tab === 'positions' && (
                  <button
                    className="btn-destructive btn-sm"
                    onClick={() => closeMut.mutate()}
                    disabled={closeMut.isPending}
                  >
                    <Square size={12} /> {t('portfolio.closeAll')}
                  </button>
                )}
                {tab === 'orders' && (
                  <>
                    <select
                      className="select btn-sm h-7"
                      value={orderStatus}
                      onChange={(e) => setOrderStatus(e.target.value)}
                    >
                      <option value="all">All</option>
                      <option value="open">Open</option>
                      <option value="closed">Closed</option>
                    </select>
                    <button
                      className="btn-destructive btn-sm"
                      onClick={() => cancelMut.mutate()}
                      disabled={cancelMut.isPending}
                    >
                      <XCircle size={12} /> {t('portfolio.cancelAll')}
                    </button>
                  </>
                )}
              </div>
            </div>

            {tab === 'positions' && <PositionsTable q={positionsQ} />}
            {tab === 'orders' && <OrdersTable q={ordersQ} />}
            {tab === 'trades' && <TradesTable q={tradesQ} />}
          </div>
        </div>

        <aside className="col-span-3 space-y-4">
          <SidebarStat
            label={t('portfolio.todayRealizedPnl')}
            value={fmtSignedUsd(healthQ.data?.realized_pnl_today ?? 0)}
            valueClass={
              healthQ.data?.realized_pnl_today > 0
                ? 'text-bull'
                : healthQ.data?.realized_pnl_today < 0
                  ? 'text-bear'
                  : 'text-steel-50'
            }
          />
          <SidebarStat label={t('portfolio.todayTrades')} value={String(healthQ.data?.trades_today ?? 0)} />
          <SidebarStat
            label={t('portfolio.todayWinsLosses')}
            value={`${healthQ.data?.wins_today ?? 0} / ${healthQ.data?.losses_today ?? 0}`}
          />
          <SidebarStat
            label={t('portfolio.winLossStreak')}
            value={
              !healthQ.data?.streak_length
                ? '—'
                : healthQ.data.streak_kind === 'win'
                  ? t('dashboard.kpi.winStreak', { n: healthQ.data.streak_length })
                  : t('dashboard.kpi.lossStreak', { n: healthQ.data.streak_length })
            }
            valueClass={
              healthQ.data?.streak_kind === 'win'
                ? 'text-profit'
                : healthQ.data?.streak_kind === 'loss'
                  ? 'text-loss'
                  : 'text-text-primary'
            }
          />
          <SidebarStat
            label={t('portfolio.lastTrade')}
            value={healthQ.data?.last_trade_at ? fmtRelativeTime(healthQ.data.last_trade_at) : '—'}
          />
          <SidebarStat
            label={t('portfolio.activeStrategy')}
            value={healthQ.data?.active_strategy_name || '—'}
            small
          />
        </aside>
      </div>
    </div>
  );
}

function SidebarStat({ label, value, valueClass = 'text-steel-50', small = false }) {
  return (
    <div className="card-dense">
      <div className="metric-caption">{label}</div>
      <div className={classNames(small ? 'text-body font-medium' : 'metric-value', valueClass, 'mt-1 break-all')}>
        {value}
      </div>
    </div>
  );
}

function AccountsSection() {
  const accountsQ = useQuery({ queryKey: ['broker-accounts'], queryFn: () => listBrokerAccounts() });
  const items = accountsQ.data?.items ?? [];
  if (accountsQ.isLoading) return null;
  // Surface errors so a failed account fetch isn't invisible. Empty list still
  // hides the section to keep the page calm for users with no broker yet.
  if (accountsQ.isError) {
    return (
      <div className="card">
        <ErrorState error={accountsQ.error} onRetry={accountsQ.refetch} />
      </div>
    );
  }
  if (items.length === 0) return null;
  return (
    <div className="card">
      <div className="font-mono text-[11px] text-text-muted tracking-[0.15em] uppercase mb-3">Accounts</div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((a) => (
          <Link
            key={a.id}
            to={`/portfolio/account/${a.id}`}
            className="flex items-center justify-between border border-border-subtle bg-surface px-4 py-3 hover:border-cyan transition"
          >
            <div className="min-w-0">
              <div className="font-medium text-steel-50 truncate">{a.alias || a.account_id}</div>
              <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mt-0.5">
                {a.broker} · {a.tier} · {a.is_active ? 'ACTIVE' : 'INACTIVE'}
              </div>
            </div>
            <ChevronRight size={14} className="text-text-muted shrink-0" />
          </Link>
        ))}
      </div>
    </div>
  );
}

function PositionsTable({ q }) {
  const { t } = useTranslation();
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data || q.data.length === 0) return <EmptyState title={t('portfolio.noPositions')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{t('common.symbol')}</th>
          <th className="tbl-num">{t('common.qty')}</th>
          <th className="tbl-num">{t('portfolio.columns.avgEntry')}</th>
          <th className="tbl-num">{t('portfolio.columns.current')}</th>
          <th className="tbl-num">{t('markets.columns.marketValue')}</th>
          <th className="tbl-num">{t('markets.columns.unrealizedPnl')}</th>
          <th className="tbl-num">{t('portfolio.columns.unrealPct')}</th>
        </tr>
      </thead>
      <tbody>
        {q.data.map((p) => {
          const qty = parseFloat(p.qty || 0);
          const entry = parseFloat(p.avg_entry_price || p.entry_price || 0);
          const current = parseFloat(p.current_price || entry);
          const mv = parseFloat(p.market_value || qty * current);
          const upl = parseFloat(p.unrealized_pl || (current - entry) * qty);
          const uplPct = entry > 0 ? ((current - entry) / entry) * 100 : 0;
          return (
            <tr key={p.symbol}>
              <td className="font-medium text-steel-50">
                <Link to={`/research/${encodeURIComponent(p.symbol)}`} className="hover:text-cyan transition-colors">
                  {p.symbol}
                </Link>
              </td>
              <td className="tbl-num">{qty.toFixed(4)}</td>
              <td className="tbl-num">{fmtUsd(entry)}</td>
              <td className="tbl-num">{fmtUsd(current)}</td>
              <td className="tbl-num">{fmtUsd(mv)}</td>
              <td className={classNames('tbl-num font-medium', upl > 0 ? 'text-bull' : upl < 0 ? 'text-bear' : '')}>
                {fmtSignedUsd(upl)}
              </td>
              <td className={classNames('tbl-num font-medium', uplPct > 0 ? 'text-bull' : uplPct < 0 ? 'text-bear' : '')}>
                {fmtPct(uplPct)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function OrdersTable({ q }) {
  const { t } = useTranslation();
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data || q.data.length === 0) return <EmptyState title={t('portfolio.noOrders')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{t('common.time')}</th>
          <th>{t('common.symbol')}</th>
          <th>{t('common.side')}</th>
          <th>{t('common.type')}</th>
          <th className="tbl-num">{t('common.qty')}</th>
          <th className="tbl-num">{t('quantlab.fields.notional')}</th>
          <th className="tbl-num">{t('portfolio.columns.filledPx')}</th>
          <th>{t('common.status')}</th>
        </tr>
      </thead>
      <tbody>
        {q.data.map((o, i) => (
          <tr key={o.order_id || o.id || i}>
            <td className="text-steel-200">{fmtRelativeTime(o.submitted_at || o.created_at)}</td>
            <td className="font-medium text-steel-50">{o.symbol}</td>
            <td>
              <span className={classNames('font-semibold uppercase', o.side === 'buy' ? 'text-bull' : 'text-bear')}>
                {o.side}
              </span>
            </td>
            <td className="text-steel-200">{o.order_type || o.type || 'market'}</td>
            <td className="tbl-num">{o.qty ? parseFloat(o.qty).toFixed(4) : '—'}</td>
            <td className="tbl-num">{o.notional ? fmtUsd(parseFloat(o.notional)) : '—'}</td>
            <td className="tbl-num">{o.filled_avg_price ? fmtUsd(parseFloat(o.filled_avg_price)) : '—'}</td>
            <td><StatusBadge status={o.status} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TradesTable({ q }) {
  const { t } = useTranslation();
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data || q.data.length === 0) return <EmptyState title={t('portfolio.noTrades')} hint={t('portfolio.noTradesHint')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{t('portfolio.columns.exitTime')}</th>
          <th>{t('common.symbol')}</th>
          <th className="tbl-num">{t('common.qty')}</th>
          <th className="tbl-num">{t('portfolio.columns.entry')}</th>
          <th className="tbl-num">{t('portfolio.columns.exit')}</th>
          <th className="tbl-num">{t('portfolio.columns.netPnl')}</th>
          <th>{t('portfolio.columns.reason')}</th>
        </tr>
      </thead>
      <tbody>
        {q.data.map((t, i) => {
          const pnl = parseFloat(t.net_profit ?? 0);
          return (
            <tr key={i}>
              <td className="text-steel-200">{fmtAbsTime(t.exit_date)}</td>
              <td className="font-medium text-steel-50">{t.symbol}</td>
              <td className="tbl-num">{parseFloat(t.qty || 0).toFixed(4)}</td>
              <td className="tbl-num">{fmtUsd(parseFloat(t.entry_price || 0))}</td>
              <td className="tbl-num">{fmtUsd(parseFloat(t.exit_price || 0))}</td>
              <td className={classNames('tbl-num font-medium', pnl > 0 ? 'text-bull' : pnl < 0 ? 'text-bear' : '')}>
                {fmtSignedUsd(pnl)}
              </td>
              <td><span className="pill-default">{t.exit_reason || '—'}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
