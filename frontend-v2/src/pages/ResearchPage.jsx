// ResearchPage — tabbed surface for the financial-services integration.
//
// Five tabs (Market / Earnings / Comps / DCF / Filings) each call into one of
// the new /api/research/* endpoints (see backend/app/routers/research.py).
// Styling matches the rest of the Tokyo cyberpunk console — uses the shared
// primitives (PageHeader / SectionHeader / LoadingState / ErrorState /
// EmptyState) and Tailwind utility classes already defined in index.css.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionHeader,
} from '../components/primitives.jsx';
import { classNames } from '../lib/format.js';
import {
  getComps,
  getDcf,
  getEarningsReview,
  getMarketResearch,
  getSecEdgarFilings,
} from '../lib/api.js';

const TABS = ['market', 'earnings', 'comps', 'dcf', 'filings'];
const ALL_FORM_TYPES = ['10-K', '10-Q', '8-K', 'S-1'];
const DEFAULT_FORM_TYPES = ['10-K', '10-Q', '8-K'];
const MIN_PEER_COUNT = 1;
const MAX_PEER_COUNT = 20;
const DEFAULT_PEER_COUNT = 10;
const DEFAULT_FILINGS_LIMIT = 20;

export default function ResearchPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState('market');

  return (
    <div className="space-y-6">
      <PageHeader
        moduleId={21}
        title={t('research.title')}
        segments={[
          { label: t('research.subtitle') },
          { label: 'RESEARCH', accent: true },
        ]}
        live={false}
      />
      <TabBar value={tab} onChange={setTab} t={t} />
      <div className="card">
        {tab === 'market' && <MarketTab t={t} />}
        {tab === 'earnings' && <EarningsTab t={t} />}
        {tab === 'comps' && <CompsTab t={t} />}
        {tab === 'dcf' && <DcfTab t={t} />}
        {tab === 'filings' && <FilingsTab t={t} />}
      </div>
    </div>
  );
}

function TabBar({ value, onChange, t }) {
  return (
    <div className="flex gap-1 border-b border-border-subtle font-mono text-[11px] tracking-[0.15em] uppercase">
      {TABS.map((name) => (
        <button
          key={name}
          type="button"
          onClick={() => onChange(name)}
          className={classNames(
            'px-4 py-2 border-b-2 -mb-[1px] transition-colors',
            name === value
              ? 'border-cyan text-cyan'
              : 'border-transparent text-text-secondary hover:text-text-primary',
          )}
        >
          {t(`research.tabs.${name}`)}
        </button>
      ))}
    </div>
  );
}

// ---------- Market tab ----------

function MarketTab({ t }) {
  const [sector, setSector] = useState('');
  const [theme, setTheme] = useState('');
  const [peerCount, setPeerCount] = useState(DEFAULT_PEER_COUNT);

  const mutation = useMutation({
    mutationFn: (body) => getMarketResearch(body),
  });

  function buildBody() {
    return {
      sector: sector.trim(),
      theme: theme.trim() || null,
      peer_count: clampPeerCount(peerCount),
    };
  }

  function submit(e) {
    e.preventDefault();
    if (!sector.trim()) return;
    mutation.mutate(buildBody());
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <input
          className="input flex-1 min-w-[220px]"
          placeholder={t('research.market.sectorPlaceholder')}
          value={sector}
          onChange={(e) => setSector(e.target.value)}
          maxLength={120}
          required
        />
        <input
          className="input flex-1 min-w-[220px]"
          placeholder={t('research.market.themePlaceholder')}
          value={theme}
          onChange={(e) => setTheme(e.target.value)}
          maxLength={120}
        />
        <label className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
          {t('research.market.peerCountLabel')}
          <input
            type="number"
            min={MIN_PEER_COUNT}
            max={MAX_PEER_COUNT}
            className="input w-20"
            value={peerCount}
            onChange={(e) => setPeerCount(Number(e.target.value) || DEFAULT_PEER_COUNT)}
          />
        </label>
        <button
          type="submit"
          className="btn-primary"
          disabled={mutation.isPending || !sector.trim()}
        >
          {mutation.isPending ? t('research.loading') : t('research.market.submit')}
        </button>
      </form>

      {mutation.isPending && <LoadingState rows={4} label={t('research.loading')} />}
      {mutation.isError && (
        <ErrorState
          error={mutation.error}
          onRetry={() => mutation.mutate(buildBody())}
        />
      )}
      {!mutation.isPending && !mutation.isError && !mutation.data && (
        <EmptyState title={t('research.noData')} />
      )}
      {mutation.data && <MarketReport data={mutation.data} t={t} />}
    </div>
  );
}

