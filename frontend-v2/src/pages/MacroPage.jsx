// MacroPage — FRED macro indicator dashboard.
// Data shape comes from /api/macro:
//   - indicators: list of MacroIndicatorView (value/signal/sparkline/...)
//   - ensemble:   { total_core, signals: { ok, warn, danger, neutral } }
//
// Borrowed from Tradewell's /macro page; redesigned to NewBird's Tokyo cyber theme.
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { RefreshCw, Sliders, RotateCcw, Save, X as XIcon, CalendarDays } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import {
  getMacroDashboard,
  refreshMacroDashboard,
  updateIndicatorThresholds,
  resetIndicatorThresholds,
  getEconomicCalendar,
} from '../lib/api.js';
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
  const [editingCode, setEditingCode] = useState(null);
  const [tab, setTab] = useState('indicators'); // 'indicators' | 'calendar'

  const macroQ = useQuery({
    queryKey: ['macro'],
    queryFn: getMacroDashboard,
    refetchInterval: 5 * 60_000,
    retry: false,
    enabled: tab === 'indicators',
  });
  const refreshMut = useMutation({
    mutationFn: refreshMacroDashboard,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['macro'] }),
  });
  const editingRow = (macroQ.data?.indicators || []).find((r) => r.code === editingCode) || null;

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

      {/* Tab switcher + actions */}
      <div className="flex items-center justify-between -mt-4">
        <div className="flex items-center gap-1 border border-border-subtle bg-surface">
          <button
            className={classNames(
              'px-4 py-2 text-body-sm transition',
              tab === 'indicators' ? 'bg-elevated text-text-primary' : 'text-text-muted hover:text-text-secondary',
            )}
            onClick={() => setTab('indicators')}
          >
            <Sliders size={12} className="inline -mt-0.5 mr-1.5" />
            {t('macro.tabs.indicators')}
          </button>
          <button
            className={classNames(
              'px-4 py-2 text-body-sm transition',
              tab === 'calendar' ? 'bg-elevated text-text-primary' : 'text-text-muted hover:text-text-secondary',
            )}
            onClick={() => setTab('calendar')}
          >
            <CalendarDays size={12} className="inline -mt-0.5 mr-1.5" />
            {t('macro.tabs.calendar')}
          </button>
        </div>
        {tab === 'indicators' && (
          <button
            className="btn-secondary btn-sm"
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending}
          >
            <RefreshCw size={12} className={refreshMut.isPending ? 'animate-spin' : ''} />
            {t('macro.refreshNow')}
          </button>
        )}
      </div>

      {tab === 'calendar' ? (
        <EconomicCalendarPanel t={t} />
      ) : macroQ.isLoading ? (
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
                    <IndicatorCard
                      key={row.code}
                      row={row}
                      t={t}
                      onEdit={() => setEditingCode(row.code)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}

      {editingRow && (
        <ThresholdEditModal
          row={editingRow}
          t={t}
          onClose={() => setEditingCode(null)}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: ['macro'] });
            setEditingCode(null);
          }}
        />
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

