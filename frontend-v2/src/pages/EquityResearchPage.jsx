// EquityResearchPage — full-page deep research view at /research/:symbol.
// Inspired by FinceptTerminal's screens/equity_research/, adapted to
// NewBird's Tokyo cyberpunk aesthetic. Tabbed: Overview / Financials /
// Technicals / News / Sentiment / Options. All endpoints reused from the
// existing API; no backend changes.
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Building2,
  ExternalLink,
  Layers,
  Newspaper,
  TrendingDown,
  TrendingUp,
  Users,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  getChart,
  getCompany,
  getIndicator,
  getNews,
  getOptionsChainGex,
  getResearch,
  getSymbolContext,
  searchSocial,
} from '../lib/api.js';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionHeader,
} from '../components/primitives.jsx';
import {
  OptionsCard,
  RegimeCard,
  TechnicalsCard,
  VolumeCard,
  fmtBigInt,
  fmtNum,
  fmtPctLocal,
} from '../components/symbolContextCards.jsx';
import { classNames, fmtRelativeTime, fmtUsd } from '../lib/format.js';

const RANGES = ['1d', '5d', '1mo', '3mo', '6mo', '1y'];
const DEFAULT_RANGE = '3mo';
const TABS = ['overview', 'financials', 'technicals', 'news', 'sentiment', 'options'];
const INDICATOR_RANGE = '3mo';
const TOP_GEX_STRIKES = 5;

const tooltipStyle = {
  background: '#0F1923',
  border: '1px solid #3D7FA5',
  borderRadius: 6,
  color: '#E8ECF1',
  fontSize: 12,
};

/**
 * @returns {JSX.Element}
 */
export default function EquityResearchPage() {
  const params = useParams();
  const symbol = (params.symbol || '').toUpperCase();
  const [tab, setTab] = useState('overview');
  const [range, setRange] = useState(DEFAULT_RANGE);

  const ctxQ = useQuery({
    queryKey: ['symbol-context', symbol],
    queryFn: () => getSymbolContext(symbol),
    enabled: !!symbol,
    staleTime: 30_000,
    retry: false,
  });

  if (!symbol) {
    return <EmptyState title="No symbol" hint="Provide a /research/:symbol path." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        moduleId={20}
        title={`Research · ${symbol}`}
        segments={[{ label: 'EQUITY', accent: true }, { label: 'DEEP-DIVE' }]}
      />
      <Header symbol={symbol} ctxQ={ctxQ} />
      <TabBar value={tab} onChange={setTab} />
      <div className="card">
        {tab === 'overview' && (
          <OverviewTab symbol={symbol} ctx={ctxQ.data} range={range} onRange={setRange} />
        )}
        {tab === 'financials' && <FinancialsTab symbol={symbol} />}
        {tab === 'technicals' && <TechnicalsTab symbol={symbol} />}
        {tab === 'news' && <NewsTab symbol={symbol} />}
        {tab === 'sentiment' && <SentimentTab symbol={symbol} ctx={ctxQ.data} />}
        {tab === 'options' && <OptionsTab symbol={symbol} ctx={ctxQ.data} />}
      </div>
      <SourcesFooter />
    </div>
  );
}

/**
 * @param {{ symbol: string, ctxQ: any }} props
 */
function Header({ symbol, ctxQ }) {
  if (ctxQ.isLoading) return <LoadingState rows={2} label={`Loading ${symbol}…`} />;
  if (ctxQ.isError) return <ErrorState error={ctxQ.error} onRetry={ctxQ.refetch} />;
  const ctx = ctxQ.data;
  const price = ctx?.price || {};
  const change = price.change_pct ?? 0;
  const tone = change > 0 ? 'text-bull' : change < 0 ? 'text-bear' : 'text-text-secondary';
  const Arrow = change >= 0 ? TrendingUp : TrendingDown;
  return (
    <div className="card sticky top-0 z-10 backdrop-blur">
      <div className="flex items-baseline gap-3 flex-wrap">
        <div className="text-h2 font-semibold text-text-primary">{symbol}</div>
        <div className="text-body font-mono">{fmtUsd(price.last)}</div>
        <div className={classNames('inline-flex items-center gap-1 text-body-sm font-medium', tone)}>
          <Arrow size={14} /> {fmtPctLocal(change)} 1d
        </div>
        <Badge label="1w" value={price.week_change_pct} />
        <Badge label="1m" value={price.month_change_pct} />
        <Badge label="1y" value={price.year_change_pct} />
      </div>
    </div>
  );
}

