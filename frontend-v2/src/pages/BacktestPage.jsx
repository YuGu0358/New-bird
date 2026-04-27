import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">Backtest</h1>
          <p className="text-body-sm text-steel-200 mt-1">P3 引擎 · 同一 Strategy ABC 实盘+回测共用。</p>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* New backtest form */}
        <form onSubmit={submit} className="col-span-5 card space-y-4">
          <SectionHeader title="新建回测" />
          {runMut.isError && <ApiErrorBanner error={runMut.error} label="回测失败" />}
          {runMut.isSuccess && (
            <div className="border border-bull/40 rounded-md bg-bull-tint px-3 py-2 text-body-sm text-bull">
              ✓ 已提交 — run #{runMut.data?.id}
            </div>
          )}

          <div>
            <label className="h-caption block mb-2">策略类型</label>
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
            <label className="h-caption block mb-2">Universe (逗号分隔)</label>
            <input className="input" value={universe} onChange={(e) => setUniverse(e.target.value.toUpperCase())} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="h-caption block mb-2">起始日期</label>
              <input className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>
            <div>
              <label className="h-caption block mb-2">结束日期</label>
              <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
          </div>

          <div>
            <label className="h-caption block mb-2">初始资金 (USD)</label>
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
              className="w-4 h-4 accent-steel-500"
              checked={enableRisk}
              onChange={(e) => setEnableRisk(e.target.checked)}
            />
            <span className="text-body-sm text-steel-100">启用风控政策(P4 RiskGuard)</span>
          </label>

          <button
            type="submit"
            className="btn-primary w-full"
            disabled={runMut.isPending}
          >
            <Play size={14} /> {runMut.isPending ? 'Running…' : '运行回测'}
          </button>
          <p className="text-caption text-steel-300">
            后端会同步阻塞跑完(yfinance 数据下载 + 模拟交易)。大区间可能需要几十秒。
          </p>
        </form>

        {/* Runs list */}
        <div className="col-span-7 card">
          <SectionHeader title="回测历史" subtitle={`最近 ${runsQ.data?.items?.length ?? 0} 次`} />
          <RunsList q={runsQ} onSelect={onSelect} />
        </div>
      </div>
    </div>
  );
}

function RunsList({ q, onSelect }) {
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={FlaskConical} title="还没跑过回测" hint="左侧表单提交一次。" />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>ID</th>
          <th>策略</th>
          <th>区间</th>
          <th className="tbl-num">Initial</th>
          <th className="tbl-num">Final equity</th>
          <th className="tbl-num">Sharpe</th>
          <th className="tbl-num">Max DD</th>
          <th>Status</th>
          <th>Time</th>
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
  const detailQ = useQuery({ queryKey: ['backtest-run', runId], queryFn: () => getBacktestRun(runId) });
  const curveQ = useQuery({ queryKey: ['backtest-equity', runId], queryFn: () => getBacktestEquityCurve(runId) });

  if (detailQ.isLoading) return <LoadingState rows={6} label="Loading run…" />;
  if (detailQ.isError) return <ErrorState error={detailQ.error} onRetry={detailQ.refetch} />;
  const summary = detailQ.data?.summary || {};
  const trades = detailQ.data?.trades || [];
  const metrics = summary.metrics || {};

  const points = (curveQ.data?.points || []).map((p) => ({ t: p.timestamp?.slice(0, 10) || '', v: p.equity }));

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button className="btn-secondary btn-sm" onClick={onBack}>
          <ArrowLeft size={14} /> 返回列表
        </button>
        <h1 className="h-page">Backtest #{runId}</h1>
        <StatusBadge status={summary.status} />
      </div>
      <div className="text-body-sm text-steel-200">
        {summary.strategy_name} · {summary.start_date} → {summary.end_date} · 初始 {fmtUsd(summary.initial_cash)}
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-4 gap-6">
        <KpiCard label="Final equity" value={fmtUsd(summary.final_equity)} delta={null} />
        <KpiCard label="Total return" value={fmtPct((metrics.total_return || 0) * 100)} delta={null} />
        <KpiCard label="Sharpe" value={(metrics.sharpe || 0).toFixed(2)} delta={null} />
        <KpiCard label="Max drawdown" value={fmtPct((metrics.max_drawdown || 0) * 100)} delta={null} />
        <KpiCard label="Sortino" value={(metrics.sortino || 0).toFixed(2)} delta={null} />
        <KpiCard label="Calmar" value={(metrics.calmar || 0).toFixed(2)} delta={null} />
        <KpiCard label="Win rate" value={fmtPct((metrics.win_rate || 0) * 100, { withSign: false })} delta={null} />
        <KpiCard label="Profit factor" value={(metrics.profit_factor || 0).toFixed(2)} delta={null} />
      </div>

      {/* Equity curve */}
      <div className="card">
        <SectionHeader title="净值曲线" subtitle={`${points.length} 个数据点`} />
        {points.length === 0 ? (
          <EmptyState title="无 equity curve" />
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
        <SectionHeader title="成交明细" subtitle={`${trades.length} 条`} />
        {trades.length === 0 ? (
          <EmptyState title="无成交" />
        ) : (
          <table className="tbl tbl-dense">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="tbl-num">Qty</th>
                <th className="tbl-num">Price</th>
                <th className="tbl-num">Notional</th>
                <th>Reason</th>
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
