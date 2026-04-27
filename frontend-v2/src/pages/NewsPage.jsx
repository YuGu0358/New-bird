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
import { SectionHeader, LoadingState, ErrorState, EmptyState } from '../components/primitives.jsx';
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
  const chartQ = useQuery({
    queryKey: ['chart', symbol],
    queryFn: () => getChart(symbol, '1m'),
    enabled: !!symbol,
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
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">{t('news.title')}</h1>
          <p className="text-body-sm text-steel-200 mt-1">{t('news.subtitle')}</p>
        </div>
      </div>

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
        <button type="submit" className="btn-primary">查询</button>
      </form>

      {/* Chart */}
      <div className="card">
        <SectionHeader title={`${symbol} 价格趋势`} subtitle="过去 1 个月 close" />
        <ChartView q={chartQ} />
      </div>

      {/* Three-column research */}
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-4 card">
          <SectionHeader title="公司画像" />
          <CompanyView q={companyQ} />
        </div>
        <div className="col-span-4 card">
          <SectionHeader title="新闻摘要" subtitle="Tavily" />
          <NewsView q={newsQ} />
        </div>
        <div className="col-span-4 card">
          <SectionHeader title="研究简报" />
          <ResearchView q={researchQ} />
        </div>
      </div>

      {/* Free Tavily search */}
      <div className="card">
        <SectionHeader title="自由检索 (Tavily)" subtitle="任意关键词 — 例如 'NVDA earnings beat'" />
        <form onSubmit={commitQuery} className="flex gap-3 mb-4">
          <input
            className="input flex-1 max-w-2xl"
            placeholder="搜索内容…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={!query.trim()}>
            搜索
          </button>
        </form>
        <TavilyResults q={tavilyQ} />
      </div>
    </div>
  );
}

function ChartView({ q }) {
  if (q.isLoading) return <LoadingState rows={4} label="Loading chart…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const points = (q.data?.points || q.data?.bars || []).map((p) => ({
    t: p.date || p.timestamp || p.t,
    v: parseFloat(p.close ?? p.price ?? p.v ?? 0),
  }));
  if (points.length === 0) return <EmptyState title="暂无价格数据" />;
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
          <XAxis dataKey="t" stroke="#7C8A9A" fontSize={11} tickLine={false} />
          <YAxis stroke="#7C8A9A" fontSize={11} tickLine={false} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#0F1923', border: '1px solid #3D7FA5', borderRadius: 6, color: '#E8ECF1', fontSize: 12 }}
            formatter={(v) => fmtUsd(v)}
          />
          <Area type="monotone" dataKey="v" stroke="#5BA3C6" strokeWidth={2} fill="url(#chartFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function CompanyView({ q }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data || {};
  if (!d.symbol && !d.company_name) return <EmptyState icon={Building2} title="无公司画像" />;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-body font-semibold text-steel-50">{d.company_name || d.name || d.symbol}</div>
        <div className="text-caption text-steel-200">{d.symbol} · {d.sector || ''} · {d.industry || ''}</div>
      </div>
      <p className="text-body-sm text-steel-100 leading-relaxed">{d.business_summary || d.summary || '—'}</p>
      <div className="text-caption text-steel-300">
        生成时间: {d.generated_at ? fmtRelativeTime(d.generated_at) : '—'}
      </div>
    </div>
  );
}

function NewsView({ q }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data || {};
  if (!d.summary) return <EmptyState icon={Newspaper} title="无新闻摘要" />;
  return (
    <div className="space-y-3">
      <p className="text-body-sm text-steel-100 leading-relaxed">{d.summary}</p>
      <div className="text-caption text-steel-300">
        Source: {d.source || 'Tavily'} · {d.timestamp ? fmtRelativeTime(d.timestamp) : ''}
      </div>
    </div>
  );
}

function ResearchView({ q }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data || {};
  if (!d.report && !d.summary) return <EmptyState icon={FileText} title="无研究简报" />;
  return (
    <div className="space-y-3">
      <p className="text-body-sm text-steel-100 leading-relaxed whitespace-pre-wrap">
        {d.report || d.summary}
      </p>
    </div>
  );
}

function TavilyResults({ q }) {
  if (q.isIdle || (!q.isLoading && !q.data)) {
    return <div className="text-body-sm text-steel-200">输入查询语句后按搜索。</div>;
  }
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const sources = q.data?.sources || q.data?.results || [];
  return (
    <div className="space-y-4">
      {q.data?.answer && (
        <div className="rounded-md bg-ink-900 border border-steel-400 p-4">
          <div className="h-caption mb-2">答案</div>
          <p className="text-body-sm text-steel-100 leading-relaxed">{q.data.answer}</p>
        </div>
      )}
      <div className="space-y-2">
        {sources.length === 0 && <div className="text-caption text-steel-200">无结果</div>}
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
