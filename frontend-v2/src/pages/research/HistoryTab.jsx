// HistoryTab — sixth tab on /research that lists persisted MarketResearchReport
// and EarningsReview rows from `/api/research/history`. Extracted from
// ResearchPage.jsx because the parent file already exceeds the 800-line
// guideline; keeping the tab here scopes the new code without touching the
// existing five tabs.
//
// Renders selected rows by reusing MarketReport / EarningsReport from
// ResearchPage.jsx so the rendering stays consistent with the live tabs.

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  SectionHeader,
} from '../../components/primitives.jsx';
import { classNames } from '../../lib/format.js';
import { getResearchHistory } from '../../lib/api.js';
import { EarningsReport, MarketReport } from '../ResearchPage.jsx';

const KIND_OPTIONS = [
  { value: '', labelKey: 'research.history.filterKindAll' },
  { value: 'market_research', labelKey: 'research.tabs.market' },
  { value: 'earnings_review', labelKey: 'research.tabs.earnings' },
];

const MIN_LIMIT = 1;
const MAX_LIMIT = 100;
const DEFAULT_LIMIT = 20;

export default function HistoryTab({ t }) {
  const [kind, setKind] = useState('');
  const [subject, setSubject] = useState('');
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [selected, setSelected] = useState(null);

  const historyQ = useQuery({
    queryKey: ['research-history', kind, subject, limit],
    queryFn: () =>
      getResearchHistory({
        kind: kind || undefined,
        subject: subject.trim() || undefined,
        limit: clampLimit(limit),
      }),
    retry: false,
    refetchOnWindowFocus: false,
  });

  function onRefresh() {
    historyQ.refetch();
  }

  const items = Array.isArray(historyQ.data?.items) ? historyQ.data.items : [];

  return (
    <div className="space-y-6">
      <FilterRow
        t={t}
        kind={kind}
        subject={subject}
        limit={limit}
        onKindChange={setKind}
        onSubjectChange={setSubject}
        onLimitChange={setLimit}
        onRefresh={onRefresh}
        isPending={historyQ.isFetching}
      />

      {historyQ.isLoading && <LoadingState rows={4} label={t('research.loading')} />}
      {historyQ.isError && <ErrorState error={historyQ.error} onRetry={historyQ.refetch} />}
      {!historyQ.isLoading && !historyQ.isError && items.length === 0 && (
        <EmptyState title={t('research.history.empty')} />
      )}
      {items.length > 0 && (
        <HistoryList items={items} onView={setSelected} t={t} />
      )}

      {selected && (
        <DetailModal item={selected} onClose={() => setSelected(null)} t={t} />
      )}
    </div>
  );
}

function FilterRow({
  t,
  kind,
  subject,
  limit,
  onKindChange,
  onSubjectChange,
  onLimitChange,
  onRefresh,
  isPending,
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
        {t('research.history.filterKind')}
        <select
          className="input"
          value={kind}
          onChange={(e) => onKindChange(e.target.value)}
        >
          {KIND_OPTIONS.map((opt) => (
            <option key={opt.value || 'all'} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
      </label>
      <input
        className="input flex-1 min-w-[220px]"
        placeholder={t('research.history.filterSubject')}
        value={subject}
        onChange={(e) => onSubjectChange(e.target.value)}
        maxLength={120}
      />
      <label className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
        {t('research.history.filterLimit')}
        <input
          type="number"
          min={MIN_LIMIT}
          max={MAX_LIMIT}
          className="input w-20"
          value={limit}
          onChange={(e) => onLimitChange(Number(e.target.value) || DEFAULT_LIMIT)}
        />
      </label>
      <button
        type="button"
        className="btn-primary"
        onClick={onRefresh}
        disabled={isPending}
      >
        {isPending ? t('research.loading') : t('research.history.refresh')}
      </button>
    </div>
  );
}

function HistoryList({ items, onView, t }) {
  return (
    <div className="border border-border-subtle">
      <table className="tbl">
        <thead>
          <tr>
            <th>Created</th>
            <th>Kind</th>
            <th>Subject</th>
            <th>Theme</th>
            <th>{t('research.history.modelId')}</th>
            <th className="tbl-num">Tokens</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td className="font-mono text-[11px] text-text-secondary">
                {formatTimestamp(item.created_at)}
              </td>
              <td>
                <KindBadge kind={item.kind} />
              </td>
              <td className="font-mono text-text-primary">{item.subject || '—'}</td>
              <td className="text-text-secondary">{item.theme || '—'}</td>
              <td className="font-mono text-[11px] text-text-muted">
                {item.model_id || '—'}
              </td>
              <td className="tbl-num font-mono text-[11px] text-text-muted">
                {formatTokens(item, t)}
              </td>
              <td>
                <button
                  type="button"
                  className="px-2 py-1 border border-cyan/40 text-cyan font-mono text-[10px] uppercase tracking-[0.15em] hover:bg-cyan/10"
                  onClick={() => onView(item)}
                >
                  {t('research.history.view')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KindBadge({ kind }) {
  const isMarket = kind === 'market_research';
  const tone = isMarket
    ? 'border-cyan/40 text-cyan'
    : 'border-bull/40 text-bull';
  const label = isMarket ? 'MARKET' : kind === 'earnings_review' ? 'EARNINGS' : kind;
  return (
    <span
      className={classNames(
        'px-2 py-0.5 border font-mono text-[10px] uppercase tracking-[0.15em]',
        tone,
      )}
    >
      {label}
    </span>
  );
}

function DetailModal({ item, onClose, t }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 overflow-y-auto p-6"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-5xl my-8 relative"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <SectionHeader
            title={`${item.subject || '—'}${item.theme ? ` · ${item.theme}` : ''}`}
            subtitle={`${formatTimestamp(item.created_at)} · ${item.model_id || '—'}`}
          />
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1 px-3 py-1 border border-border-subtle text-text-secondary hover:text-text-primary font-mono text-[10px] uppercase tracking-[0.15em]"
            aria-label={t('research.history.viewClose')}
          >
            <X size={12} /> {t('research.history.viewClose')}
          </button>
        </div>
        <DetailBody item={item} t={t} />
      </div>
    </div>
  );
}

function DetailBody({ item, t }) {
  const payload = item?.payload;
  if (!payload || typeof payload !== 'object') {
    return <EmptyState title={t('research.noData')} />;
  }
  if (item.kind === 'market_research') {
    return <MarketReport data={payload} t={t} />;
  }
  if (item.kind === 'earnings_review') {
    return <EarningsReport data={payload} t={t} />;
  }
  // Unknown kind — render the raw JSON so nothing is silently dropped.
  return (
    <pre className="border border-border-subtle p-4 text-[11px] font-mono text-text-secondary whitespace-pre-wrap overflow-x-auto">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

// ---------- helpers ----------

function clampLimit(n) {
  const value = Number(n);
  if (!Number.isFinite(value)) return DEFAULT_LIMIT;
  return Math.max(MIN_LIMIT, Math.min(MAX_LIMIT, Math.round(value)));
}

function formatTimestamp(value) {
  if (!value) return '—';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return value;
  }
}

function formatTokens(item, t) {
  const inT = item.cost_tokens_in;
  const outT = item.cost_tokens_out;
  if (inT == null && outT == null) return '—';
  const parts = [];
  if (inT != null) parts.push(`${inT} ${t('research.history.tokensIn')}`);
  if (outT != null) parts.push(`${outT} ${t('research.history.tokensOut')}`);
  return parts.join(' / ');
}
