import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Activity, Database, Zap, History as HistoryIcon, Map as MapIcon } from 'lucide-react';
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import {
  listFactors, getFactorDetail, getActiveUniverse,
  listFactorRuns,
  getEvolutionStatus, startEvolution, stopEvolution,
  getEvolutionHistory, getEvolutionPopulation,
  getFactorLandscape,
} from '../lib/api.js';
import {
  PageHeader, SectionHeader, LoadingState, ErrorState, EmptyState,
} from '../components/primitives.jsx';
import { classNames, fmtUsd } from '../lib/format.js';

const TABS = [
  { id: 'library',   icon: Database,    label: '库' },
  { id: 'evolution', icon: Activity,    label: '演化曲线' },
  { id: 'landscape', icon: MapIcon,     label: '基因图谱' },
  { id: 'universe',  icon: Zap,         label: '活跃股' },
  { id: 'runs',      icon: HistoryIcon, label: '运行记录' },
];

const tooltipStyle = {
  background: '#0F1923', border: '1px solid #3D7FA5',
  borderRadius: 6, color: '#E8ECF1', fontSize: 12,
};

export default function FactorsPage() {
  const [tab, setTab] = useState('library');
  return (
    <div className="space-y-4">
      <PageHeader
        moduleId={21}
        title="因子工厂"
        segments={[{ label: 'FACTOR', accent: true }, { label: 'FORGE' }]}
      />
      <HeroPanel />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2"><PopulationGrid /></div>
        <EventFeed />
      </div>
      <TabBar value={tab} onChange={setTab} />
      <div className="card">
        {tab === 'library'   && <LibraryTab />}
        {tab === 'evolution' && <EvolutionChart />}
        {tab === 'landscape' && <LandscapeTab />}
        {tab === 'universe'  && <UniverseTab />}
        {tab === 'runs'      && <RunsTab />}
      </div>
    </div>
  );
}

function HeroPanel() {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ['evolution-status'],
    queryFn: getEvolutionStatus,
    refetchInterval: 5_000,
  });
  const historyQ = useQuery({
    queryKey: ['evolution-history-spark'],
    queryFn: () => getEvolutionHistory(50),
    refetchInterval: 10_000,
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
  const dot = running ? 'bg-bull animate-pulse' : 'bg-text-muted';
  const lastDone = s?.last_generation_completed_at
    ? new Date(s.last_generation_completed_at).toLocaleString()
    : '—';
  const histItems = historyQ.data?.items || [];

  const recentBest = s?.best_fitness_recent;
  const olderBest = histItems.length >= 6
    ? histItems[histItems.length - 6]?.best_fitness
    : null;
  const delta = recentBest != null && olderBest != null && olderBest !== 0
    ? ((recentBest - olderBest) / Math.abs(olderBest)) * 100
    : null;
  const deltaTone = delta == null ? 'text-text-muted'
    : delta > 0 ? 'text-bull' : delta < 0 ? 'text-bear' : 'text-text-muted';

  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <span className={classNames('w-2.5 h-2.5 rounded-full', dot)} />
          <span className="font-mono text-[11px] tracking-[0.15em] uppercase text-text-secondary">
            {running ? '进化中' : '已停止'}
          </span>
          <Stat label="代" value={s?.current_generation ?? 0} />
          <Stat label="best" value={recentBest != null ? recentBest.toFixed(4) : '—'} />
          {delta != null && (
            <span className={classNames('font-mono text-caption', deltaTone)}>
              {delta >= 0 ? '↑' : '↓'} 较 5 代前 {delta >= 0 ? '+' : ''}{delta.toFixed(1)}%
            </span>
          )}
          <Stat label="种群" value={s?.population_size ?? 0} />
          <Stat label="库" value={s?.library_count ?? 0} />
          <Stat label="last gen" value={lastDone} />
        </div>
        <div>
          {running ? (
            <button
              type="button"
              onClick={() => stopM.mutate()}
              disabled={stopM.isPending}
              className="px-3 py-1 border border-bear/40 text-bear font-mono text-[10px] tracking-[0.15em] uppercase hover:bg-bear/10 disabled:opacity-50"
            >{stopM.isPending ? '停止中…' : '停止'}</button>
          ) : (
            <button
              type="button"
              onClick={() => startM.mutate()}
              disabled={startM.isPending}
              className="px-3 py-1 border border-cyan/40 text-cyan font-mono text-[10px] tracking-[0.15em] uppercase hover:bg-cyan/10 disabled:opacity-50"
            >{startM.isPending ? '启动中…' : '启动'}</button>
          )}
        </div>
      </div>
      {s?.error && (
        <div className="text-rose-400 text-caption font-mono">上次出错: {String(s.error).slice(0, 200)}</div>
      )}
      <Sparkline data={histItems} />
    </div>
  );
}