/** @param {{ label: string, value: number | null | undefined }} props */
function Badge({ label, value }) {
  const tone =
    value == null
      ? 'text-text-muted'
      : value > 0
        ? 'text-bull'
        : value < 0
          ? 'text-bear'
          : 'text-text-secondary';
  return (
    <span
      className={classNames(
        'px-2 py-0.5 border border-border-subtle text-[11px] font-mono uppercase tracking-[0.1em]',
        tone,
      )}
    >
      {label} {fmtPctLocal(value)}
    </span>
  );
}

/** @param {{ value: string, onChange: (v: string) => void }} props */
function TabBar({ value, onChange }) {
  return (
    <div className="flex gap-1 border-b border-border-subtle font-mono text-[11px] tracking-[0.15em] uppercase">
      {TABS.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onChange(t)}
          className={classNames(
            'px-4 py-2 border-b-2 -mb-[1px] transition-colors',
            t === value
              ? 'border-cyan text-cyan'
              : 'border-transparent text-text-secondary hover:text-text-primary',
          )}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

/** @param {{ symbol: string, ctx: any, range: string, onRange: (r: string) => void }} props */
function OverviewTab({ symbol, ctx, range, onRange }) {
  const chartQ = useQuery({
    queryKey: ['research-chart', symbol, range],
    queryFn: () => getChart(symbol, range),
    enabled: !!symbol,
    retry: false,
  });
  return (
    <div className="space-y-4">
      <SectionHeader title="Price" subtitle="historical close" />
      <RangeBar value={range} onChange={onRange} />
      <BigChart q={chartQ} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TechnicalsCard tech={ctx?.technicals} />
        <VolumeCard volume={ctx?.volume_profile} />
        <OptionsCard options={ctx?.options_flow} spot={ctx?.price?.last} />
        <RegimeCard regime={ctx?.regime} />
      </div>
    </div>
  );
}

/** @param {{ value: string, onChange: (r: string) => void }} props */
function RangeBar({ value, onChange }) {
  return (
    <div className="inline-flex gap-1 font-mono text-[10px] tracking-[0.15em] uppercase">
      {RANGES.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onChange(r)}
          className={classNames(
            'px-2 py-1 border',
            r === value
              ? 'border-cyan text-cyan bg-cyan/10'
              : 'border-border-subtle text-text-secondary hover:text-text-primary',
          )}
        >
          {r}
        </button>
      ))}
    </div>
  );
}

/** @param {{ q: any }} props */
function BigChart({ q }) {
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const points = (q.data?.points || []).map((p) => ({
    t: p.timestamp || p.date || p.t,
    v: parseFloat(p.close ?? p.price ?? p.v ?? 0),
  }));
  if (!points.length) return <EmptyState title="No price data" />;
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points}>
          <defs>
            <linearGradient id="researchFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5BA3C6" stopOpacity={0.45} />
              <stop offset="100%" stopColor="#5BA3C6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
          <XAxis dataKey="t" stroke="#7C8A9A" fontSize={10} tickLine={false} hide />
          <YAxis stroke="#7C8A9A" fontSize={10} tickLine={false} domain={['auto', 'auto']} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtUsd(v)} />
          <Area
            type="monotone"
            dataKey="v"
            stroke="#5BA3C6"
            strokeWidth={1.6}
            fill="url(#researchFill)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** @param {{ symbol: string }} props */
