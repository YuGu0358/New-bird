import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Search as SearchIcon, ExternalLink, Newspaper, FileText, Building2 } from 'lucide-react';
import { getNews, getResearch, getCompany, tavilySearch, getChart } from '../lib/api.js';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { SectionHeader, PageHeader, LoadingState, ErrorState, EmptyState } from '../components/primitives.jsx';
import { fmtUsd, fmtRelativeTime, fmtAbsTime } from '../lib/format.js';

export default function NewsPage() {
  const { t } = useTranslation();
  const [symbol, setSymbol] = useState('NVDA');
  const [draft, setDraft] = useState('NVDA');
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');

  const newsQ = useQuery({
    queryKey: ['news', symbol],
    queryFn: () => getNews(symbol),
    enabled: !!symbol,
  });
  const researchQ = useQuery({
    queryKey: ['research', symbol],
    queryFn: () => getResearch(symbol),
    enabled: !!symbol,
  });
  const companyQ = useQuery({
    queryKey: ['company', symbol],
    queryFn: () => getCompany(symbol),
    enabled: !!symbol,
  });
  const [chartRange, setChartRange] = useState('1d');
  const chartQ = useQuery({
    queryKey: ['chart', symbol, chartRange],
    queryFn: () => getChart(symbol, chartRange),
    enabled: !!symbol,
    // 1m / 5m bars stale fast — auto-refresh on intraday ranges.
    refetchInterval: chartRange === '1d' ? 60_000 : chartRange === '5d' ? 120_000 : false,
  });
  const tavilyQ = useQuery({
    queryKey: ['tavily', submittedQuery],
    queryFn: () => tavilySearch(submittedQuery),
    enabled: submittedQuery.length > 0,
  });

  function commitSymbol(e) {
    e.preventDefault();
    if (draft.trim()) setSymbol(draft.trim().toUpperCase());
  }

  function commitQuery(e) {
    e.preventDefault();
    if (query.trim()) setSubmittedQuery(query.trim());
  }

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={4}
        title={t('news.title')}
        segments={[{ label: t('news.subtitle') }]}
      />

      {/* Symbol switcher */}
      <form onSubmit={commitSymbol} className="card flex items-end gap-3">
        <div className="flex-1 max-w-sm">
          <label className="h-caption block mb-2">Symbol</label>
          <div className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-steel-200" />
            <input
              className="input pl-9 uppercase"
              value={draft}
              onChange={(e) => setDraft(e.target.value.toUpperCase())}
              placeholder="NVDA / SPY / TSLA …"
            />
          </div>
        </div>
        <button type="submit" className="btn-primary">{t('news.querySymbol')}</button>
      </form>

      {/* Chart */}
      <div className="card">
        <SectionHeader
          title={t('news.priceTrend', { symbol })}
          subtitle={`${chartRange} · ${chartQ.data?.interval ?? '...'}`}
          meta={<RangePicker value={chartRange} onChange={setChartRange} />}
        />
        <ChartView q={chartQ} range={chartRange} t={t} />
      </div>

      {/* Three-column research */}
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-4 card">
          <SectionHeader title={t('news.companyProfile')} />
          <CompanyView q={companyQ} t={t} />
        </div>
        <div className="col-span-4 card">
          <SectionHeader title={t('news.newsSummary')} subtitle="Tavily" />
          <NewsView q={newsQ} t={t} />
        </div>
        <div className="col-span-4 card">
          <SectionHeader title={t('news.researchBrief')} />
          <ResearchView q={researchQ} t={t} />
        </div>
      </div>

      {/* Free Tavily search */}
      <div className="card">
        <SectionHeader title={t('news.freeSearch')} subtitle={t('news.freeSearchSubtitle')} />
        <form onSubmit={commitQuery} className="flex gap-3 mb-4">
          <input
            className="input flex-1 max-w-2xl"
            placeholder={t('news.searchContent')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={!query.trim()}>
            {t('common.search')}
          </button>
        </form>
        <TavilyResults q={tavilyQ} t={t} />
      </div>
    </div>
  );
}

const RANGES = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y'];

function RangePicker({ value, onChange }) {
  return (
    <div className="inline-flex gap-1 font-mono text-[10px] tracking-[0.15em] uppercase">
      {RANGES.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onChange(r)}
          className={
            'px-2 py-1 border ' +
            (r === value
              ? 'border-cyan text-cyan bg-cyan/10'
              : 'border-border-subtle text-text-secondary hover:text-text-primary')
          }
        >
          {r}
        </button>
      ))}
    </div>
  );
}