function Sparkline({ data }) {
  if (!data || data.length < 2) {
    return <div className="h-12 text-caption text-text-muted">等待第一代完成…</div>;
  }
  const points = data.map((d) => ({ g: d.generation, v: d.best_fitness ?? 0 }));
  return (
    <div className="h-12">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points}>
          <Line type="monotone" dataKey="v" stroke="#5BA3C6" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
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

function PopulationGrid() {
  const popQ = useQuery({
    queryKey: ['evolution-pop'],
    queryFn: getEvolutionPopulation,
    refetchInterval: 5_000,
  });
  const [focused, setFocused] = useState(null);
  if (popQ.isLoading) return <div className="card"><LoadingState rows={3} /></div>;
  if (popQ.isError) return <div className="card"><ErrorState error={popQ.error} onRetry={popQ.refetch} /></div>;
  const slots = popQ.data?.slots || [];
  if (!slots.length) return <div className="card"><EmptyState title="种群空" hint="等待第一代播种…" /></div>;

  const fits = slots.map((s) => s.fitness).filter((f) => f > -50);
  const minF = fits.length ? Math.min(...fits) : 0;
  const maxF = fits.length ? Math.max(...fits) : 0;
  const range = (maxF - minF) || 1;

  return (
    <div className="card space-y-3">
      <div className="flex items-baseline justify-between">
        <SectionHeader title="当代种群" subtitle={`gen ${popQ.data.generation} · ${slots.length} slots`} />
        <span className="text-caption text-text-muted font-mono">
          best {fits.length ? maxF.toFixed(4) : '—'} · worst {fits.length ? minF.toFixed(4) : '—'}
        </span>
      </div>
      <div className="grid grid-cols-10 gap-1.5">
        {slots.map((slot) => {
          const f = slot.fitness;
          const failed = f < -50;
          const t = failed ? 0 : (f - minF) / range;
          const bg = failed ? '#2A3645'
            : `hsl(${Math.round(t * 130)}, 60%, ${30 + Math.round(t * 25)}%)`;
          return (
            <button
              key={slot.slot}
              type="button"
              onClick={() => setFocused(slot)}
              title={`#${slot.slot} fit=${f.toFixed(4)}\n${slot.formula}`}
              className="aspect-square border border-border-subtle hover:ring-1 hover:ring-cyan transition-all"
              style={{ backgroundColor: bg }}
            />
          );
        })}
      </div>
      {focused && (
        <div className="border border-cyan/40 p-3 space-y-1">
          <div className="text-caption text-text-muted font-mono">
            #{focused.slot} · fitness {focused.fitness.toFixed(4)}
          </div>
          <div className="font-mono text-body-sm break-all">{focused.formula}</div>
        </div>
      )}
    </div>
  );
}

function EventFeed() {
  const histQ = useQuery({
    queryKey: ['evolution-history-feed'],
    queryFn: () => getEvolutionHistory(20),
    refetchInterval: 5_000,
  });
  const items = histQ.data?.items ? [...histQ.data.items].reverse() : [];
  return (
    <div className="card max-h-[420px] overflow-y-auto">
      <SectionHeader title="最近事件" subtitle="按代倒序" />
      {!items.length ? (
        <EmptyState title="尚无事件" hint="代完成后这里会更新" />
      ) : (
        <ul className="space-y-1.5 text-caption font-mono">
          {items.map((it) => (
            <li key={it.generation} className="flex items-baseline justify-between gap-2 border-b border-border-subtle/50 pb-1">
              <span className="text-text-muted">
                {new Date(it.completed_at).toLocaleTimeString()}
              </span>
              <span>
                gen {it.generation} · best{' '}
                <span className={it.best_fitness != null && it.best_fitness > 0.02 ? 'text-bull' : 'text-text-secondary'}>
                  {it.best_fitness != null ? it.best_fitness.toFixed(4) : '—'}
                </span>
                {it.persisted_count > 0 ? <span className="text-cyan"> · +{it.persisted_count} → 库</span> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EvolutionChart() {
  const histQ = useQuery({
    queryKey: ['evolution-history-chart'],
    queryFn: () => getEvolutionHistory(500),
    refetchInterval: 15_000,
  });
  if (histQ.isLoading) return <LoadingState rows={6} />;
  if (histQ.isError) return <ErrorState error={histQ.error} onRetry={histQ.refetch} />;
  const items = histQ.data?.items || [];
  if (!items.length) return <EmptyState title="尚无数据" hint="跑过一代后这里会有曲线" />;
  return (
    <div className="space-y-3">
      <SectionHeader title="演化曲线" subtitle="best/median fitness 与每代入库数 · 越老的代越靠左" />
      <div className="h-[400px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={items}>
            <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
            <XAxis dataKey="generation" stroke="#7C8A9A" fontSize={10} />
            <YAxis yAxisId="fit" stroke="#7C8A9A" fontSize={10} />
            <YAxis yAxisId="cnt" orientation="right" stroke="#7C8A9A" fontSize={10} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar yAxisId="cnt" dataKey="persisted_count" fill="#3D7FA5" opacity={0.4} />
            <Line yAxisId="fit" type="monotone" dataKey="median_fitness" stroke="#7C8A9A" strokeWidth={1.2} dot={false} isAnimationActive={false} name="median" />
            <Line yAxisId="fit" type="monotone" dataKey="best_fitness" stroke="#5BA3C6" strokeWidth={1.8} dot={false} isAnimationActive={false} name="best" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function TabBar({ value, onChange }) {
  return (
    <div className="flex gap-1 border-b border-border-subtle font-mono text-[11px] tracking-[0.15em] uppercase">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={classNames(
            'px-4 py-2 border-b-2 -mb-[1px] transition-colors inline-flex items-center gap-1',
            t.id === value ? 'border-cyan text-cyan' : 'border-transparent text-text-muted hover:text-text-primary',
          )}
        >
          <t.icon size={12} /> {t.label}
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

function LandscapeTab() {
  const q = useQuery({
    queryKey: ['factor-landscape'],
    queryFn: () => getFactorLandscape(500),
    refetchInterval: 30_000,
  });
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length < 2) {
    return <EmptyState title="尚无足够因子" hint="库里至少要 2 个因子才能投影" />;
  }
  const fits = items.map((p) => p.fitness).slice().sort((a, b) => a - b);
  const p20 = fits[Math.floor(fits.length * 0.2)];
  const p80 = fits[Math.floor(fits.length * 0.8)];
  const colorOf = (f) => (f >= p80 ? '#22C55E' : f <= p20 ? '#EF4444' : '#7C8A9A');
  const data = items.map((p) => ({ ...p, fill: colorOf(p.fitness) }));
  return (
    <div className="space-y-3">
      <SectionHeader title="基因图谱" subtitle={`${items.length} 个因子的 PCA-2D 嵌入投影 · 按 fitness 着色`} />
      <div className="h-[480px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
            <XAxis type="number" dataKey="x" name="PC1" stroke="#7C8A9A" fontSize={10} />
            <YAxis type="number" dataKey="y" name="PC2" stroke="#7C8A9A" fontSize={10} />
            <ZAxis type="number" range={[40, 200]} dataKey="fitness" />
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              content={({ payload }) => {
                const pt = payload?.[0]?.payload;
                if (!pt) return null;
                return (
                  <div style={tooltipStyle} className="p-2 max-w-md">
                    <div className="font-mono text-caption text-text-muted">#{pt.id}</div>
                    <div className="font-mono text-body-sm break-all">{pt.formula}</div>
                    <div className="font-mono text-caption mt-1">fitness {pt.fitness.toFixed(4)}</div>
                  </div>
                );
              }}
            />
            <Scatter name="Factors" data={data} fill="#5BA3C6" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-4 text-caption font-mono">
        <span className="inline-flex items-center gap-1"><span className="w-2 h-2 bg-bull rounded-full" /> top 20%</span>
        <span className="inline-flex items-center gap-1"><span className="w-2 h-2 bg-text-muted rounded-full" /> middle</span>
        <span className="inline-flex items-center gap-1"><span className="w-2 h-2 bg-bear rounded-full" /> bottom 20%</span>
      </div>
    </div>
  );
}
