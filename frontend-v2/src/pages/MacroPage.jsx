// MacroPage — FRED macro indicator dashboard.
// Data shape comes from /api/macro:
//   - indicators: list of MacroIndicatorView (value/signal/sparkline/...)
//   - ensemble:   { total_core, signals: { ok, warn, danger, neutral } }
//
// Borrowed from Tradewell's /macro page; redesigned to NewBird's Tokyo cyber theme.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import { getMacroDashboard, refreshMacroDashboard } from '../lib/api.js';
import {
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
  SignalDot,
} from '../components/primitives.jsx';
import { classNames, fmtRelativeTime } from '../lib/format.js';

const CATEGORY_KEYS = ['inflation', 'liquidity', 'rates', 'credit', 'growth', 'fx', 'vol'];

export default function MacroPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const macroQ = useQuery({
    queryKey: ['macro'],
    queryFn: getMacroDashboard,
    refetchInterval: 5 * 60_000,
    retry: false,
  });
  const refreshMut = useMutation({
    mutationFn: refreshMacroDashboard,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['macro'] }),
  });

  const indicators = macroQ.data?.indicators || [];
  const ensemble = macroQ.data?.ensemble || { total_core: 0, signals: {} };

  // Group indicators by category for the per-section grids.
  const byCategory = new Map();
  for (const row of indicators) {
    if (!byCategory.has(row.category)) byCategory.set(row.category, []);
    byCategory.get(row.category).push(row);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={6}
        title={t('macro.title')}
        segments={[{ label: t('macro.subtitle') }]}
      />

      <div className="flex justify-end -mt-4">
        <button
          className="btn-secondary btn-sm"
          onClick={() => refreshMut.mutate()}
          disabled={refreshMut.isPending}
        >
          <RefreshCw size={12} className={refreshMut.isPending ? 'animate-spin' : ''} />
          {t('macro.refreshNow')}
        </button>
      </div>

      {macroQ.isLoading ? (
        <LoadingState rows={6} label={t('macro.loading')} />
      ) : macroQ.isError ? (
        <ErrorState error={macroQ.error} onRetry={macroQ.refetch} />
      ) : indicators.length === 0 ? (
        <EmptyState
          title={t('macro.empty')}
          hint={t('macro.emptyHint')}
        />
      ) : (
        <>
          {/* Ensemble summary KPIs */}
          <div className="card">
            <SectionHeader
              title={t('macro.ensembleTitle')}
              subtitle={`${ensemble.total_core} ${t('macro.coreIndicators')}`}
              meta={
                macroQ.data?.generated_at
                  ? `${t('macro.lastUpdate')}: ${fmtRelativeTime(macroQ.data.generated_at)}`
                  : null
              }
            />
            <div className="grid grid-cols-4 gap-px bg-border-subtle">
              <SummaryCell label={t('macro.signalOk')} count={ensemble.signals?.ok ?? 0} total={ensemble.total_core} tone="ok" />
              <SummaryCell label={t('macro.signalWarn')} count={ensemble.signals?.warn ?? 0} total={ensemble.total_core} tone="warn" />
              <SummaryCell label={t('macro.signalDanger')} count={ensemble.signals?.danger ?? 0} total={ensemble.total_core} tone="danger" />
              <SummaryCell label={t('macro.signalNeutral')} count={ensemble.signals?.neutral ?? 0} total={ensemble.total_core} tone="neutral" />
            </div>
          </div>

          {CATEGORY_KEYS.map((cat) => {
            const rows = byCategory.get(cat);
            if (!rows || rows.length === 0) return null;
            return (
              <div key={cat} className="card">
                <SectionHeader
                  title={t(`macro.categories.${cat}`)}
                  subtitle={`${rows.length} ${t('macro.indicatorsLabel')}`}
                />
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {rows.map((row) => (
                    <IndicatorCard key={row.code} row={row} t={t} />
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function SummaryCell({ label, count, total, tone }) {
  const toneClass =
    tone === 'ok' ? 'text-bull' :
    tone === 'warn' ? 'text-warn' :
    tone === 'danger' ? 'text-bear' :
    'text-text-muted';
  return (
    <div className="bg-surface px-5 py-4">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.2em] uppercase mb-2">
        {label}
      </div>
      <div className="flex items-baseline gap-2">
        <span className={classNames('font-display font-light text-[36px] tabular leading-none', toneClass)}>
          {count}
        </span>
        <span className="font-mono text-[11px] text-text-muted">/ {total}</span>
      </div>
    </div>
  );
}

function IndicatorCard({ row, t }) {
  const value = row.value;
  const localizedTitle = t(row.i18n_key, { defaultValue: row.code });
  const localizedDesc = t(row.description_key, { defaultValue: '' });
  const valueText =
    value === null || value === undefined
      ? '—'
      : Math.abs(value) >= 100
        ? value.toFixed(0)
        : Math.abs(value) >= 10
          ? value.toFixed(1)
          : value.toFixed(2);
  return (
    <div className="border border-border-subtle p-4 hover:border-cyan transition duration-150 relative">
      <div className="flex items-start justify-between mb-2">
        <div className="min-w-0">
          <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase">{row.code}</div>
          <div className="text-body font-medium text-text-primary truncate">{localizedTitle}</div>
        </div>
        <SignalDot tone={signalTone(row.signal)} />
      </div>
      <div className="flex items-baseline gap-2 mb-3">
        <span className="font-display text-[28px] font-light text-text-primary tabular leading-none">
          {valueText}
        </span>
        {row.unit && <span className="font-mono text-[12px] text-text-muted">{row.unit}</span>}
        {row.is_ensemble_core && (
          <span className="ml-auto text-[10px] font-mono tracking-[0.15em] text-cyan">★ CORE</span>
        )}
      </div>
      {row.sparkline && row.sparkline.length > 1 && (
        <div className="h-10 -mx-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={row.sparkline.map((p) => ({ x: p.as_of, y: p.value }))}>
              <defs>
                <linearGradient id={`grad-${row.code}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#5BA3C6" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#5BA3C6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="y" stroke="#5BA3C6" strokeWidth={1.5} fill={`url(#grad-${row.code})`} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      {localizedDesc && (
        <div className="text-caption text-text-muted mt-2 leading-relaxed">{localizedDesc}</div>
      )}
      {row.as_of && (
        <div className="font-mono text-[10px] text-text-muted mt-2 tracking-[0.1em]">
          {row.as_of}
        </div>
      )}
    </div>
  );
}

function signalTone(signal) {
  if (signal === 'ok') return 'ok';
  if (signal === 'warn') return 'warn';
  if (signal === 'danger') return 'danger';
  return 'neutral';
}
