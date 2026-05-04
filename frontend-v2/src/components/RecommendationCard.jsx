import { useState } from 'react';
import { TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react';
import { classNames, fmtUsd } from '../lib/format.js';

const STATE_TONE = {
  open: { label: '开仓', tone: 'border-cyan/40 text-cyan' },
  add: { label: '加仓', tone: 'border-bull text-bull' },
  reduce: { label: '减仓', tone: 'border-amber-400/50 text-amber-300' },
  close: { label: '平仓', tone: 'border-bear text-bear' },
  hold: { label: '持有', tone: 'border-text-muted text-text-muted' },
};

export default function RecommendationCard({ rec }) {
  const [expanded, setExpanded] = useState(false);
  const isBuy = rec.action === 'buy';
  const Icon = isBuy ? TrendingUp : TrendingDown;
  const tone = isBuy ? 'border-bull text-bull' : 'border-bear text-bear';
  const confPct = Math.round((rec.confidence || 0) * 100);
  const stateMeta = STATE_TONE[rec.position_state] || STATE_TONE.open;
  return (
    <div className={classNames('card space-y-2 border', tone)}>
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Icon size={18} />
          <span className="font-mono text-h2">{rec.symbol}</span>
          <span className="font-mono text-[10px] tracking-[0.15em] uppercase">
            {isBuy ? '买入' : '卖出'} #{rec.rank}
          </span>
          <span
            className={classNames(
              'px-1.5 py-0.5 border text-[10px] uppercase tracking-[0.1em]',
              stateMeta.tone,
            )}
          >
            {stateMeta.label}
          </span>
        </div>
        <span className="font-mono text-caption text-text-muted">
          score {rec.ensemble_score.toFixed(3)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-body-sm font-mono">
        <Field label="入场" value={`${fmtUsd(rec.entry_low)}~${fmtUsd(rec.entry_high)}`} />
        <Field label="持仓" value={`${rec.holding_days}天`} />
        <Field label="止损" value={fmtUsd(rec.stop_loss)} tone="text-bear" />
        <Field label="目标" value={fmtUsd(rec.take_profit)} tone="text-bull" />
        <Field label="仓位" value={`${rec.position_pct.toFixed(1)}%`} />
        <Field label="置信" value={`${confPct}%`} />
      </div>
      <div>
        <div className="h-1 bg-border-subtle">
          <div className="h-1 bg-cyan" style={{ width: `${confPct}%` }} />
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-caption">
        <button
          type="button"
          onClick={() => setExpanded((e) => (e === 'reasoning' ? false : 'reasoning'))}
          className="px-2 py-0.5 border border-border-subtle font-mono text-[10px] uppercase tracking-[0.1em] hover:text-text-primary"
        >
          推理 ({rec.reasoning?.length || 0})
        </button>
        {rec.risk_signals?.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((e) => (e === 'risks' ? false : 'risks'))}
            className="px-2 py-0.5 border border-bear/40 text-bear font-mono text-[10px] uppercase tracking-[0.1em] hover:bg-bear/10"
          >
            <AlertTriangle size={10} className="inline mr-1" />
            风险 ({rec.risk_signals.length})
          </button>
        )}
      </div>
      {expanded === 'reasoning' && (
        <ul className="text-caption font-mono space-y-1 border-t border-border-subtle pt-2">
          {(rec.reasoning || []).map((r, i) => (
            <li key={i} className="space-y-0.5">
              <div className="text-text-secondary truncate" title={r.formula}>{r.formula}</div>
              <div className="text-text-muted">
                fitness {r.fitness?.toFixed(4)} · weight {r.weight?.toFixed(2)} · {r.interpretation}
              </div>
            </li>
          ))}
        </ul>
      )}
      {expanded === 'risks' && (
        <ul className="text-caption font-mono space-y-1 border-t border-bear/30 pt-2 text-rose-400">
          {(rec.risk_signals || []).map((s, i) => (
            <li key={i}>· {s.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Field({ label, value, tone }) {
  return (
    <div>
      <div className="text-text-muted text-caption uppercase tracking-[0.1em]">{label}</div>
      <div className={classNames('font-mono', tone || '')}>{value}</div>
    </div>
  );
}
