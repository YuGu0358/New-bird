import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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
import { Play, FlaskConical, ArrowLeft } from 'lucide-react';
import {
  runBacktest,
  listBacktestRuns,
  getBacktestRun,
  getBacktestEquityCurve,
  listRegisteredStrategies,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
  StatusBadge,
  KpiCard,
} from '../components/primitives.jsx';
import { fmtUsd, fmtSignedUsd, fmtPct, fmtRelativeTime, classNames } from '../lib/format.js';
import { ApiErrorBanner } from '../components/TopBar.jsx';

export default function BacktestPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState(null);

  if (selectedId) {
    return (
      <BacktestDetail
        runId={selectedId}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return (
    <BacktestList
      onSelect={setSelectedId}
      queryClient={queryClient}
    />
  );
}

function BacktestList({ onSelect, queryClient }) {
  const { t } = useTranslation();
  const runsQ = useQuery({ queryKey: ['backtest-runs'], queryFn: listBacktestRuns, refetchInterval: 15_000 });
  const registeredQ = useQuery({ queryKey: ['registered-strategies'], queryFn: listRegisteredStrategies });

  const [strategyName, setStrategyName] = useState('strategy_b_v1');
  const [universe, setUniverse] = useState('AAPL,MSFT,NVDA,GOOGL,META');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-06-01');
  const [initialCash, setInitialCash] = useState(100_000);
  const [enableRisk, setEnableRisk] = useState(false);

  const runMut = useMutation({
    mutationFn: runBacktest,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backtest-runs'] }),
  });

  function submit(e) {
    e.preventDefault();
    runMut.mutate({
      strategy_name: strategyName,
      parameters: {},
      universe: universe.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
      start_date: startDate,
      end_date: endDate,
      initial_cash: parseFloat(initialCash),
      enable_risk_guard: enableRisk,
    });
  }

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={6}
        title={t('backtest.title')}
        segments={[
          { label: t('backtest.subtitle') },
          { label: 'P3 · ENGINE', accent: true },
        ]}
        live={false}
      />

      <div className="grid grid-cols-12 gap-6">
        {/* New backtest form */}
        <form onSubmit={submit} className="col-span-5 card space-y-4">
          <SectionHeader title={t('backtest.newRun')} />
          {runMut.isError && <ApiErrorBanner error={runMut.error} label={t('backtest.runFailed')} />}
          {runMut.isSuccess && (
            <div className="border border-profit/40 bg-profit-tint px-3 py-2 text-body-sm text-profit">
              ✓ {t('backtest.runSubmitted', { id: runMut.data?.id })}
            </div>
          )}

          <div>
            <label className="h-caption block mb-2">{t('backtest.strategyType')}</label>
            <select className="select" value={strategyName} onChange={(e) => setStrategyName(e.target.value)}>
              {(registeredQ.data?.items || []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} — {s.description?.slice(0, 50)}
                </option>
              ))}
              {(!registeredQ.data || registeredQ.data.items?.length === 0) && (
                <option value="strategy_b_v1">strategy_b_v1</option>
              )}
            </select>
          </div>

          <div>
            <label className="h-caption block mb-2">{t('backtest.universe')}</label>
            <input className="input" value={universe} onChange={(e) => setUniverse(e.target.value.toUpperCase())} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="h-caption block mb-2">{t('backtest.startDate')}</label>
              <input className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>
            <div>
              <label className="h-caption block mb-2">{t('backtest.endDate')}</label>
              <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
          </div>

          <div>
            <label className="h-caption block mb-2">{t('backtest.initialCash')}</label>
            <input
              className="input tabular"
              type="number"
              step="1000"
              value={initialCash}
              onChange={(e) => setInitialCash(e.target.value)}
            />
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="w-4 h-4 accent-cyan"
              checked={enableRisk}
              onChange={(e) => setEnableRisk(e.target.checked)}
            />
            <span className="text-body-sm text-text-primary">{t('backtest.enableRiskGuard')}</span>
          </label>

          <button
            type="submit"
            className="btn-primary w-full"
            disabled={runMut.isPending}
          >
            <Play size={14} /> {runMut.isPending ? t('backtest.running') : t('backtest.runBacktest')}
          </button>
          <p className="text-caption text-text-muted">{t('backtest.runHint')}</p>
        </form>

        {/* Runs list */}
        <div className="col-span-7 card">
          <SectionHeader title={t('backtest.history')} subtitle={t('backtest.historyCount', { count: runsQ.data?.items?.length ?? 0 })} />
          <RunsList q={runsQ} onSelect={onSelect} t={t} />
        </div>
      </div>
    </div>
  );
}

