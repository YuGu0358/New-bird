// Shared symbol-context cards used by SymbolPreview (compact list) and the
// full EquityResearchPage. Extracted so visual style stays in sync between
// the inline preview and the deep page.
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Layers,
} from 'lucide-react';
import { fmtUsd, classNames } from '../lib/format.js';

/**
 * @param {{ tech: object | null | undefined }} props
 */
export function TechnicalsCard({ tech }) {
  if (!tech) {
    return <BlockEmpty title="Technicals" hint="Indicator data unavailable." icon={Activity} />;
  }
  const rsi = tech.rsi_14;
  const rsiTone =
    rsi == null ? '' : rsi >= 70 ? 'text-bear' : rsi <= 30 ? 'text-bull' : 'text-text-secondary';
  const macdHist = tech.macd_hist;
  const macdTone =
    macdHist == null ? '' : macdHist > 0 ? 'text-bull' : macdHist < 0 ? 'text-bear' : '';
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={Activity} title="Technicals" />
      <Row
        label="RSI(14)"
        value={fmtNum(rsi, 1)}
        tone={rsiTone}
        suffix={rsi >= 70 ? 'overbought' : rsi <= 30 ? 'oversold' : ''}
      />
      <Row
        label="MACD hist"
        value={fmtNum(macdHist, 3)}
        tone={macdTone}
        suffix={macdHist > 0 ? 'bullish' : macdHist < 0 ? 'bearish' : ''}
      />
      <Row label="SMA(20)" value={fmtUsd(tech.sma_20)} />
      <Row label="EMA(20)" value={fmtUsd(tech.ema_20)} />
      <BollingerBar
        position={tech.bbands_position}
        upper={tech.bbands_upper}
        lower={tech.bbands_lower}
      />
    </div>
  );
}

/**
 * @param {{ volume: object | null | undefined }} props
 */
export function VolumeCard({ volume }) {
  if (!volume) {
    return <BlockEmpty title="Volume" hint="Volume data unavailable." icon={BarChart3} />;
  }
  const x = volume.today_vs_avg_x;
  const xTone = x == null ? '' : x >= 1.5 ? 'text-bull' : x < 0.7 ? 'text-bear' : '';
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={BarChart3} title="Volume" />
      <Row label="Today" value={fmtBigInt(volume.today_volume)} />
      <Row label="20d avg" value={fmtBigInt(volume.avg_volume_20d)} />
      <Row
        label="vs 20d"
        value={x == null ? '—' : `${x.toFixed(2)}x`}
        tone={xTone}
        suffix={x >= 1.5 ? 'high' : x < 0.7 ? 'thin' : ''}
      />
      <Row
        label="Turnover"
        value={volume.turnover_pct == null ? '—' : `${volume.turnover_pct.toFixed(2)}%`}
      />
    </div>
  );
}

/**
 * @param {{ options: object | null | undefined, spot?: number | null }} props
 */
export function OptionsCard({ options, spot }) {
  if (!options) {
    return <BlockEmpty title="Options flow" hint="Chain data unavailable." icon={Layers} />;
  }
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={Layers} title="Options flow" />
      <Row
        label="Call wall"
        value={fmtUsd(options.call_wall)}
        suffix={spot && options.call_wall ? `${pctFromSpot(spot, options.call_wall)} from spot` : ''}
      />
      <Row
        label="Put wall"
        value={fmtUsd(options.put_wall)}
        suffix={spot && options.put_wall ? `${pctFromSpot(spot, options.put_wall)} from spot` : ''}
      />
      <Row label="Zero gamma" value={fmtUsd(options.zero_gamma)} />
      <Row label="Max pain" value={fmtUsd(options.max_pain)} />
      <Row
        label="P/C OI"
        value={fmtNum(options.put_call_oi_ratio, 2)}
        tone={
          options.put_call_oi_ratio > 1
            ? 'text-bear'
            : options.put_call_oi_ratio < 0.7
              ? 'text-bull'
              : ''
        }
        suffix={
          options.put_call_oi_ratio > 1
            ? 'put-heavy'
            : options.put_call_oi_ratio < 0.7
              ? 'call-heavy'
              : ''
        }
      />
      <Row
        label="ATM IV"
        value={options.atm_iv == null ? '—' : `${(options.atm_iv * 100).toFixed(1)}%`}
      />
    </div>
  );
}

/**
 * @param {{ regime: object | null | undefined }} props
 */
export function RegimeCard({ regime }) {
  if (!regime) {
    return <BlockEmpty title="Regime" hint="Sector data unavailable." icon={AlertTriangle} />;
  }
  const sectorMove = regime.sector_5d_change_pct;
  const tone = sectorMove == null ? '' : sectorMove > 0 ? 'text-bull' : sectorMove < 0 ? 'text-bear' : '';
  const rank = regime.sector_rank_among_11;
  return (
    <div className="border border-border-subtle p-3 space-y-2">
      <CardHeader icon={AlertTriangle} title="Regime" />
      <Row label="Sector" value={regime.sector || '—'} />
      <Row
        label="Sector 5d"
        value={fmtPctLocal(sectorMove)}
        tone={tone}
        suffix={rank ? `rank ${rank}/11` : ''}
      />
      {regime.macro_tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
          {regime.macro_tags.slice(0, 6).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 border border-border-subtle text-[10px] font-mono uppercase tracking-[0.1em] text-text-secondary"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// shared primitives + formatters

export function CardHeader({ icon: Icon, title }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
      <Icon size={12} /> {title}
    </div>
  );
}

export function Row({ label, value, tone = '', suffix = '' }) {
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

/**
 * @param {number | null | undefined} v
 * @returns {string}
 */
export function fmtPctLocal(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${Number(v).toFixed(2)}%`;
}

/**
 * @param {number | null | undefined} v
 * @param {number} decimals
 * @returns {string}
 */
export function fmtNum(v, decimals = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toFixed(decimals);
}

/**
 * @param {number | null | undefined} v
 * @returns {string}
 */
export function fmtBigInt(v) {
  if (v == null) return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(Math.round(n));
}

/**
 * @param {number | null | undefined} spot
 * @param {number | null | undefined} level
 * @returns {string}
 */
export function pctFromSpot(spot, level) {
  if (!spot || !level) return '';
  const p = ((level - spot) / spot) * 100;
  const sign = p >= 0 ? '+' : '';
  return `${sign}${p.toFixed(1)}%`;
}
