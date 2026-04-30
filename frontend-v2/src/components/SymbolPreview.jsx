// SymbolPreview — shows the same enriched context the AI Council ingests
// for one symbol. Lets the user inspect price + technicals + volume +
// options flow + sector regime before acting on an LLM verdict.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Layers,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getChart, getSymbolContext } from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from './primitives.jsx';
import { fmtUsd, classNames } from '../lib/format.js';

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
        <ChartBlock q={chartQ} />
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
      <div className="text-h2 font-semibold text-text-primary">{ctx.symbol}</div>
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

function ChartBlock({ q }) {
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
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function TechnicalsCard({ tech }) {
  if (!tech) return <BlockEmpty title="Technicals" hint="Indicator data unavailable." icon={Activity} />;
  const rsi = tech.rsi_14;
  const rsiTone = rsi == null ? '' : rsi >= 70 ? 'text-bear' : rsi <= 30 ? 'text-bull' : 'text-text-secondary';
  const macdHist = tech.macd_hist;
  const macdTone = macdHist == null ? '' : macdHist > 0 ? 'text-bull' : macdHist < 0 ? 'text-bear' : '';
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={Activity} title="Technicals" />
      <Row label="RSI(14)" value={fmtNum(rsi, 1)} tone={rsiTone}
        suffix={rsi >= 70 ? 'overbought' : rsi <= 30 ? 'oversold' : ''} />
      <Row label="MACD hist" value={fmtNum(macdHist, 3)} tone={macdTone}
        suffix={macdHist > 0 ? 'bullish' : macdHist < 0 ? 'bearish' : ''} />
      <Row label="SMA(20)" value={fmtUsd(tech.sma_20)} />
      <Row label="EMA(20)" value={fmtUsd(tech.ema_20)} />
      <BollingerBar position={tech.bbands_position} upper={tech.bbands_upper} lower={tech.bbands_lower} />
    </div>
  );
}

function VolumeCard({ volume }) {
  if (!volume) return <BlockEmpty title="Volume" hint="Volume data unavailable." icon={BarChart3} />;
  const x = volume.today_vs_avg_x;
  const xTone = x == null ? '' : x >= 1.5 ? 'text-bull' : x < 0.7 ? 'text-bear' : '';
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={BarChart3} title="Volume" />
      <Row label="Today" value={fmtBigInt(volume.today_volume)} />
      <Row label="20d avg" value={fmtBigInt(volume.avg_volume_20d)} />
      <Row label="vs 20d" value={x == null ? '—' : `${x.toFixed(2)}x`} tone={xTone}
        suffix={x >= 1.5 ? 'high' : x < 0.7 ? 'thin' : ''} />
      <Row label="Turnover" value={volume.turnover_pct == null ? '—' : `${volume.turnover_pct.toFixed(2)}%`} />
    </div>
  );
}

function OptionsCard({ options, spot }) {
  if (!options) return <BlockEmpty title="Options flow" hint="Chain data unavailable." icon={Layers} />;
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={Layers} title="Options flow" />
      <Row label="Call wall" value={fmtUsd(options.call_wall)}
        suffix={spot && options.call_wall ? `${pctFromSpot(spot, options.call_wall)} from spot` : ''} />
      <Row label="Put wall" value={fmtUsd(options.put_wall)}
        suffix={spot && options.put_wall ? `${pctFromSpot(spot, options.put_wall)} from spot` : ''} />
      <Row label="Zero gamma" value={fmtUsd(options.zero_gamma)} />
      <Row label="Max pain" value={fmtUsd(options.max_pain)} />
      <Row label="P/C OI" value={fmtNum(options.put_call_oi_ratio, 2)}
        tone={options.put_call_oi_ratio > 1 ? 'text-bear' : options.put_call_oi_ratio < 0.7 ? 'text-bull' : ''}
        suffix={options.put_call_oi_ratio > 1 ? 'put-heavy' : options.put_call_oi_ratio < 0.7 ? 'call-heavy' : ''} />
      <Row label="ATM IV" value={options.atm_iv == null ? '—' : `${(options.atm_iv * 100).toFixed(1)}%`} />
    </div>
  );
}

function RegimeCard({ regime }) {
  if (!regime) return <BlockEmpty title="Regime" hint="Sector data unavailable." icon={AlertTriangle} />;
  const sectorMove = regime.sector_5d_change_pct;
  const tone = sectorMove == null ? '' : sectorMove > 0 ? 'text-bull' : sectorMove < 0 ? 'text-bear' : '';
  const rank = regime.sector_rank_among_11;
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={AlertTriangle} title="Regime" />
      <Row label="Sector" value={regime.sector || '—'} />
      <Row label="Sector 5d" value={fmtPct(sectorMove)} tone={tone}
        suffix={rank ? `rank ${rank}/11` : ''} />
      {regime.macro_tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
          {regime.macro_tags.slice(0, 6).map((tag) => (
            <span key={tag} className="px-2 py-0.5 border border-border-subtle text-[10px] font-mono uppercase tracking-[0.1em] text-text-secondary">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// primitives

function CardHeader({ icon: Icon, title }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
      <Icon size={12} /> {title}
    </div>
  );
}

function Row({ label, value, tone = '', suffix = '' }) {
  return (
    <div className="flex justify-between text-body-sm">
      <span className="text-text-secondary">{label}</span>
      <span className={classNames('font-mono', tone)}>
        {value}
        {suffix && <span className="text-caption text-text-muted ml-1">· {suffix}</span>}
      </span>
    </div>
  );
}

function BollingerBar({ position, upper, lower }) {
  if (position == null) return null;
  const pct = Math.max(0, Math.min(1, position)) * 100;
  return (
    <div>
      <div className="flex justify-between text-caption text-text-muted">
        <span>BB {fmtUsd(lower)}</span>
        <span>{fmtUsd(upper)}</span>
      </div>
      <div className="relative h-1 bg-border-subtle mt-1">
        <div
          className="absolute top-0 h-1 bg-cyan"
          style={{ left: `${pct}%`, width: '2px' }}
        />
      </div>
    </div>
  );
}

function BlockEmpty({ icon, title, hint }) {
  return (
    <div className="border border-border-subtle p-3">
      <CardHeader icon={icon} title={title} />
      <div className="text-caption text-text-muted mt-2">{hint}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// formatting

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${Number(v).toFixed(2)}%`;
}

function fmtNum(v, decimals = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toFixed(decimals);
}

function fmtBigInt(v) {
  if (v == null) return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(Math.round(n));
}

function pctFromSpot(spot, level) {
  if (!spot || !level) return '';
  const p = ((level - spot) / spot) * 100;
  const sign = p >= 0 ? '+' : '';
  return `${sign}${p.toFixed(1)}%`;
}
