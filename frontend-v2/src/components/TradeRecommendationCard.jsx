// TradeRecommendationCard — synthesized "what should I do" stance for one symbol.
// Renders the rule-based recommendation from /api/trade-recommendations/{symbol}.
import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { TrendingUp, TrendingDown, Pause, AlertTriangle, Target, Users, RefreshCw } from 'lucide-react';
import { getTradeRecommendation, councilAnalyze } from '../lib/api.js';
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

const DEFAULT_PERSONA_IDS = ['macro_bull', 'value_hawk', 'momentum_chaser'];

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

  const [councilOpen, setCouncilOpen] = useState(false);
  const councilM = useMutation({
    mutationFn: () => councilAnalyze({ symbol, persona_ids: DEFAULT_PERSONA_IDS }),
  });

  const handleToggleCouncil = () => {
    const next = !councilOpen;
    setCouncilOpen(next);
    if (next && !councilM.data && !councilM.isPending) {
      councilM.mutate();
    }
  };

  if (recQ.isLoading) return <LoadingState rows={4} />;
  if (recQ.isError) return <ErrorState error={recQ.error} onRetry={recQ.refetch} />;
  const rec = recQ.data;
  if (!rec) return <EmptyState title={symbol} hint="No recommendation available." />;

  return (
    <div className="card space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-mono text-[11px] tracking-[0.15em] uppercase text-text-muted">
          Trade recommendation · {rec.symbol}
        </div>
        <div className="flex items-center gap-3">
          <div className="text-caption text-text-muted">
            {rec.recent_signals_count} signals · price {rec.current_price ? fmtUsd(rec.current_price) : '—'}
          </div>
          <button
            type="button"
            onClick={handleToggleCouncil}
            className={classNames(
              'inline-flex items-center gap-1 border px-2 py-0.5 text-caption font-mono uppercase tracking-[0.12em] transition-colors',
              councilOpen ? 'border-cyan-400 text-cyan-300' : 'border-border-subtle text-text-secondary hover:border-cyan-400 hover:text-cyan-300',
            )}
          >
            <Users size={12} />
            AI 议会
          </button>
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

      {councilOpen && (
        <CouncilPanel
          mutation={councilM}
          onRetry={() => councilM.mutate()}
        />
      )}
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
          {rec.custom_stop_loss != null ? fmtUsd(rec.custom_stop_loss) : '—'}
          {' / '}
          {rec.custom_take_profit != null ? fmtUsd(rec.custom_take_profit) : '—'}
        </span></div>
    </div>
  );
}

function StanceBlock({ stance }) {
  const tone = ACTION_TONE[stance.action] || ACTION_TONE.wait;
  const Icon = tone.icon;
  const confPct = ((stance.confidence ?? 0) * 100).toFixed(0);
  return (
    <div className={classNames('border p-3 space-y-2', tone.classes)}>
      <div className="flex items-center gap-2">
        <Icon size={14} />
        <span className="font-mono text-[11px] tracking-[0.15em] uppercase">{tone.label}</span>
        <span className="text-caption text-text-muted">conf {confPct}%</span>
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

function CouncilPanel({ mutation, onRetry }) {
  return (
    <div className="border border-cyan-400/40 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-mono text-[11px] tracking-[0.15em] uppercase text-cyan-300">
          AI 议会 · 多视角分析
        </div>
        <button
          type="button"
          onClick={onRetry}
          disabled={mutation.isPending}
          className="inline-flex items-center gap-1 border border-border-subtle px-2 py-0.5 text-caption font-mono uppercase tracking-[0.12em] text-text-secondary hover:border-cyan-400 hover:text-cyan-300 disabled:opacity-50"
        >
          <RefreshCw size={11} />
          重试
        </button>
      </div>

      {mutation.isPending && (
        <div className="text-body-sm text-text-muted">AI 议会思考中…</div>
      )}
      {mutation.isError && (
        <div className="text-body-sm text-rose-400">
          {String(mutation.error?.message || '调用失败')}
        </div>
      )}
      {mutation.data && (mutation.data.analyses || []).length === 0 && !mutation.isPending && (
        <div className="text-body-sm text-text-muted">暂无议会回复</div>
      )}
      {mutation.data && (mutation.data.analyses || []).length > 0 && (
        <div className="space-y-2">
          {mutation.data.analyses.map((a) => (
            <PersonaAnalysis key={a.id} analysis={a} />
          ))}
        </div>
      )}
    </div>
  );
}

function PersonaAnalysis({ analysis }) {
  const verdictKey = (analysis.verdict || 'wait').toLowerCase();
  const tone = ACTION_TONE[verdictKey] || ACTION_TONE.wait;
  const Icon = tone.icon;
  const confPct = ((analysis.confidence ?? 0) * 100).toFixed(0);
  const topFactors = [...(analysis.key_factors || [])]
    .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))
    .slice(0, 3);
  const plan = analysis.action_plan;

  return (
    <div className={classNames('border p-2 space-y-2', tone.classes)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="border border-cyan-400/60 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.15em] uppercase text-cyan-300">
          {String(analysis.persona_id || '').toUpperCase()}
        </span>
        <Icon size={13} />
        <span className="font-mono text-[11px] tracking-[0.15em] uppercase">{tone.label}</span>
        <span className="text-caption text-text-muted">conf {confPct}%</span>
      </div>
      {analysis.reasoning_summary && (
        <div className="text-body-sm text-text-secondary leading-relaxed">
          {analysis.reasoning_summary}
        </div>
      )}
      {plan && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-caption border-t border-border-subtle pt-2">
          <div><span className="text-text-muted">Entry: </span>
            <span className="font-mono">
              {plan.entry_zone_low != null ? fmtUsd(plan.entry_zone_low) : '—'}
              {plan.entry_zone_high != null ? `–${fmtUsd(plan.entry_zone_high)}` : ''}
            </span></div>
          <div><span className="text-text-muted">Stop: </span>
            <span className="font-mono">{plan.stop_loss != null ? fmtUsd(plan.stop_loss) : '—'}</span></div>
          <div><span className="text-text-muted">TP: </span>
            <span className="font-mono">{plan.take_profit != null ? fmtUsd(plan.take_profit) : '—'}</span></div>
          <div><span className="text-text-muted">Horizon: </span>
            <span className="font-mono">{plan.time_horizon || '—'}</span></div>
        </div>
      )}
      {topFactors.length > 0 && (
        <ul className="text-caption text-text-secondary space-y-0.5">
          {topFactors.map((f) => (
            <li key={f.signal} className="leading-relaxed">
              <span className="font-mono text-text-muted">{f.signal}</span>
              {f.interpretation ? `: ${f.interpretation}` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
