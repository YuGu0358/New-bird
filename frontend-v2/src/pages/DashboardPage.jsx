import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ArrowUpRight, ArrowDownRight, Sparkles, FlaskConical, ShieldAlert, Target } from 'lucide-react';
import {
  getAccount,
  getStrategyHealth,
  getMonitoring,
  listRiskEvents,
  getOrders,
} from '../lib/api.js';
import {
  KpiCard,
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
  StatusBadge,
  SignalDot,
} from '../components/primitives.jsx';
import {
  fmtUsd,
  fmtSignedUsd,
  fmtPct,
  fmtRelativeTime,
  classNames,
} from '../lib/format.js';

export default function DashboardPage() {
  const { t } = useTranslation();
  const accountQ = useQuery({ queryKey: ['account'], queryFn: getAccount, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['strategy-health'], queryFn: getStrategyHealth, refetchInterval: 30_000 });
  const monitoringQ = useQuery({ queryKey: ['monitoring'], queryFn: getMonitoring, refetchInterval: 30_000 });
  const ordersQ = useQuery({ queryKey: ['orders', 'all'], queryFn: () => getOrders('all'), refetchInterval: 15_000 });
  const riskEventsQ = useQuery({ queryKey: ['risk-events'], queryFn: listRiskEvents, refetchInterval: 60_000 });

  const equity = accountQ.data?.equity;
  const lastEquity = accountQ.data?.last_equity;
  const equityDelta = equity != null && lastEquity != null && lastEquity !== 0
    ? ((equity - lastEquity) / lastEquity) * 100
    : null;

  const realizedToday = healthQ.data?.realized_pnl_today ?? 0;
  const tradesToday = healthQ.data?.trades_today ?? 0;
  const openCount = healthQ.data?.open_position_count ?? 0;
  const streakKind = healthQ.data?.streak_kind ?? 'none';
  const streakLength = healthQ.data?.streak_length ?? 0;

  const recentOrders = (ordersQ.data || []).slice(0, 5);
  const recentRisk = (riskEventsQ.data?.items || []).slice(0, 5);
  const candidates = (monitoringQ.data?.candidates || []).slice(0, 5);
  const trackedTop = (monitoringQ.data?.tracked || monitoringQ.data?.items || []).slice(0, 5);

  // Synthesize a 30-day equity sparkline from last_equity → equity (placeholder).
  const equityCurve = synthesizeCurve(lastEquity, equity);

  const positionsCount = healthQ.data?.open_position_count ?? 0;

  return (
    <div className="space-y-12">
      <PageHeader
        moduleId={1}
        title={t('dashboard.title')}
        segments={[
          { label: t('dashboard.subtitle') },
          { label: `${positionsCount} POSITIONS`, accent: true },
          { label: 'UPDATED T-0.3S' },
        ]}
      />

      {/* KPI row — Tokyo mockup style: 1px gap shared border */}
      <div className="kpi-row">
        <KpiCard
          label={t('dashboard.kpi.equity')}
          value={fmtUsd(equity)}
          delta={equityDelta}
          deltaLabel={t('topbar.vsPrevClose')}
          loading={accountQ.isLoading}
          tag={equityDelta != null ? (equityDelta >= 0 ? '+' : '−') : 'L0'}
          tagTone={equityDelta != null ? (equityDelta >= 0 ? 'pos' : 'neg') : 'cyan'}
        />
        <KpiCard
          label={t('dashboard.kpi.todayPnl')}
          value={fmtSignedUsd(realizedToday)}
          delta={null}
          loading={healthQ.isLoading}
          tag={realizedToday >= 0 ? '+' : '−'}
          tagTone={realizedToday >= 0 ? 'pos' : 'neg'}
        />
        <KpiCard
          label={t('dashboard.kpi.openPositions')}
          value={String(positionsCount)}
          delta={null}
          loading={healthQ.isLoading}
          tag="L0"
          tagTone="cyan"
        />
        <KpiCard
          label={t('dashboard.kpi.streak')}
          value={
            streakLength === 0
              ? '—'
              : streakKind === 'win'
                ? t('dashboard.kpi.winStreak', { n: streakLength })
                : streakKind === 'loss'
                  ? t('dashboard.kpi.lossStreak', { n: streakLength })
                  : String(streakLength)
          }
          delta={null}
          loading={healthQ.isLoading}
          tag={streakKind === 'win' ? 'WIN' : streakKind === 'loss' ? 'LOSS' : 'NONE'}
          tagTone={streakKind === 'win' ? 'pos' : streakKind === 'loss' ? 'neg' : 'neutral'}
        />
      </div>

      {/* Equity chart */}
      <div className="card">
        <SectionHeader
          title={t('dashboard.equityCurve')}
          subtitle={
            accountQ.isLoading
              ? t('common.loading')
              : equity != null && lastEquity != null
                ? t('dashboard.lastClose', { prev: fmtUsd(lastEquity), curr: fmtUsd(equity) })
                : t('dashboard.equityCurveHint')
          }
        />
        {accountQ.isError ? (
          <ErrorState error={accountQ.error} onRetry={accountQ.refetch} />
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityCurve}>
                <defs>
                  <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#5BA3C6" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#5BA3C6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
                <XAxis dataKey="t" stroke="#7C8A9A" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#7C8A9A" fontSize={11} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{
                    background: '#0F1923',
                    border: '1px solid #3D7FA5',
                    borderRadius: 6,
                    color: '#E8ECF1',
                    fontSize: 12,
                  }}
                  formatter={(v) => fmtUsd(v)}
                  labelFormatter={(l) => l}
                />
                <Area type="monotone" dataKey="v" stroke="#5BA3C6" strokeWidth={2} fill="url(#equityFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Two-column body */}
      <div className="grid grid-cols-12 gap-6">
        {/* Holdings preview */}
        <div className="col-span-7 card">
          <SectionHeader title={t('dashboard.holdings')} subtitle={t('dashboard.holdingsSubtitle')} />
          <HoldingsPreview t={t} data={trackedTop} loading={monitoringQ.isLoading} error={monitoringQ.error} retry={monitoringQ.refetch} />
        </div>
        {/* Strategy health */}
        <div className="col-span-5 card">
          <SectionHeader title={t('dashboard.strategyHealth')} />
          <StrategyHealthSummary
            t={t}
            loading={healthQ.isLoading}
            error={healthQ.error}
            retry={healthQ.refetch}
            data={healthQ.data}
            tradesToday={tradesToday}
          />
        </div>

        {/* Candidate pool */}
        <div className="col-span-7 card">
          <SectionHeader title={t('dashboard.candidatePool')} subtitle={t('dashboard.candidatePoolSubtitle')} />
          <CandidatePoolPreview t={t} data={candidates} loading={monitoringQ.isLoading} />
        </div>
        {/* Recent orders */}
        <div className="col-span-5 card">
          <SectionHeader title={t('dashboard.recentOrders')} />
          <OrderList t={t} orders={recentOrders} loading={ordersQ.isLoading} error={ordersQ.error} retry={ordersQ.refetch} />
        </div>

        {/* Risk events */}
        <div className="col-span-12 card">
          <SectionHeader
            title={t('dashboard.riskFeed')}
            subtitle={t('dashboard.riskFeedSubtitle')}
          />
          <RiskFeed t={t} events={recentRisk} loading={riskEventsQ.isLoading} error={riskEventsQ.error} retry={riskEventsQ.refetch} />
        </div>
      </div>
    </div>
  );
}

