// SymbolPreview — shows the same enriched context the AI Council ingests
// for one symbol. Lets the user inspect price + technicals + volume +
// options flow + sector regime before acting on an LLM verdict.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { TrendingDown, TrendingUp } from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getChart, getSignals, getSymbolContext } from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from './primitives.jsx';
import SignalsMarkers from './SignalsMarkers.jsx';
import { fmtUsd, classNames } from '../lib/format.js';
import {
  TechnicalsCard,
  VolumeCard,
  OptionsCard,
  RegimeCard,
  fmtPctLocal as fmtPct,
} from './symbolContextCards.jsx';

const RANGES = ['1d', '5d', '1mo', '3mo', '6mo', '1y'];

/**
 * @param {{ symbol: string, defaultRange?: string }} props
 */
export default function SymbolPreview({ symbol, defaultRange = '1mo' }) {
  const [range, setRange] = useState(defaultRange);

  const ctxQ = useQuery({
    queryKey: ['symbol-context', symbol],
    queryFn: () => getSymbolContext(symbol),
    enabled: !!symbol,
    staleTime: 30_000,
    retry: false,
  });

  const chartQ = useQuery({
    queryKey: ['chart', symbol, range],
    queryFn: () => getChart(symbol, range),
    enabled: !!symbol,
    retry: false,
  });

  const sigQ = useQuery({
    queryKey: ['signals', symbol, range],
    queryFn: () => getSignals(symbol, range),
    enabled: !!symbol,
    staleTime: 60_000,
    retry: false,
  });

  if (!symbol) return null;
  if (ctxQ.isLoading) return <LoadingState rows={4} label={`Loading ${symbol}…`} />;
  if (ctxQ.isError) return <ErrorState error={ctxQ.error} onRetry={ctxQ.refetch} />;
  const ctx = ctxQ.data;
  if (!ctx) return <EmptyState title={symbol} hint="No context available." />;

  return (
    <div className="card space-y-4">
      <Header ctx={ctx} />
      <div>
        <RangeBar value={range} onChange={setRange} />
        <ChartBlock q={chartQ} signals={sigQ.data?.signals} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TechnicalsCard tech={ctx.technicals} />
        <VolumeCard volume={ctx.volume_profile} />
        <OptionsCard options={ctx.options_flow} spot={ctx.price?.last} />
        <RegimeCard regime={ctx.regime} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Header({ ctx }) {
  const price = ctx.price || {};
  const change = price.change_pct ?? 0;
  const tone = change > 0 ? 'text-bull' : change < 0 ? 'text-bear' : 'text-text-secondary';
  const Arrow = change >= 0 ? TrendingUp : TrendingDown;
  return (
    <div className="flex items-baseline gap-3 flex-wrap">
      <Link
        to={`/research/${encodeURIComponent(ctx.symbol)}`}
        className="text-h2 font-semibold text-text-primary hover:text-cyan transition-colors"
      >
        {ctx.symbol}
      </Link>
      <div className="text-body font-mono">{fmtUsd(price.last)}</div>
      <div className={classNames('inline-flex items-center gap-1 text-body-sm font-medium', tone)}>
        <Arrow size={14} /> {fmtPct(change)} 1d
      </div>
      <div className="text-caption text-text-muted">
        1w {fmtPct(price.week_change_pct)} · 1m {fmtPct(price.month_change_pct)} · 1y {fmtPct(price.year_change_pct)}
      </div>
    </div>
  );
}

function RangeBar({ value, onChange }) {
  return (
    <div className="inline-flex gap-1 font-mono text-[10px] tracking-[0.15em] uppercase mb-2">
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

function ChartBlock({ q, signals }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const points = (q.data?.points || []).map((p) => ({
    t: p.timestamp || p.date || p.t,
    v: parseFloat(p.close ?? p.price ?? p.v ?? 0),
  }));
  if (!points.length) return <EmptyState title="No price data" />;
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points}>
          <defs>
            <linearGradient id="symbolPreviewFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5BA3C6" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#5BA3C6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
          <XAxis dataKey="t" stroke="#7C8A9A" fontSize={10} tickLine={false} hide />
          <YAxis stroke="#7C8A9A" fontSize={10} tickLine={false} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{
              background: '#0F1923',
              border: '1px solid #3D7FA5',
              borderRadius: 6,
              color: '#E8ECF1',
              fontSize: 12,
            }}
            formatter={(v) => fmtUsd(v)}
          />
          <Area
            type="monotone"
            dataKey="v"
            stroke="#5BA3C6"
            strokeWidth={1.5}
            fill="url(#symbolPreviewFill)"
            isAnimationActive={false}
            dot={false}
          />
          {signals && signals.length > 0 && (
            <SignalsMarkers signals={signals} bars={points} />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

