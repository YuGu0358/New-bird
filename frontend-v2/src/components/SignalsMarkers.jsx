// SignalsMarkers — derives recharts ReferenceDot props from the signal list.
// Embed inside an existing <AreaChart> alongside the <Area>; recharts
// renders dots at (x, y) coordinates pulled from each signal's timestamp.
import { ReferenceDot } from 'recharts';

const COLOR = {
  buy: '#16a34a',
  sell: '#dc2626',
};

/**
 * Normalize timestamps to "YYYY-MM-DDTHH:MM" so a chart bar with
 * "2026-04-30T14:00:00.000Z" matches a signal with "2026-04-30T14:00:00+00:00".
 * Strict string equality silently dropped every marker when even microseconds
 * or timezone format differed between the chart and signals endpoints.
 */
function normalizeTs(value) {
  if (value == null) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  // Minute-level precision is coarse enough to absorb format drift but
  // fine enough for both daily and intraday bars.
  return d.toISOString().slice(0, 16);
}

/**
 * @param {{ signals: Array<{kind:string, direction:'buy'|'sell', ts:string, bar_index:number, strength:number, interpretation:string}>,
 *           bars: Array<{t:string, v:number}> }} props
 */
export default function SignalsMarkers({ signals, bars }) {
  if (!signals || !bars) return null;
  const byTs = new Map(
    bars
      .map((b) => [normalizeTs(b.t), b.v])
      .filter(([k]) => k != null),
  );
  return (
    <>
      {signals.map((s, idx) => {
        const key = normalizeTs(s.ts);
        const v = key != null ? byTs.get(key) ?? null : null;
        if (v == null) return null;
        return (
          <ReferenceDot
            key={`${s.kind}-${s.ts}-${idx}`}
            x={s.ts}
            y={v}
            r={Math.max(3, Math.round(3 + (s.strength || 0) * 4))}
            fill={COLOR[s.direction] || '#9ca3af'}
            stroke="#0F1923"
            strokeWidth={1}
            ifOverflow="extendDomain"
          />
        );
      })}
    </>
  );
}