function IndicatorCard({ row, t, onEdit }) {
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
  // Only indicators that aren't purely informational get an edit button —
  // an informational indicator has no signal levels to tune.
  const editable = row.thresholds?.direction !== 'informational';
  return (
    <div className="border border-border-subtle p-4 hover:border-cyan transition duration-150 relative group">
      <div className="flex items-start justify-between mb-2">
        <div className="min-w-0">
          <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase">
            {row.code}
            {row.thresholds_overridden && (
              <span className="ml-2 text-cyan">· {t('macro.customized')}</span>
            )}
          </div>
          <div className="text-body font-medium text-text-primary truncate">{localizedTitle}</div>
        </div>
        <div className="flex items-center gap-2">
          {editable && (
            <button
              onClick={onEdit}
              className="opacity-0 group-hover:opacity-100 transition duration-150 text-text-muted hover:text-cyan"
              title={t('macro.editThresholds')}
            >
              <Sliders size={12} />
            </button>
          )}
          <SignalDot tone={signalTone(row.signal)} />
        </div>
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

/* ---------------------------------------------------------- Threshold edit modal */

function ThresholdEditModal({ row, t, onClose, onSaved }) {
  const initial = row.thresholds || {};
  const [direction, setDirection] = useState(initial.direction || 'higher_is_worse');
  const [okMax, setOkMax] = useState(initial.ok_max ?? '');
  const [warnMax, setWarnMax] = useState(initial.warn_max ?? '');
  const [dangerMax, setDangerMax] = useState(initial.danger_max ?? '');

  const saveMut = useMutation({
    mutationFn: () =>
      updateIndicatorThresholds(row.code, {
        direction,
        ok_max: direction === 'informational' ? null : Number(okMax),
        warn_max: direction === 'informational' ? null : Number(warnMax),
        danger_max: direction === 'informational' ? null : Number(dangerMax),
      }),
    onSuccess: onSaved,
  });
  const resetMut = useMutation({
    mutationFn: () => resetIndicatorThresholds(row.code),
    onSuccess: onSaved,
  });

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center px-4"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border-subtle max-w-md w-full p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="font-mono text-[10px] text-text-muted tracking-[0.2em] uppercase mb-1">
              {row.code}
            </div>
            <h3 className="h-section">{t('macro.editThresholds')}</h3>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary">
            <XIcon size={16} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="h-caption block mb-1">{t('macro.direction')}</label>
            <select
              className="input"
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            >
              <option value="higher_is_worse">{t('macro.higherIsWorse')}</option>
              <option value="higher_is_better">{t('macro.higherIsBetter')}</option>
              <option value="informational">{t('macro.informational')}</option>
            </select>
          </div>

          {direction !== 'informational' && (
            <div className="grid grid-cols-3 gap-3">
              <NumField label={t('macro.okMax')} value={okMax} onChange={setOkMax} />
              <NumField label={t('macro.warnMax')} value={warnMax} onChange={setWarnMax} />
              <NumField label={t('macro.dangerMax')} value={dangerMax} onChange={setDangerMax} />
            </div>
          )}

          <div className="text-caption text-text-muted leading-relaxed">
            {direction === 'higher_is_worse' && t('macro.directionHintWorse')}
            {direction === 'higher_is_better' && t('macro.directionHintBetter')}
            {direction === 'informational' && t('macro.directionHintInfo')}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 mt-6 pt-4 border-t border-border-subtle">
          {row.thresholds_overridden ? (
            <button
              className="btn-secondary btn-sm"
              onClick={() => resetMut.mutate()}
              disabled={resetMut.isPending}
            >
              <RotateCcw size={12} /> {t('macro.resetToDefault')}
            </button>
          ) : <span />}
          <div className="flex items-center gap-2">
            <button className="btn-ghost btn-sm" onClick={onClose}>{t('common.cancel')}</button>
            <button
              className="btn-primary btn-sm"
              onClick={() => saveMut.mutate()}
              disabled={saveMut.isPending}
            >
              <Save size={12} /> {t('common.save')}
            </button>
          </div>
        </div>

        {(saveMut.isError || resetMut.isError) && (
          <div className="text-caption text-bear mt-3 break-all">
            {String((saveMut.error || resetMut.error)?.detail || (saveMut.error || resetMut.error)?.message)}
          </div>
        )}
      </div>
    </div>
  );
}

function NumField({ label, value, onChange }) {
  return (
    <div>
      <label className="h-caption block mb-1">{label}</label>
      <input
        type="number"
        step="0.01"
        className="input tabular"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/* ----------------------------------------------------------- Economic Calendar */

function EconomicCalendarPanel({ t }) {
  const [daysAhead, setDaysAhead] = useState(30);
  const [impact, setImpact] = useState('');
  const calQ = useQuery({
    queryKey: ['macro-calendar', daysAhead, impact],
    queryFn: () => getEconomicCalendar({ daysAhead, impact: impact || null }),
    retry: false,
  });

  const items = calQ.data?.items || [];

  return (
    <div className="space-y-4">
      <div className="card">
        <SectionHeader
          title={t('macro.calendar.title')}
          subtitle={t('macro.calendar.subtitle')}
          meta={
            calQ.data?.as_of && (
              <span className="font-mono text-[10px] tracking-[0.15em] text-text-muted uppercase">
                {fmtRelativeTime(calQ.data.as_of)}
              </span>
            )
          }
        />

        <div className="flex flex-wrap items-end gap-4 mb-4">
          <div>
            <label className="h-caption block mb-1">{t('macro.calendar.daysAhead')}</label>
            <select
              className="select"
              value={daysAhead}
              onChange={(e) => setDaysAhead(Number(e.target.value))}
            >
              <option value={7}>7</option>
              <option value={14}>14</option>
              <option value={30}>30</option>
              <option value={60}>60</option>
              <option value={90}>90</option>
              <option value={180}>180</option>
            </select>
          </div>
          <div>
            <label className="h-caption block mb-1">{t('macro.calendar.impactFilter.label')}</label>
            <select
              className="select"
              value={impact}
              onChange={(e) => setImpact(e.target.value)}
            >
              <option value="">{t('macro.calendar.impactFilter.all')}</option>
              <option value="high">{t('macro.calendar.impactFilter.high')}</option>
              <option value="medium">{t('macro.calendar.impactFilter.medium')}</option>
              <option value="low">{t('macro.calendar.impactFilter.low')}</option>
            </select>
          </div>
        </div>

        {calQ.isLoading ? (
          <LoadingState rows={6} />
        ) : calQ.isError ? (
          <ErrorState error={calQ.error} onRetry={calQ.refetch} />
        ) : items.length === 0 ? (
          <EmptyState title={t('macro.calendar.empty')} />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>{t('macro.calendar.columns.date')}</th>
                <th>{t('macro.calendar.columns.countdown')}</th>
                <th>{t('macro.calendar.columns.event')}</th>
                <th>{t('macro.calendar.columns.category')}</th>
                <th>{t('macro.calendar.columns.impact')}</th>
                <th>{t('macro.calendar.columns.source')}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <CalendarRow key={row.id} row={row} t={t} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function CalendarRow({ row, t }) {
  const dt = new Date(row.date_utc);
  const now = new Date();
  const days = Math.round((dt - now) / 86_400_000);
  let countdown = '';
  if (days <= 0) countdown = t('macro.calendar.countdown.today');
  else if (days === 1) countdown = t('macro.calendar.countdown.tomorrow');
  else countdown = t('macro.calendar.countdown.inDays', { count: days });

  const impactClass =
    row.impact === 'high' ? 'text-bear bg-bear/10 border-bear/40' :
    row.impact === 'medium' ? 'text-warn bg-warn/10 border-warn/40' :
    'text-text-muted bg-elevated border-border-subtle';

  return (
    <tr>
      <td className="font-mono text-text-primary tabular">
        {dt.toISOString().slice(0, 10)}
        <span className="ml-2 text-caption text-text-muted">
          {dt.toISOString().slice(11, 16)} UTC
        </span>
      </td>
      <td className="text-body-sm text-text-secondary">{countdown}</td>
      <td className="font-medium text-text-primary">{row.name}</td>
      <td>
        <span className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
          {t(`macro.calendar.category.${row.category}`, { defaultValue: row.category })}
        </span>
      </td>
      <td>
        <span className={classNames(
          'inline-block px-2 py-0.5 text-[10px] font-mono tracking-[0.15em] uppercase border',
          impactClass,
        )}>
          {t(`macro.calendar.impactBadge.${row.impact}`)}
        </span>
      </td>
      <td className="text-caption text-text-muted">
        {t(`macro.calendar.sourceLabel.${row.source}`, { defaultValue: row.source })}
      </td>
    </tr>
  );
}