function HoldingsPreview({ t, data, loading, error, retry }) {
  if (loading) return <LoadingState rows={4} />;
  if (error) return <ErrorState error={error} onRetry={retry} />;
  if (!data || data.length === 0)
    return <EmptyState icon={Target} title={t('dashboard.noPositions')} hint={t('dashboard.noPositionsHint')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th style={{ width: 32 }}></th>
          <th>Ticker</th>
          <th className="tbl-num">Qty</th>
          <th className="tbl-num">Entry</th>
          <th className="tbl-num">Last</th>
          <th className="tbl-num">PnL %</th>
          <th className="tbl-num">PnL $</th>
          <th>Trend (D / W / M)</th>
          <th>Signal</th>
        </tr>
      </thead>
      <tbody>
        {data.map((row, i) => {
          const symbol = row.symbol ?? row.ticker ?? '?';
          const qty = parseFloat(row.qty ?? row.quantity ?? 0) || 0;
          const entry = parseFloat(row.avg_entry_price ?? row.entry_price ?? row.average_entry_price ?? 0) || 0;
          const current = parseFloat(row.current_price ?? row.price ?? entry) || entry;
          const unreal = parseFloat(row.unrealized_pl ?? row.unrealized_profit ?? (current - entry) * qty) || 0;
          const unrealPct = entry > 0 ? ((current - entry) / entry) * 100 : 0;
          const dPct = parseFloat(row.day_change_percent ?? 0);
          const wPct = parseFloat(row.week_change_percent ?? 0);
          const mPct = parseFloat(row.month_change_percent ?? 0);

          // Map P&L magnitude to signal tone
          const tone = unrealPct > 0 ? 'ok' : unrealPct < -5 ? 'danger' : unrealPct < 0 ? 'warn' : 'neutral';
          const signalLabel = tone === 'ok' ? 'NORMAL' : tone === 'warn' ? 'DRAWDOWN' : tone === 'danger' ? 'NEAR LIMIT' : 'IDLE';
          const signalCls = `signal-label ${tone}`;

          return (
            <tr key={`${symbol}-${i}`}>
              <td style={{ paddingLeft: 16 }}><SignalDot tone={tone} /></td>
              <td className="ticker">{symbol}</td>
              <td className="tbl-num">{qty.toFixed(4)}</td>
              <td className="tbl-num">{fmtUsd(entry)}</td>
              <td className="tbl-num">{fmtUsd(current)}</td>
              <td className={classNames('tbl-num', unrealPct > 0 ? 'pos' : unrealPct < 0 ? 'neg' : '')}>
                {fmtPct(unrealPct)}
              </td>
              <td className={classNames('tbl-num', unreal > 0 ? 'pos' : unreal < 0 ? 'neg' : '')}>
                {fmtSignedUsd(unreal)}
              </td>
              <td>
                <div className="flex items-center gap-3 font-mono text-[10px]">
                  <Trend pct={dPct} label="D" />
                  <Trend pct={wPct} label="W" />
                  <Trend pct={mPct} label="M" />
                </div>
              </td>
              <td><span className={signalCls}>● {signalLabel}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Trend({ pct, label }) {
  const v = Number.isFinite(pct) ? pct : 0;
  return (
    <span className={classNames('inline-flex items-center gap-1', v > 0 ? 'pos' : v < 0 ? 'neg' : 'text-text-muted')}>
      <span className="text-text-muted">{label}</span>
      <span>{Number.isFinite(pct) ? fmtPct(pct) : '—'}</span>
    </span>
  );
}

function CandidatePoolPreview({ t, data, loading }) {
  if (loading) return <LoadingState rows={4} />;
  if (!data || data.length === 0) return <EmptyState icon={Sparkles} title={t('dashboard.candidatesEmpty')} hint={t('dashboard.candidatesEmptyHint')} />;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Category</th>
          <th className="tbl-num">Score</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {data.map((row, i) => (
          <tr key={`${row.symbol}-${i}`}>
            <td className="font-medium text-steel-50">{row.symbol}</td>
            <td><span className="pill-default">{row.category || 'tech'}</span></td>
            <td className="tbl-num text-steel-50">{Number(row.score ?? 0).toFixed(2)}</td>
            <td className="text-steel-200 max-w-md truncate">{row.reason || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OrderList({ t, orders, loading, error, retry }) {
  if (loading) return <LoadingState rows={3} />;
  if (error) return <ErrorState error={error} onRetry={retry} />;
  if (!orders || orders.length === 0) return <EmptyState icon={FlaskConical} title={t('dashboard.noOrdersToday')} />;
  return (
    <ul className="divide-y divide-steel-400">
      {orders.map((o, i) => (
        <li key={o.order_id || i} className="py-3 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-body font-medium text-steel-50 truncate">
              <span className={classNames(o.side === 'buy' ? 'text-bull' : 'text-bear', 'mr-2 uppercase font-semibold')}>
                {o.side}
              </span>
              {o.symbol}
            </div>
            <div className="text-caption text-steel-200 mt-0.5">
              {o.qty ? `${o.qty} sh` : ''} {o.notional ? fmtUsd(o.notional) : ''} · {fmtRelativeTime(o.submitted_at || o.created_at)}
            </div>
          </div>
          <StatusBadge status={o.status} />
        </li>
      ))}
    </ul>
  );
}

function RiskFeed({ t, events, loading, error, retry }) {
  if (loading) return <LoadingState rows={3} />;
  if (error) return <ErrorState error={error} onRetry={retry} />;
  if (!events || events.length === 0) return <EmptyState icon={ShieldAlert} title={t('dashboard.noRiskEvents')} hint={t('dashboard.noRiskEventsHint')} />;
  return (
    <ul className="divide-y divide-steel-400">
      {events.map((e) => (
        <li key={e.id} className="py-3 grid grid-cols-12 items-center gap-4">
          <div className="col-span-2"><span className="pill-warn">{e.policy_name}</span></div>
          <div className="col-span-2">
            <span className={classNames(e.side === 'buy' ? 'text-bull' : 'text-bear', 'uppercase font-semibold')}>
              {e.side}
            </span>{' '}
            <span className="font-medium text-steel-50">{e.symbol}</span>
          </div>
          <div className="col-span-2 tabular text-steel-100">
            {e.notional ? fmtUsd(e.notional) : e.qty ? `${e.qty} sh` : '—'}
          </div>
          <div className="col-span-4 text-steel-200 text-body-sm truncate">{e.reason}</div>
          <div className="col-span-2 text-caption text-steel-200 text-right">{fmtRelativeTime(e.occurred_at)}</div>
        </li>
      ))}
    </ul>
  );
}

function StrategyHealthSummary({ t, data, tradesToday, loading, error, retry }) {
  if (loading) return <LoadingState rows={3} />;
  if (error) return <ErrorState error={error} onRetry={retry} />;
  if (!data) return <EmptyState title={t('common.noData')} />;
  return (
    <div className="space-y-4">
      <Row label={t('dashboard.activeStrategy')} value={data.active_strategy_name || '—'} />
      <Row label={t('dashboard.tradesToday')} value={String(tradesToday)} />
      <Row label={t('dashboard.winsLosses')} value={`${data.wins_today || 0} / ${data.losses_today || 0}`} />
      <Row
        label={t('dashboard.winLossStreak')}
        value={
          data.streak_length === 0
            ? '—'
            : data.streak_kind === 'win'
              ? t('dashboard.kpi.winStreak', { n: data.streak_length })
              : data.streak_kind === 'loss'
                ? t('dashboard.kpi.lossStreak', { n: data.streak_length })
                : String(data.streak_length)
        }
        valueClass={
          data.streak_kind === 'win' ? 'text-bull' : data.streak_kind === 'loss' ? 'text-bear' : 'text-steel-50'
        }
      />
      <Row
        label={t('dashboard.lastTrade')}
        value={data.last_trade_at ? fmtRelativeTime(data.last_trade_at) : '—'}
      />
    </div>
  );
}

function Row({ label, value, valueClass }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-body-sm text-steel-200">{label}</span>
      <span className={classNames('text-body font-medium tabular', valueClass || 'text-steel-50')}>{value}</span>
    </div>
  );
}

function synthesizeCurve(prev, curr) {
  // Simple 30-point linear interp for visual continuity until we have real history.
  const start = Number.isFinite(prev) && prev > 0 ? prev : 100_000;
  const end = Number.isFinite(curr) && curr > 0 ? curr : start;
  const points = [];
  for (let i = 0; i < 30; i++) {
    const ratio = i / 29;
    const v = start + (end - start) * ratio + (Math.sin(i * 0.4) * (end - start) * 0.04);
    points.push({ t: `D-${29 - i}`, v: Math.round(v * 100) / 100 });
  }
  return points;
}