function MarketReport({ data, t }) {
  return (
    <div className="space-y-6">
      <ProseBlock
        title={t('research.market.industryOverview')}
        body={data.industry_overview}
      />
      <BulletList title={t('research.market.keyDrivers')} items={data.key_drivers} />
      <ProseBlock
        title={t('research.market.competitiveLandscape')}
        body={data.competitive_landscape}
      />
      <PeerCompsBlock
        title={t('research.market.peerComps')}
        comps={data.peer_comps}
        t={t}
      />
      <IdeasShortlist title={t('research.market.ideasShortlist')} items={data.ideas_shortlist} />
      <BulletList title={t('research.market.keyRisks')} items={data.key_risks} />
      <ProseBlock title={t('research.market.sectorThesis')} body={data.sector_thesis} accent />
    </div>
  );
}

// ---------- Earnings tab ----------

function EarningsTab({ t }) {
  const [symbol, setSymbol] = useState('');

  const mutation = useMutation({
    mutationFn: (sym) => getEarningsReview(sym),
  });

  function submit(e) {
    e.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    mutation.mutate(trimmed);
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
        <input
          className="input uppercase font-mono w-40"
          placeholder={t('research.earnings.symbolPlaceholder')}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          maxLength={16}
          required
        />
        <button
          type="submit"
          className="btn-primary"
          disabled={mutation.isPending || !symbol.trim()}
        >
          {mutation.isPending ? t('research.loading') : t('research.earnings.submit')}
        </button>
      </form>

      {mutation.isPending && <LoadingState rows={4} label={t('research.loading')} />}
      {mutation.isError && (
        <ErrorState
          error={mutation.error}
          onRetry={() => mutation.mutate(symbol.trim().toUpperCase())}
        />
      )}
      {!mutation.isPending && !mutation.isError && !mutation.data && (
        <EmptyState title={t('research.noData')} />
      )}
      {mutation.data && <EarningsReport data={mutation.data} t={t} />}
    </div>
  );
}

function EarningsReport({ data, t }) {
  return (
    <div className="space-y-6">
      <SectionHeader
        title={data.symbol}
        subtitle={`${t('research.earnings.period')}: ${data.period || '—'}`}
      />
      <VarianceTable title={t('research.earnings.variance')} rows={data.variance_table} />
      <GuidanceTable title={t('research.earnings.guidance')} rows={data.guidance_changes} />
      <FilingHighlights title={t('research.earnings.filings')} items={data.filing_highlights} />
      <ProseBlock title={t('research.earnings.note')} body={data.note_draft} accent />
      <BulletList title={t('research.earnings.takeaways')} items={data.key_takeaways} />
      <BulletList title={t('research.earnings.followUps')} items={data.follow_ups} />
    </div>
  );
}

// ---------- Comps tab ----------