/** Format a tick label appropriately for the selected range. */
function tickFormatter(range, raw) {
  if (!raw) return '';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(raw);
  if (range === '1d') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (range === '5d') {
    return d.toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function ChartView({ q, range, t }) {
  if (q.isLoading) return <LoadingState rows={4} label={t('news.loadingChart')} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const points = (q.data?.points || q.data?.bars || []).map((p) => ({
    t: p.date || p.timestamp || p.t,
    v: parseFloat(p.close ?? p.price ?? p.v ?? 0),
  }));
  if (points.length === 0) return <EmptyState title={t('news.noPriceData')} />;
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points}>
          <defs>
            <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5BA3C6" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#5BA3C6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
          <XAxis
            dataKey="t"
            stroke="#7C8A9A"
            fontSize={11}
            tickLine={false}
            tickFormatter={(v) => tickFormatter(range, v)}
            minTickGap={40}
          />
          <YAxis stroke="#7C8A9A" fontSize={11} tickLine={false} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#0F1923', border: '1px solid #3D7FA5', borderRadius: 6, color: '#E8ECF1', fontSize: 12 }}
            formatter={(v) => fmtUsd(v)}
            labelFormatter={(v) => tickFormatter(range, v)}
          />
          <Area
            type="monotone"
            dataKey="v"
            stroke="#5BA3C6"
            strokeWidth={range === '1d' ? 1.5 : 2}
            fill="url(#chartFill)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function CompanyView({ q, t }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data || {};
  if (!d.symbol && !d.company_name) return <EmptyState icon={Building2} title={t('news.noProfile')} />;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-body font-semibold text-text-primary">{d.company_name || d.name || d.symbol}</div>
        <div className="text-caption text-text-secondary">{d.symbol} · {d.sector || ''} · {d.industry || ''}</div>
      </div>
      <p className="text-body-sm text-text-primary leading-relaxed">{d.business_summary || d.summary || '—'}</p>
      <div className="text-caption text-text-muted">
        {t('news.generatedAt')}: {d.generated_at ? fmtRelativeTime(d.generated_at) : '—'}
      </div>
    </div>
  );
}

function NewsView({ q, t }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data || {};
  if (!d.summary) return <EmptyState icon={Newspaper} title={t('news.noNews')} />;
  return (
    <div className="space-y-3">
      <p className="text-body-sm text-text-primary leading-relaxed">{d.summary}</p>
      <div className="text-caption text-text-muted">
        {t('news.source')}: {d.source || 'Tavily'} · {d.timestamp ? fmtRelativeTime(d.timestamp) : ''}
      </div>
    </div>
  );
}

function ResearchView({ q, t }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data || {};
  if (!d.report && !d.summary) return <EmptyState icon={FileText} title={t('news.noResearch')} />;
  return (
    <div className="space-y-3">
      <p className="text-body-sm text-text-primary leading-relaxed whitespace-pre-wrap">
        {d.report || d.summary}
      </p>
    </div>
  );
}

function TavilyResults({ q, t }) {
  if (q.isIdle || (!q.isLoading && !q.data)) {
    return <div className="text-body-sm text-text-secondary">{t('news.searchContent')}</div>;
  }
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const sources = q.data?.sources || q.data?.results || [];
  return (
    <div className="space-y-4">
      {q.data?.answer && (
        <div className="bg-surface border border-border-subtle p-4">
          <div className="h-caption mb-2">{t('news.answer')}</div>
          <p className="text-body-sm text-text-primary leading-relaxed">{q.data.answer}</p>
        </div>
      )}
      <div className="space-y-2">
        {sources.length === 0 && <div className="text-caption text-text-secondary">{t('common.noData')}</div>}
        {sources.map((s, i) => (
          <a
            key={i}
            href={s.url || s.link}
            target="_blank"
            rel="noreferrer"
            className="block card-dense hover:border-steel-600 transition duration-150"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-body font-medium text-steel-50 truncate">{s.title || s.name || s.url}</span>
              <ExternalLink size={12} className="text-steel-200 ml-2 shrink-0" />
            </div>
            <div className="text-caption text-steel-200 truncate">{s.url || s.link}</div>
            {s.content && <div className="text-body-sm text-steel-100 mt-2 line-clamp-3">{s.content}</div>}
          </a>
        ))}
      </div>
    </div>
  );
}
