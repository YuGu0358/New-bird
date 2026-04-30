// TradeRecommendationCard — synthesized "what should I do" stance for one symbol.
// Renders the rule-based recommendation from /api/trade-recommendations/{symbol}.
import { useQuery } from '@tanstack/react-query';
import { TrendingUp, TrendingDown, Pause, AlertTriangle, Target } from 'lucide-react';
import { getTradeRecommendation } from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from './primitives.jsx';
import { fmtUsd, classNames } from '../lib/format.js';

const ACTION_TONE = {
  buy: { icon: TrendingUp, classes: 'border-bull text-bull', label: 'BUY' },
  sell: { icon: TrendingDown, classes: 'border-bear text-bear', label: 'SELL' },
  hold: { icon: Pause, classes: 'border-border-subtle text-text-secondary', label: 'HOLD' },
  wait: { icon: Pause, classes: 'border-border-subtle text-text-muted', label: 'WAIT' },
  stop_triggered: { icon: AlertTriangle, classes: 'border-bear text-bear', label: 'STOP HIT' },
  tp_triggered: { icon: Target, classes: 'border-bull text-bull', label: 'TP HIT' },
};

/**
 * @param {{ symbol: string, brokerAccountId?: number|null }} props
 */
export default function TradeRecommendationCard({ symbol, brokerAccountId = null }) {
  const recQ = useQuery({
    queryKey: ['trade-rec', symbol, brokerAccountId],
    queryFn: () => getTradeRecommendation(symbol, brokerAccountId != null ? { broker_account_id: brokerAccountId } : {}),
    enabled: !!symbol,
    staleTime: 60_000,
    retry: false,
  });

  if (recQ.isLoading) return <LoadingState rows={4} />;
  if (recQ.isError) return <ErrorState error={recQ.error} onRetry={recQ.refetch} />;
  const rec = recQ.data;
  if (!rec) return <EmptyState title={symbol} hint="No recommendation available." />;

  return (
    <div className="card space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="font-mono text-[11px] tracking-[0.15em] uppercase text-text-muted">
          Trade recommendation · {rec.symbol}
        </div>
        <div className="text-caption text-text-muted">
          {rec.recent_signals_count} signals · price {rec.current_price ? fmtUsd(rec.current_price) : '—'}
        </div>
      </div>

      {rec.has_position && (
        <PositionBlock rec={rec} />
      )}

      <div className="space-y-3">
        {(rec.stances || []).map((stance, i) => (
          <StanceBlock key={i} stance={stance} />
        ))}
      </div>
    </div>
  );
}

function PositionBlock({ rec }) {
  const upnlTone = rec.unrealized_pnl_pct == null ? '' : rec.unrealized_pnl_pct >= 0 ? 'text-bull' : 'text-bear';
  return (
    <div className="text-body-sm grid grid-cols-2 md:grid-cols-4 gap-2 border-b border-border-subtle pb-2">
      <div><span className="text-text-secondary">Avg cost: </span>
        <span className="font-mono">{rec.avg_cost_basis ? fmtUsd(rec.avg_cost_basis) : '—'}</span></div>
      <div><span className="text-text-secondary">Shares: </span>
        <span className="font-mono">{rec.total_shares ?? '—'}</span></div>
      <div><span className="text-text-secondary">U-PnL: </span>
        <span className={classNames('font-mono', upnlTone)}>
          {rec.unrealized_pnl_pct != null ? `${rec.unrealized_pnl_pct.toFixed(2)}%` : '—'}
        </span></div>
      <div><span className="text-text-secondary">Stop / TP: </span>
        <span className="font-mono">
          {rec.custom_stop_loss ? fmtUsd(rec.custom_stop_loss) : '—'}
          {' / '}
          {rec.custom_take_profit ? fmtUsd(rec.custom_take_profit) : '—'}
        </span></div>
    </div>
  );
}

function StanceBlock({ stance }) {
  const tone = ACTION_TONE[stance.action] || ACTION_TONE.wait;
  const Icon = tone.icon;
  return (
    <div className={classNames('border p-3 space-y-2', tone.classes)}>
      <div className="flex items-center gap-2">
        <Icon size={14} />
        <span className="font-mono text-[11px] tracking-[0.15em] uppercase">{tone.label}</span>
        <span className="text-caption text-text-muted">conf {(stance.confidence * 100).toFixed(0)}%</span>
      </div>
      <div className="text-body-sm font-medium">{stance.headline}</div>
      <ul className="text-caption text-text-secondary space-y-1">
        {(stance.rationale || []).map((r, i) => (
          <li key={i} className="leading-relaxed">{r}</li>
        ))}
      </ul>
    </div>
  );
}