function RunsList({ q, onSelect, t }) {
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={FlaskConical} title={t('backtest.noBacktests')} hint={t('backtest.noBacktestsHint')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>ID</th>
          <th>{t('backtest.strategyType')}</th>
          <th>{t('common.time')}</th>
          <th className="tbl-num">{t('backtest.initialCash')}</th>
          <th className="tbl-num">{t('backtest.metrics.finalEquity')}</th>
          <th className="tbl-num">{t('backtest.metrics.sharpe')}</th>
          <th className="tbl-num">{t('backtest.metrics.maxDrawdown')}</th>
          <th>{t('common.status')}</th>
          <th>{t('common.time')}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => {
          const dd = parseFloat(r.metrics?.max_drawdown ?? 0);
          const sharpe = parseFloat(r.metrics?.sharpe ?? 0);
          const final = parseFloat(r.final_equity ?? r.initial_cash ?? 0);
          return (
            <tr key={r.id} className="cursor-pointer" onClick={() => onSelect(r.id)}>
              <td className="font-mono text-steel-200">#{r.id}</td>
              <td className="font-medium text-steel-50">{r.strategy_name}</td>
              <td className="text-steel-200">{r.start_date} → {r.end_date}</td>
              <td className="tbl-num">{fmtUsd(parseFloat(r.initial_cash))}</td>
              <td className="tbl-num font-medium">{fmtUsd(final)}</td>
              <td className="tbl-num">{sharpe.toFixed(2)}</td>
              <td className={classNames('tbl-num', dd < 0 ? 'text-bear' : 'text-steel-100')}>
                {fmtPct(dd * 100)}
              </td>
              <td><StatusBadge status={r.status} /></td>
              <td className="text-caption text-steel-200">{fmtRelativeTime(r.finished_at)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function BacktestDetail({ runId, onBack }) {
  const { t } = useTranslation();
  const detailQ = useQuery({ queryKey: ['backtest-run', runId], queryFn: () => getBacktestRun(runId) });
  const curveQ = useQuery({ queryKey: ['backtest-equity', runId], queryFn: () => getBacktestEquityCurve(runId) });

  if (detailQ.isLoading) return <LoadingState rows={6} />;
  if (detailQ.isError) return <ErrorState error={detailQ.error} onRetry={detailQ.refetch} />;
  const summary = detailQ.data?.summary || {};
  const trades = detailQ.data?.trades || [];
  const metrics = summary.metrics || {};

  const points = (curveQ.data?.points || []).map((p) => ({ t: p.timestamp?.slice(0, 10) || '', v: p.equity }));

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button className="btn-secondary btn-sm" onClick={onBack}>
          <ArrowLeft size={14} /> {t('backtest.back')}
        </button>
        <h1 className="h-page">{t('backtest.title')} #{runId}</h1>
        <StatusBadge status={summary.status} />
      </div>
      <div className="text-body-sm text-text-secondary font-mono">
        {summary.strategy_name} · {summary.start_date} → {summary.end_date} · {fmtUsd(summary.initial_cash)}
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-4 gap-6">
        <KpiCard label={t('backtest.metrics.finalEquity')} value={fmtUsd(summary.final_equity)} delta={null} />
        <KpiCard label={t('backtest.metrics.totalReturn')} value={fmtPct((metrics.total_return || 0) * 100)} delta={null} />
        <KpiCard label={t('backtest.metrics.sharpe')} value={(metrics.sharpe || 0).toFixed(2)} delta={null} />
        <KpiCard label={t('backtest.metrics.maxDrawdown')} value={fmtPct((metrics.max_drawdown || 0) * 100)} delta={null} />
        <KpiCard label={t('backtest.metrics.sortino')} value={(metrics.sortino || 0).toFixed(2)} delta={null} />
        <KpiCard label={t('backtest.metrics.calmar')} value={(metrics.calmar || 0).toFixed(2)} delta={null} />
        <KpiCard label={t('backtest.metrics.winRate')} value={fmtPct((metrics.win_rate || 0) * 100, { withSign: false })} delta={null} />
        <KpiCard label={t('backtest.metrics.profitFactor')} value={(metrics.profit_factor || 0).toFixed(2)} delta={null} />
      </div>

      {/* Equity curve */}
      <div className="card">
        <SectionHeader title={t('backtest.equityCurve')} subtitle={t('backtest.equityCurvePoints', { n: points.length })} />
        {points.length === 0 ? (
          <EmptyState title={t('backtest.noEquityCurve')} />
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <defs>
                  <linearGradient id="btFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#5BA3C6" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#5BA3C6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
                <XAxis dataKey="t" stroke="#7C8A9A" fontSize={11} tickLine={false} />
                <YAxis stroke="#7C8A9A" fontSize={11} tickLine={false} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ background: '#0F1923', border: '1px solid #3D7FA5', borderRadius: 6, color: '#E8ECF1', fontSize: 12 }}
                  formatter={(v) => fmtUsd(v)}
                />
                <Area type="monotone" dataKey="v" stroke="#5BA3C6" strokeWidth={2} fill="url(#btFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Trades */}
      <div className="card">
        <SectionHeader title={t('backtest.trades')} subtitle={t('backtest.tradesCount', { n: trades.length })} />
        {trades.length === 0 ? (
          <EmptyState title={t('backtest.noTrades')} />
        ) : (
          <table className="tbl tbl-dense">
            <thead>
              <tr>
                <th>{t('common.time')}</th>
                <th>{t('common.symbol')}</th>
                <th>{t('portfolio.columns.type')}</th>
                <th className="tbl-num">{t('common.qty')}</th>
                <th className="tbl-num">{t('common.price')}</th>
                <th className="tbl-num">{t('quantlab.fields.notional')}</th>
                <th>{t('portfolio.columns.reason')}</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i}>
                  <td className="text-steel-200">{(t.timestamp || '').slice(0, 16).replace('T', ' ')}</td>
                  <td className="font-medium text-steel-50">{t.symbol}</td>
                  <td>
                    <span className={classNames('uppercase font-semibold', t.side === 'buy' ? 'text-bull' : 'text-bear')}>
                      {t.side}
                    </span>
                  </td>
                  <td className="tbl-num">{parseFloat(t.qty).toFixed(4)}</td>
                  <td className="tbl-num">{fmtUsd(parseFloat(t.price))}</td>
                  <td className="tbl-num">{fmtSignedUsd(t.side === 'sell' ? t.notional : -t.notional)}</td>
                  <td className="text-caption text-steel-200">{t.reason || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
