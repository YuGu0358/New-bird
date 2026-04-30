// SignalsMarkers — derives recharts ReferenceDot props from the signal list.
// Embed inside an existing <AreaChart> alongside the <Area>; recharts
// renders dots at (x, y) coordinates pulled from each signal's timestamp.
import { ReferenceDot } from 'recharts';

const COLOR = {
  buy: '#16a34a',
  sell: '#dc2626',
};

/**
 * @param {{ signals: Array<{kind:string, direction:'buy'|'sell', ts:string, bar_index:number, strength:number, interpretation:string}>,
 *           bars: Array<{t:string, v:number}> }} props
 */
export default function SignalsMarkers({ signals, bars }) {
  if (!signals || !bars) return null;
  const byTs = new Map(bars.map((b) => [String(b.t), b.v]));
  return (
    <>
      {signals.map((s, idx) => {
        const v = byTs.get(String(s.ts)) ?? null;
        if (v == null) return null;
        return (
          <ReferenceDot
            key={`${s.kind}-${idx}`}
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