function CompsTab({ t }) {
  const [symbol, setSymbol] = useState('');
  const [submittedSymbol, setSubmittedSymbol] = useState('');
  const [n, setN] = useState(DEFAULT_PEER_COUNT);
  const [submittedN, setSubmittedN] = useState(DEFAULT_PEER_COUNT);

  const compsQ = useQuery({
    queryKey: ['research-comps', submittedSymbol, submittedN],
    queryFn: () => getComps(submittedSymbol, submittedN),
    enabled: !!submittedSymbol,
    retry: false,
  });

  function submit(e) {
    e.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    setSubmittedSymbol(trimmed);
    setSubmittedN(clampPeerCount(n));
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
        <input
          className="input uppercase font-mono w-40"
          placeholder={t('research.earnings.symbolPlaceholder')}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          maxLength={16}
          required
        />
        <label className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
          {t('research.market.peerCountLabel')}
          <input
            type="number"
            min={MIN_PEER_COUNT}
            max={MAX_PEER_COUNT}
            className="input w-20"
            value={n}
            onChange={(e) => setN(Number(e.target.value) || DEFAULT_PEER_COUNT)}
          />
        </label>
        <button type="submit" className="btn-primary" disabled={!symbol.trim()}>
          {t('research.comps.submit')}
        </button>
      </form>

      {!submittedSymbol && <EmptyState title={t('research.noData')} />}
      {submittedSymbol && compsQ.isLoading && (
        <LoadingState rows={4} label={t('research.loading')} />
      )}
      {submittedSymbol && compsQ.isError && (
        <ErrorState error={compsQ.error} onRetry={compsQ.refetch} />
      )}
      {compsQ.data && (
        <PeerCompsBlock
          title={`${compsQ.data.symbol || submittedSymbol} · ${t('research.market.peerComps')}`}
          comps={compsQ.data}
          t={t}
        />
      )}
    </div>
  );
}

// ---------- DCF tab ----------

function DcfTab({ t }) {
  const [symbol, setSymbol] = useState('');
  const [submittedSymbol, setSubmittedSymbol] = useState('');

  const dcfQ = useQuery({
    queryKey: ['research-dcf', submittedSymbol],
    queryFn: () => getDcf(submittedSymbol),
    enabled: !!submittedSymbol,
    retry: false,
  });

  function submit(e) {
    e.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    setSubmittedSymbol(trimmed);
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
        <input
          className="input uppercase font-mono w-40"
          placeholder={t('research.earnings.symbolPlaceholder')}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          maxLength={16}
          required
        />
        <button type="submit" className="btn-primary" disabled={!symbol.trim()}>
          {t('research.dcf.submit')}
        </button>
      </form>

      {!submittedSymbol && <EmptyState title={t('research.noData')} />}
      {submittedSymbol && dcfQ.isLoading && (
        <LoadingState rows={3} label={t('research.loading')} />
      )}
      {submittedSymbol && dcfQ.isError && (
        <ErrorState error={dcfQ.error} onRetry={dcfQ.refetch} />
      )}
      {dcfQ.data && <DcfTable data={dcfQ.data} />}
    </div>
  );
}

function DcfTable({ data }) {
  // The DCF response shape is variable — render every scalar field at top
  // level, recursing one level into nested objects to keep the table flat.
  const rows = flattenScalars(data);
  if (!rows.length) return <EmptyState title="No DCF fields" />;
  return (
    <div className="border border-border-subtle">
      <table className="tbl">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="font-mono text-text-secondary">{k}</td>
              <td className="font-mono text-text-primary">{formatScalar(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- Filings tab ----------

function FilingsTab({ t }) {
  const [symbol, setSymbol] = useState('');
  const [limit, setLimit] = useState(DEFAULT_FILINGS_LIMIT);
  const [formTypes, setFormTypes] = useState(DEFAULT_FORM_TYPES);
  const [submitted, setSubmitted] = useState(null);

  const filingsQ = useQuery({
    queryKey: ['research-filings', submitted?.symbol, submitted?.limit, submitted?.formTypes],
    queryFn: () =>
      getSecEdgarFilings(submitted.symbol, {
        limit: submitted.limit,
        formTypes: submitted.formTypes,
      }),
    enabled: !!submitted?.symbol,
    retry: false,
  });

  function toggleFormType(name) {
    setFormTypes((prev) =>
      prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name],
    );
  }

  function submit(e) {
    e.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    setSubmitted({
      symbol: trimmed,
      limit: clampLimit(limit),
      formTypes: (formTypes.length > 0 ? formTypes : DEFAULT_FORM_TYPES).join(','),
    });
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
        <input
          className="input uppercase font-mono w-40"
          placeholder={t('research.earnings.symbolPlaceholder')}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          maxLength={16}
          required
        />
        <label className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
          {t('research.filings.limitLabel')}
          <input
            type="number"
            min={1}
            max={100}
            className="input w-20"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value) || DEFAULT_FILINGS_LIMIT)}
          />
        </label>
        <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
          {t('research.filings.formTypesLabel')}:
          <div className="inline-flex gap-1">
            {ALL_FORM_TYPES.map((name) => (
              <button
                key={name}
                type="button"
                aria-pressed={formTypes.includes(name)}
                onClick={() => toggleFormType(name)}
                className={classNames(
                  'px-2 py-1 border',
                  formTypes.includes(name)
                    ? 'border-cyan text-cyan bg-cyan/10'
                    : 'border-border-subtle text-text-secondary hover:text-text-primary',
                )}
              >
                {name}
              </button>
            ))}
          </div>
        </div>
        <button type="submit" className="btn-primary" disabled={!symbol.trim()}>
          {t('research.filings.submit')}
        </button>
      </form>

      {!submitted && <EmptyState title={t('research.noData')} />}
      {submitted && filingsQ.isLoading && (
        <LoadingState rows={4} label={t('research.loading')} />
      )}
      {submitted && filingsQ.isError && (
        <ErrorState error={filingsQ.error} onRetry={filingsQ.refetch} />
      )}
      {filingsQ.data && <FilingsTable data={filingsQ.data} t={t} />}
    </div>
  );
}

