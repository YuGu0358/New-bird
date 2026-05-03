import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Activity, Database, Cpu, Play } from 'lucide-react';
import {
  listFactors, getFactorDetail, getActiveUniverse,
  listFactorRuns,
  getEvolutionStatus, startEvolution, stopEvolution,
} from '../lib/api.js';
import {
  PageHeader, SectionHeader, LoadingState, ErrorState, EmptyState,
} from '../components/primitives.jsx';
import { classNames, fmtUsd } from '../lib/format.js';

const TABS = [
  { id: 'library', icon: Database, label: 'nav.factors' },
  { id: 'universe', icon: Activity, label: 'factors.universe' },
  { id: 'runs', icon: Cpu, label: 'factors.runs' },
];

export default function FactorsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState('library');
  return (
    <div className="space-y-4">
      <PageHeader
        moduleId={21}
        title={t('factors.title', '因子工厂')}
        segments={[{ label: 'FACTOR', accent: true }, { label: 'FORGE' }]}
      />
      <StatusBanner />
      <TabBar value={tab} onChange={setTab} />
      <div className="card">
        {tab === 'library' && <LibraryTab />}
        {tab === 'universe' && <UniverseTab />}
        {tab === 'runs' && <RunsTab />}
      </div>
    </div>
  );
}

function StatusBanner() {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ['evolution-status'],
    queryFn: getEvolutionStatus,
    refetchInterval: 5_000,
  });
  const startM = useMutation({
    mutationFn: startEvolution,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evolution-status'] }),
  });
  const stopM = useMutation({
    mutationFn: stopEvolution,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evolution-status'] }),
  });

  const s = statusQ.data;
  const running = !!s?.is_running;
  const dotClass = running ? 'bg-bull animate-pulse' : 'bg-text-muted';
  const lastDone = s?.last_generation_completed_at
    ? new Date(s.last_generation_completed_at).toLocaleString()
    : '—';

  return (
    <div className="card flex items-center justify-between flex-wrap gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className={classNames('w-2.5 h-2.5 rounded-full', dotClass)} />
        <span className="font-mono text-[11px] tracking-[0.15em] uppercase text-text-secondary">
          {running ? '进化中' : '已停止'}
        </span>
        <Stat label="代" value={s?.current_generation ?? 0} />
        <Stat label="best" value={s?.best_fitness_recent != null ? s.best_fitness_recent.toFixed(4) : '—'} />
        <Stat label="种群" value={s?.population_size ?? 0} />
        <Stat label="库" value={s?.library_count ?? 0} />
        <Stat label="last gen" value={lastDone} />
      </div>
      <div className="flex items-center gap-2">
        {running ? (
          <button
            type="button"
            onClick={() => stopM.mutate()}
            disabled={stopM.isPending}
            className="px-3 py-1 border border-bear/40 text-bear font-mono text-[10px] tracking-[0.15em] uppercase hover:bg-bear/10 disabled:opacity-50"
          >
            {stopM.isPending ? '停止中…' : '停止'}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => startM.mutate()}
            disabled={startM.isPending}
            className="px-3 py-1 border border-cyan/40 text-cyan font-mono text-[10px] tracking-[0.15em] uppercase hover:bg-cyan/10 disabled:opacity-50"
          >
            {startM.isPending ? '启动中…' : '启动'}
          </button>
        )}
      </div>
      {s?.error ? (
        <div className="basis-full text-rose-400 text-caption font-mono">
          上次出错: {String(s.error).slice(0, 200)}
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-text-muted text-caption uppercase tracking-[0.1em]">{label}</span>
      <span className="font-mono text-body-sm">{value}</span>
    </div>
  );
}

function TabBar({ value, onChange }) {
  const { t } = useTranslation();
  return (
    <div className="flex gap-1 border-b border-border-subtle font-mono text-[11px] tracking-[0.15em] uppercase">
      {TABS.map((tabDef) => (
        <button
          key={tabDef.id}
          type="button"
          onClick={() => onChange(tabDef.id)}
          className={classNames(
            'px-4 py-2 border-b-2 -mb-[1px] transition-colors',
            tabDef.id === value
              ? 'border-cyan text-cyan'
              : 'border-transparent text-text-muted hover:text-text-primary',
          )}
        >
          {t(tabDef.label, tabDef.id)}
        </button>
      ))}
    </div>
  );
}