function FinancialsTab({ symbol }) {
  const companyQ = useQuery({
    queryKey: ['research-company', symbol],
    queryFn: () => getCompany(symbol),
    enabled: !!symbol,
    retry: false,
  });
  const researchQ = useQuery({
    queryKey: ['research-brief', symbol],
    queryFn: () => getResearch(symbol),
    enabled: !!symbol,
    retry: false,
    staleTime: 5 * 60_000,
  });
  if (companyQ.isLoading) return <LoadingState rows={5} label="Loading company…" />;
  if (companyQ.isError) return <ErrorState error={companyQ.error} onRetry={companyQ.refetch} />;
  const c = companyQ.data || {};
  const r = researchQ.data || {};
  const rows = [
    ['Sector', c.sector],
    ['Industry', c.industry],
    ['Exchange', c.exchange],
    ['Currency', c.currency],
    ['Quote type', c.quote_type],
    ['Market cap', c.market_cap != null ? fmtUsd(c.market_cap, { compact: true }) : null],
    ['P/E ratio', r.pe_ratio != null ? fmtNum(r.pe_ratio, 2) : null],
    ['Employees', c.full_time_employees != null ? fmtBigInt(c.full_time_employees) : null],
    ['Location', c.location],
    [
      'Website',
      c.website ? (
        <ExternalAnchor key="w" href={c.website}>
          {c.website.replace(/^https?:\/\//, '')}
        </ExternalAnchor>
      ) : null,
    ],
  ];
  return (
    <div className="space-y-4">
      <SectionHeader
        title={c.company_name || symbol}
        subtitle={c.sector || ''}
        meta={<Building2 size={14} className="text-text-muted" />}
      />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 border border-border-subtle p-4">
        {rows
          .filter(([, v]) => v !== null && v !== undefined && v !== '')
          .map(([label, value]) => (
            <KvRow key={label} label={label} value={value} />
          ))}
      </div>
      {c.business_summary && (
        <div className="border border-border-subtle p-4">
          <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted mb-2">
            Business summary
          </div>
          <p className="text-body-sm text-text-secondary leading-relaxed whitespace-pre-line">
            {c.business_summary}
          </p>
        </div>
      )}
      {r.summary && (
        <div className="border border-border-subtle p-4">
          <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted mb-2">
            AI research brief
          </div>
          <p className="text-body-sm text-text-secondary leading-relaxed">{r.summary}</p>
          {Array.isArray(r.key_insights) && r.key_insights.length > 0 && (
            <ul className="list-disc list-inside text-body-sm text-text-secondary mt-3 space-y-1">
              {r.key_insights.slice(0, 6).map((k, i) => (
                <li key={i}>{k}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** @param {{ label: string, value: any }} props */
function KvRow({ label, value }) {
  return (
    <div className="flex justify-between gap-4 text-body-sm py-1 border-b border-border-subtle/40">
      <span className="text-text-muted">{label}</span>
      <span className="font-mono text-text-primary text-right">{value ?? '—'}</span>
    </div>
  );
}

/** @param {{ symbol: string }} props */
function TechnicalsTab({ symbol }) {
  const queries = useQueries({
    queries: [
      {
        queryKey: ['ind', symbol, 'rsi', INDICATOR_RANGE],
        queryFn: () => getIndicator(symbol, { name: 'rsi', range: INDICATOR_RANGE, period: 14 }),
        enabled: !!symbol,
        retry: false,
      },
      {
        queryKey: ['ind', symbol, 'macd', INDICATOR_RANGE],
        queryFn: () =>
          getIndicator(symbol, { name: 'macd', range: INDICATOR_RANGE, fast: 12, slow: 26, signal: 9 }),
        enabled: !!symbol,
        retry: false,
      },
      {
        queryKey: ['ind', symbol, 'sma', INDICATOR_RANGE],
        queryFn: () => getIndicator(symbol, { name: 'sma', range: INDICATOR_RANGE, period: 20 }),
        enabled: !!symbol,
        retry: false,
      },
      {
        queryKey: ['ind', symbol, 'bbands', INDICATOR_RANGE],
        queryFn: () => getIndicator(symbol, { name: 'bbands', range: INDICATOR_RANGE, period: 20, k: 2 }),
        enabled: !!symbol,
        retry: false,
      },
    ],
  });
  const [rsi, macd, sma, bbands] = queries;
  return (
    <div className="space-y-4">
      <SectionHeader title="Technicals" subtitle={`${INDICATOR_RANGE} window`} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <IndicatorPanel title="RSI(14)" q={rsi} kind="rsi" />
        <IndicatorPanel title="MACD(12,26,9)" q={macd} kind="macd" />
        <IndicatorPanel title="SMA(20)" q={sma} kind="sma" />
        <IndicatorPanel title="Bollinger Bands(20, k=2)" q={bbands} kind="bbands" />
      </div>
    </div>
  );
}

/** @param {{ title: string, q: any, kind: 'rsi'|'macd'|'sma'|'bbands' }} props */
function IndicatorPanel({ title, q, kind }) {
  if (q.isLoading) {
    return (
      <PanelShell title={title}>
        <LoadingState rows={3} />
      </PanelShell>
    );
  }
  if (q.isError) {
    return (
      <PanelShell title={title}>
        <ErrorState error={q.error} onRetry={q.refetch} />
      </PanelShell>
    );
  }
  const data = q.data;
  if (!data?.timestamps?.length) {
    return (
      <PanelShell title={title}>
        <EmptyState title="No indicator data" />
      </PanelShell>
    );
  }
  const rows = data.timestamps.map((t, i) => {
    const row = { t };
    for (const k of Object.keys(data.series || {})) {
      row[k] = data.series[k]?.[i] ?? null;
    }
    return row;
  });
  return (
    <PanelShell title={title}>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          {kind === 'macd' ? (
            <BarChart data={rows}>
              <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
              <XAxis dataKey="t" stroke="#7C8A9A" fontSize={10} hide />
              <YAxis stroke="#7C8A9A" fontSize={10} domain={['auto', 'auto']} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="histogram" fill="#3D7FA5" isAnimationActive={false} />
              <Line type="monotone" dataKey="macd" stroke="#14F1D9" strokeWidth={1.4} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="signal" stroke="#FF8FB1" strokeWidth={1.2} dot={false} isAnimationActive={false} />
            </BarChart>
          ) : kind === 'rsi' ? (
            <LineChart data={rows}>
              <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
              <XAxis dataKey="t" stroke="#7C8A9A" fontSize={10} hide />
              <YAxis stroke="#7C8A9A" fontSize={10} domain={[0, 100]} ticks={[0, 30, 50, 70, 100]} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="value" stroke="#14F1D9" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          ) : (
            <LineChart data={rows}>
              <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
              <XAxis dataKey="t" stroke="#7C8A9A" fontSize={10} hide />
              <YAxis stroke="#7C8A9A" fontSize={10} domain={['auto', 'auto']} />
              <Tooltip contentStyle={tooltipStyle} />
              {kind === 'sma' && (
                <Line type="monotone" dataKey="value" stroke="#14F1D9" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              )}
              {kind === 'bbands' && (
                <>
                  <Line type="monotone" dataKey="upper" stroke="#FF8FB1" strokeWidth={1.2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="middle" stroke="#5BA3C6" strokeWidth={1.4} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="lower" stroke="#7CD9FF" strokeWidth={1.2} dot={false} isAnimationActive={false} />
                </>
              )}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </PanelShell>
  );
}

/** @param {{ title: string, children: any }} props */
function PanelShell({ title, children }) {
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
        <Activity size={12} /> {title}
      </div>
      {children}
    </div>
  );
}

/** @param {{ symbol: string }} props */
function NewsTab({ symbol }) {
  const newsQ = useQuery({
    queryKey: ['research-news', symbol],
    queryFn: () => getNews(symbol),
    enabled: !!symbol,
    retry: false,
    staleTime: 5 * 60_000,
  });
  if (newsQ.isLoading) return <LoadingState rows={4} label="Loading news…" />;
  if (newsQ.isError) return <ErrorState error={newsQ.error} onRetry={newsQ.refetch} />;
  const article = newsQ.data;
  if (!article || !article.summary) {
    return <EmptyState title="No news" hint="Tavily returned no summary." />;
  }
  return (
    <div className="space-y-4">
      <SectionHeader
        title="News"
        subtitle={article.source || 'Tavily'}
        meta={<Newspaper size={14} className="text-text-muted" />}
      />
      <div className="border border-border-subtle p-4 space-y-3">
        <div className="flex items-center gap-3 text-caption text-text-muted">
          <span className="font-mono uppercase tracking-[0.15em]">{article.source || '—'}</span>
          <span>·</span>
          <span>{fmtRelativeTime(article.timestamp)}</span>
        </div>
        <p className="text-body-sm text-text-secondary leading-relaxed whitespace-pre-line">
          {article.summary}
        </p>
      </div>
    </div>
  );
}

/** @param {{ symbol: string, ctx: any }} props */
function SentimentTab({ symbol, ctx }) {
  const social = ctx?.social;
  const postsQ = useQuery({
    queryKey: ['research-social-posts', symbol],
    queryFn: () => searchSocial(symbol, 'x'),
    enabled: !!symbol,
    retry: false,
    staleTime: 60_000,
  });
  if (!social && !postsQ.data) {
    return <EmptyState title="No sentiment" hint="Social context not available for this symbol." />;
  }
  return (
    <div className="space-y-4">
      <SectionHeader
        title="Sentiment"
        subtitle="social + market"
        meta={<Users size={14} className="text-text-muted" />}
      />
      {social && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <ScoreTile label="Social" value={social.social_score} />
          <ScoreTile label="Market" value={social.market_score} />
          <ScoreTile label="Final weight" value={social.final_weight} fmt="number" />
          <ScoreTile label="Action" value={social.action} fmt="text" />
          <ScoreTile label="Confidence" value={social.confidence_label} fmt="text" />
        </div>
      )}
      {Array.isArray(social?.reasons) && social.reasons.length > 0 && (
        <div className="border border-border-subtle p-3">
          <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted mb-2">
            Reasons
          </div>
          <ul className="list-disc list-inside text-body-sm text-text-secondary space-y-1">
            {social.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      <SocialPosts q={postsQ} />
    </div>
  );
}

/** @param {{ label: string, value: any, fmt?: 'pct'|'number'|'text' }} props */
function ScoreTile({ label, value, fmt = 'pct' }) {
  let display = '—';
  if (value != null) {
    if (fmt === 'text') display = String(value);
    else if (fmt === 'number') display = fmtNum(value, 2);
    else display = fmtPctLocal(value);
  }
  return (
    <div className="border border-border-subtle p-3">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{label}</div>
      <div className="text-h3 font-mono text-text-primary mt-1">{display}</div>
    </div>
  );
}

/** @param {{ q: any }} props */
function SocialPosts({ q }) {
  if (q.isLoading) return <LoadingState rows={2} label="Loading posts…" />;
  if (q.isError) return null;
  const items = q.data?.results || q.data?.items || [];
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
        Representative posts
      </div>
      {items.slice(0, 5).map((p, i) => (
        <div key={i} className="border border-border-subtle p-3 text-body-sm text-text-secondary">
          <div className="flex items-center gap-2 text-caption text-text-muted mb-1">
            <span className="font-mono uppercase">{p.author || p.handle || p.source || 'X'}</span>
            <span>·</span>
            <span>{fmtRelativeTime(p.timestamp || p.published_date || p.created_at)}</span>
          </div>
          <div>{p.text || p.content || p.title || ''}</div>
        </div>
      ))}
    </div>
  );
}

/** @param {{ symbol: string, ctx: any }} props */
function OptionsTab({ symbol, ctx }) {
  const gexQ = useQuery({
    queryKey: ['research-gex', symbol],
    queryFn: () => getOptionsChainGex(symbol, 6),
    enabled: !!symbol,
    retry: false,
    staleTime: 60_000,
  });
  const optionsFlow = ctx?.options_flow;
  const topStrikes = useMemo(() => {
    const list = gexQ.data?.by_strike || [];
    return [...list]
      .sort((a, b) => Math.abs(b.net_gex) - Math.abs(a.net_gex))
      .slice(0, TOP_GEX_STRIKES);
  }, [gexQ.data]);
  if (gexQ.isLoading) return <LoadingState rows={5} label="Loading options chain…" />;
  if (gexQ.isError) return <ErrorState error={gexQ.error} onRetry={gexQ.refetch} />;
  const g = gexQ.data;
  if (!g) return <EmptyState title="No options data" />;
  return (
    <div className="space-y-4">
      <SectionHeader
        title="Options"
        subtitle={`spot ${fmtUsd(g.spot)}`}
        meta={<Layers size={14} className="text-text-muted" />}
        action={
          <Link to="/options" className="btn-secondary btn-sm inline-flex items-center gap-1">
            Full chain <ArrowUpRight size={12} />
          </Link>
        }
      />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <LevelTile label="Call wall" value={g.call_wall} spot={g.spot} />
        <LevelTile label="Put wall" value={g.put_wall} spot={g.spot} />
        <LevelTile label="Zero gamma" value={g.zero_gamma} spot={g.spot} />
        <LevelTile label="Max pain" value={g.max_pain} spot={g.spot} />
      </div>
      {optionsFlow && (
        <div className="text-body-sm text-text-secondary">
          ATM IV{' '}
          <span className="font-mono text-text-primary">
            {optionsFlow.atm_iv == null ? '—' : `${(optionsFlow.atm_iv * 100).toFixed(1)}%`}
          </span>
          {' · '}
          P/C OI{' '}
          <span className="font-mono text-text-primary">
            {fmtNum(optionsFlow.put_call_oi_ratio, 2)}
          </span>
        </div>
      )}
      <div className="border border-border-subtle">
        <div className="px-3 py-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted border-b border-border-subtle flex items-center gap-2">
          <BarChart3 size={12} /> Top {TOP_GEX_STRIKES} strikes by |net GEX|
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Strike</th>
              <th className="tbl-num">Net GEX</th>
              <th className="tbl-num">Call OI</th>
              <th className="tbl-num">Put OI</th>
              <th className="tbl-num">Total OI</th>
            </tr>
          </thead>
          <tbody>
            {topStrikes.map((s) => (
              <tr key={s.strike}>
                <td className="font-medium text-steel-50">{fmtUsd(s.strike)}</td>
                <td
                  className={classNames(
                    'tbl-num font-mono',
                    s.net_gex > 0 ? 'text-bull' : s.net_gex < 0 ? 'text-bear' : '',
                  )}
                >
                  {fmtNum(s.net_gex, 0)}
                </td>
                <td className="tbl-num font-mono">{fmtBigInt(s.call_oi)}</td>
                <td className="tbl-num font-mono">{fmtBigInt(s.put_oi)}</td>
                <td className="tbl-num font-mono">{fmtBigInt(s.oi)}</td>
              </tr>
            ))}
            {topStrikes.length === 0 && (
              <tr>
                <td colSpan={5} className="text-center text-text-muted py-4">No strike data</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="border border-border-subtle">
        <div className="px-3 py-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted border-b border-border-subtle">
          By expiry
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Expiry</th>
              <th className="tbl-num">Total GEX</th>
              <th className="tbl-num">Max pain</th>
              <th className="tbl-num">Contracts</th>
            </tr>
          </thead>
          <tbody>
            {(g.by_expiry || []).slice(0, 8).map((e) => (
              <tr key={e.expiry}>
                <td className="font-mono">{e.expiry}</td>
                <td className="tbl-num font-mono">{fmtNum(e.total_gex, 0)}</td>
                <td className="tbl-num font-mono">{fmtUsd(e.max_pain)}</td>
                <td className="tbl-num font-mono">{fmtBigInt(e.contracts)}</td>
              </tr>
            ))}
            {(!g.by_expiry || g.by_expiry.length === 0) && (
              <tr>
                <td colSpan={4} className="text-center text-text-muted py-4">No expiry data</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** @param {{ label: string, value: number | null | undefined, spot: number | null | undefined }} props */
function LevelTile({ label, value, spot }) {
  const dist =
    spot && value != null
      ? `${value > spot ? '+' : ''}${(((value - spot) / spot) * 100).toFixed(1)}%`
      : '';
  return (
    <div className="border border-border-subtle p-3">
      <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">{label}</div>
      <div className="text-h3 font-mono text-text-primary mt-1">{fmtUsd(value)}</div>
      {dist && <div className="text-caption text-text-muted">{dist} from spot</div>}
    </div>
  );
}

/** @param {{ href: string, children: any }} props */
function ExternalAnchor({ href, children }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-cyan hover:text-cyan-light"
    >
      {children} <ExternalLink size={11} />
    </a>
  );
}

function SourcesFooter() {
  const sources = [
    'Overview · /api/symbols/:symbol/context · /api/chart/:symbol',
    'Financials · /api/company/:symbol · /api/research/:symbol',
    'Technicals · /api/indicators/:symbol',
    'News · /api/news/:symbol',
    'Sentiment · /api/symbols/:symbol/context · /api/social/search',
    'Options · /api/options-chain/:symbol',
  ];
  return (
    <div className="text-caption text-text-muted space-y-1 pt-4 border-t border-border-subtle/40">
      <div className="font-mono uppercase tracking-[0.15em]">Sources</div>
      {sources.map((s) => (
        <div key={s} className="font-mono">{s}</div>
      ))}
    </div>
  );
}