function FilingsTable({ data, t }) {
  const rows = Array.isArray(data?.filings) ? data.filings : [];
  if (!rows.length) {
    return (
      <EmptyState
        title={t('research.filings.configureUserAgent')}
        hint={data?.cik ? `CIK ${data.cik}` : undefined}
      />
    );
  }
  return (
    <div className="space-y-3">
      <SectionHeader
        title={`${data.symbol || ''} · ${rows.length} filings`}
        subtitle={data.source || 'SEC EDGAR'}
      />
      <div className="border border-border-subtle">
        <table className="tbl">
          <thead>
            <tr>
              <th>Form</th>
              <th>Filing date</th>
              <th>Report date</th>
              <th>Accession</th>
              <th>Document</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.accession_number}>
                <td className="font-mono text-text-primary">{f.form_type}</td>
                <td className="font-mono text-text-secondary">{f.filing_date || '—'}</td>
                <td className="font-mono text-text-secondary">{f.report_date || '—'}</td>
                <td className="font-mono text-text-muted text-[11px]">{f.accession_number}</td>
                <td>
                  {f.primary_doc_url ? (
                    <a
                      href={f.primary_doc_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-cyan hover:text-cyan-light font-mono text-[11px]"
                    >
                      {f.primary_document || 'open'} <ExternalLink size={11} />
                    </a>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Shared rendering primitives ----------

function ProseBlock({ title, body, accent = false }) {
  if (!body) return null;
  return (
    <div className="space-y-2">
      <div
        className={classNames(
          'font-mono text-[10px] tracking-[0.15em] uppercase',
          accent ? 'text-cyan' : 'text-text-muted',
        )}
      >
        {title}
      </div>
      <div
        className={classNames(
          'border p-4 text-body-sm leading-relaxed whitespace-pre-wrap',
          accent
            ? 'border-cyan/40 bg-cyan/5 text-text-primary'
            : 'border-border-subtle text-text-secondary',
        )}
      >
        {body}
      </div>
    </div>
  );
}

function BulletList({ title, items }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
      <ul className="list-disc list-inside space-y-1 text-body-sm text-text-secondary border border-border-subtle p-4">
        {items.map((item, i) => (
          <li key={i}>{String(item)}</li>
        ))}
      </ul>
    </div>
  );
}

function PeerCompsBlock({ title, comps, t }) {
  const peers = Array.isArray(comps?.peers) ? comps.peers : [];
  if (peers.length === 0) {
    return (
      <div className="space-y-2">
        <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
        <EmptyState title="No peers" />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
      <div className="border border-border-subtle">
        <table className="tbl">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th className="tbl-num">Mkt cap</th>
              <th className="tbl-num">P/E</th>
              <th className="tbl-num">EV/EBITDA</th>
              <th className="tbl-num">P/S</th>
              <th className="tbl-num">Growth YoY</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {peers.map((p) => (
              <tr key={p.symbol}>
                <td className="font-mono text-text-primary">{p.symbol}</td>
                <td className="text-text-secondary">{p.name || '—'}</td>
                <td className="tbl-num font-mono">{formatNumber(p.market_cap, { compact: true })}</td>
                <td className="tbl-num font-mono">{formatNumber(p.pe_ratio, { digits: 2 })}</td>
                <td className="tbl-num font-mono">{formatNumber(p.ev_ebitda, { digits: 2 })}</td>
                <td className="tbl-num font-mono">{formatNumber(p.ps_ratio, { digits: 2 })}</td>
                <td className="tbl-num font-mono">{formatPct(p.revenue_growth_yoy)}</td>
                <td className="text-text-secondary text-[12px]">{p.notes || ''}</td>
              </tr>
            ))}
            <tr className="border-t-2 border-cyan/30">
              <td className="font-mono text-cyan uppercase tracking-[0.1em]">{t('research.comps.median')}</td>
              <td />
              <td />
              <td className="tbl-num font-mono text-cyan">{formatNumber(comps.median_pe, { digits: 2 })}</td>
              <td className="tbl-num font-mono text-cyan">{formatNumber(comps.median_ev_ebitda, { digits: 2 })}</td>
              <td />
              <td />
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      {comps.commentary && (
        <p className="text-body-sm text-text-secondary leading-relaxed">{comps.commentary}</p>
      )}
    </div>
  );
}

function IdeasShortlist({ title, items }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((idea, i) => (
          <div key={i} className="border border-border-subtle p-3 space-y-2">
            <div className="text-h3 font-mono text-cyan">{idea.symbol || '—'}</div>
            <KvLine label="Thesis" value={idea.thesis} />
            <KvLine label="Catalyst" value={idea.catalyst} />
            <KvLine label="Risk" value={idea.risk} />
          </div>
        ))}
      </div>
    </div>
  );
}

function KvLine({ label, value }) {
  if (!value) return null;
  return (
    <div className="text-body-sm">
      <span className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{label}: </span>
      <span className="text-text-secondary">{value}</span>
    </div>
  );
}

function VarianceTable({ title, rows }) {
  if (!Array.isArray(rows) || rows.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
      <div className="border border-border-subtle">
        <table className="tbl">
          <thead>
            <tr>
              <th>Metric</th>
              <th className="tbl-num">Actual</th>
              <th className="tbl-num">Consensus</th>
              <th className="tbl-num">Prior</th>
              <th className="tbl-num">Surprise %</th>
              <th>Commentary</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="font-mono text-text-primary">{r.metric}</td>
                <td className="tbl-num font-mono">{formatScalar(r.actual)}</td>
                <td className="tbl-num font-mono">{formatScalar(r.consensus)}</td>
                <td className="tbl-num font-mono">{formatScalar(r.prior)}</td>
                <td className={classNames('tbl-num font-mono', numericTone(r.surprise_pct))}>
                  {formatPct(r.surprise_pct)}
                </td>
                <td className="text-body-sm text-text-secondary">{r.commentary || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GuidanceTable({ title, rows }) {
  if (!Array.isArray(rows) || rows.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
      <div className="border border-border-subtle">
        <table className="tbl">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Prior guidance</th>
              <th>New guidance</th>
              <th>Direction</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="font-mono text-text-primary">{r.metric}</td>
                <td className="font-mono text-text-secondary">{formatScalar(r.prior_guidance)}</td>
                <td className="font-mono text-text-primary">{formatScalar(r.new_guidance)}</td>
                <td>
                  <DirectionBadge value={r.direction} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DirectionBadge({ value }) {
  const direction = (value || '').toLowerCase();
  const tone =
    {
      raised: 'border-bull/40 text-bull',
      lowered: 'border-bear/40 text-bear',
      maintained: 'border-border-subtle text-text-secondary',
      introduced: 'border-cyan/40 text-cyan',
    }[direction] || 'border-border-subtle text-text-secondary';
  return (
    <span
      className={classNames(
        'px-2 py-0.5 border font-mono text-[10px] uppercase tracking-[0.15em]',
        tone,
      )}
    >
      {value || '—'}
    </span>
  );
}

function FilingHighlights({ title, items }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{title}</div>
      <div className="space-y-2">
        {items.map((h, i) => (
          <details key={i} className="border border-border-subtle p-3">
            <summary className="cursor-pointer flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-cyan">
                  {h.form_type || '—'}
                </span>
                <span className="font-mono text-[11px] text-text-muted">
                  {h.accession_number || ''}
                </span>
                {h.relevance && (
                  <span className="font-mono text-[10px] text-text-secondary uppercase tracking-[0.15em]">
                    relevance: {h.relevance}
                  </span>
                )}
              </div>
              {h.accession_number && (
                <a
                  href={edgarUrlForAccession(h.accession_number)}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 text-cyan hover:text-cyan-light font-mono text-[11px]"
                >
                  EDGAR <ExternalLink size={11} />
                </a>
              )}
            </summary>
            {h.excerpt && (
              <p className="mt-3 text-body-sm text-text-secondary leading-relaxed whitespace-pre-wrap">
                {h.excerpt}
              </p>
            )}
          </details>
        ))}
      </div>
    </div>
  );
}

// ---------- Helpers ----------

function clampPeerCount(n) {
  const value = Number(n);
  if (!Number.isFinite(value)) return DEFAULT_PEER_COUNT;
  return Math.max(MIN_PEER_COUNT, Math.min(MAX_PEER_COUNT, Math.round(value)));
}

function clampLimit(n) {
  const value = Number(n);
  if (!Number.isFinite(value)) return DEFAULT_FILINGS_LIMIT;
  return Math.max(1, Math.min(100, Math.round(value)));
}

function formatNumber(value, { digits = 0, compact = false } = {}) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
  const num = Number(value);
  if (compact) {
    const abs = Math.abs(num);
    if (abs >= 1e12) return `${(num / 1e12).toFixed(2)}T`;
    if (abs >= 1e9) return `${(num / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${(num / 1e6).toFixed(2)}M`;
    if (abs >= 1e3) return `${(num / 1e3).toFixed(2)}K`;
  }
  return num.toFixed(digits);
}

function formatPct(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const num = Number(value);
  // The backend may send percentages as either fractions (0.12) or already-
  // scaled percent (12). Heuristic: |v| <= 1.5 → fraction, else already %.
  const asPct = Math.abs(num) <= 1.5 ? num * 100 : num;
  return `${asPct >= 0 ? '+' : ''}${asPct.toFixed(2)}%`;
}

function formatScalar(value) {
  if (value == null) return '—';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—';
    if (Number.isInteger(value)) return value.toString();
    return value.toFixed(4);
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function numericTone(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 'text-text-secondary';
  if (num > 0) return 'text-bull';
  if (num < 0) return 'text-bear';
  return 'text-text-secondary';
}

function flattenScalars(obj, prefix = '') {
  if (!obj || typeof obj !== 'object') return [];
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v == null || typeof v !== 'object') {
      out.push([key, v]);
    } else if (Array.isArray(v)) {
      out.push([key, JSON.stringify(v)]);
    } else {
      // Recurse one level — keeps the table flat for nested {fair_value: {...}}.
      out.push(...flattenScalars(v, key));
    }
  }
  return out;
}

function edgarUrlForAccession(accession) {
  // We don't have CIK here, so use the search URL. Backend's primary_doc_url
  // is the preferred deep-link; this is a fallback only.
  const stripped = (accession || '').replace(/-/g, '');
  return `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum=&type=&dateb=&owner=include&count=40&search_text=${encodeURIComponent(stripped)}`;
}