function LibraryTab() {
  const [selectedId, setSelectedId] = useState(null);
  const q = useQuery({
    queryKey: ['factor-library'],
    queryFn: () => listFactors({ limit: 100, sort_by: 'fitness' }),
    refetchInterval: 60_000,
  });
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (!items.length) return <EmptyState title="尚无因子" hint="等待第一次进化运行完成" />;
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="md:col-span-2 overflow-x-auto">
        <table className="w-full text-body-sm font-mono">
          <thead className="text-text-muted text-[10px] tracking-[0.15em] uppercase">
            <tr>
              <th className="text-left p-2">Formula</th>
              <th className="text-right p-2">Fit</th>
              <th className="text-right p-2">IC5</th>
              <th className="text-right p-2">Sharpe</th>
              <th className="text-right p-2">DD</th>
              <th className="text-right p-2">Gen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr
                key={f.id}
                onClick={() => setSelectedId(f.id)}
                className={classNames(
                  'border-t border-border-subtle cursor-pointer hover:bg-cyan/5',
                  selectedId === f.id ? 'bg-cyan/10' : '',
                )}
              >
                <td className="p-2 max-w-md truncate" title={f.formula}>{f.formula}</td>
                <td className="p-2 text-right">{f.fitness?.toFixed(4) ?? '—'}</td>
                <td className="p-2 text-right">{f.ic_5d?.toFixed(4) ?? '—'}</td>
                <td className="p-2 text-right">{f.sharpe?.toFixed(2) ?? '—'}</td>
                <td className="p-2 text-right text-bear">
                  {f.max_drawdown != null ? `${(f.max_drawdown * 100).toFixed(1)}%` : '—'}
                </td>
                <td className="p-2 text-right text-text-muted">{f.generation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <FactorDetail id={selectedId} />
    </div>
  );
}

function FactorDetail({ id }) {
  const q = useQuery({
    queryKey: ['factor-detail', id],
    queryFn: () => getFactorDetail(id),
    enabled: !!id,
  });
  if (!id) return <div className="card text-text-muted text-body-sm">点击表格中一行查看详情</div>;
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const f = q.data;
  return (
    <div className="card space-y-3">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
        Factor #{f.id}
      </div>
      <div className="font-mono text-body-sm break-all">{f.formula}</div>
      <div className="grid grid-cols-2 gap-2 text-body-sm">
        <Metric label="Fitness"   value={f.fitness?.toFixed(4)} />
        <Metric label="IC 1d"     value={f.ic_1d?.toFixed(4)} />
        <Metric label="IC 5d"     value={f.ic_5d?.toFixed(4)} />
        <Metric label="IC 20d"    value={f.ic_20d?.toFixed(4)} />
        <Metric label="ICIR"      value={f.icir?.toFixed(2)} />
        <Metric label="Sharpe"    value={f.sharpe?.toFixed(2)} />
        <Metric label="Max DD"    value={f.max_drawdown != null ? `${(f.max_drawdown * 100).toFixed(1)}%` : '—'} />
        <Metric label="Turnover"  value={f.turnover != null ? `${(f.turnover * 100).toFixed(1)}%` : '—'} />
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div>
      <div className="text-text-muted text-caption">{label}</div>
      <div className="font-mono">{value ?? '—'}</div>
    </div>
  );
}

function UniverseTab() {
  const today = new Date().toISOString().slice(0, 10);
  const q = useQuery({
    queryKey: ['active-universe', today],
    queryFn: () => getActiveUniverse(today, 100),
    refetchInterval: 60_000,
  });
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (!items.length) return <EmptyState title="今日尚无活跃股名单" hint="等待收盘后任务完成" />;
  return (
    <div className="overflow-x-auto">
      <SectionHeader title={`${q.data?.date} · Top ${items.length}`} subtitle="活跃股按综合分数排序" />
      <table className="w-full text-body-sm font-mono">
        <thead className="text-text-muted text-[10px] tracking-[0.15em] uppercase">
          <tr>
            <th className="text-left p-2">#</th>
            <th className="text-left p-2">Symbol</th>
            <th className="text-right p-2">Activity</th>
            <th className="text-right p-2">$Volume</th>
          </tr>
        </thead>
        <tbody>
          {items.map((u) => (
            <tr key={u.symbol} className="border-t border-border-subtle">
              <td className="p-2">{u.rank}</td>
              <td className="p-2">{u.symbol}</td>
              <td className="p-2 text-right">{u.activity_score?.toFixed(2)}</td>
              <td className="p-2 text-right">{fmtUsd(u.dollar_volume)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunsTab() {
  const q = useQuery({
    queryKey: ['factor-runs'],
    queryFn: () => listFactorRuns(20),
    refetchInterval: 30_000,
  });
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (!items.length) return <EmptyState title="无运行记录" hint="点击 立即运行 触发第一次" />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body-sm font-mono">
        <thead className="text-text-muted text-[10px] tracking-[0.15em] uppercase">
          <tr>
            <th className="text-left p-2">Run #</th>
            <th className="text-left p-2">Started</th>
            <th className="text-left p-2">Status</th>
            <th className="text-right p-2">S1 best</th>
            <th className="text-right p-2">S2 best</th>
            <th className="text-right p-2">Persisted</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id} className="border-t border-border-subtle">
              <td className="p-2">{r.id}</td>
              <td className="p-2 text-text-muted">{new Date(r.started_at).toLocaleString()}</td>
              <td className="p-2">
                <span className={classNames(
                  'px-1.5 py-0.5 border text-[10px] uppercase tracking-[0.1em]',
                  r.status === 'completed' ? 'border-bull text-bull'
                    : r.status === 'failed' ? 'border-bear text-bear'
                    : 'border-cyan text-cyan',
                )}>{r.status}</span>
              </td>
              <td className="p-2 text-right">{r.stage1_best?.toFixed(4) ?? '—'}</td>
              <td className="p-2 text-right">{r.stage2_best?.toFixed(4) ?? '—'}</td>
              <td className="p-2 text-right">{r.total_persisted}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
