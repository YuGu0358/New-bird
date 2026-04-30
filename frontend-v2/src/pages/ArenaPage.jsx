// Alpha Arena — leaderboard for the AI Council.
// Runs all (or selected) personas on the same symbols, then surfaces:
//   - a current verdicts grid (rows = personas, columns = symbols)
//   - a scoreboard ranked by historical buy-call P&L
//   - per-persona best/worst calls
//
// Reuses existing primitives + the same React Query patterns as
// IntelligencePage. No new dependencies.

import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Trophy, Send, Check, BarChart3 } from 'lucide-react';

import {
  listPersonas,
  runArena,
  getArenaScoreboard,
} from '../lib/api.js';
import {
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { classNames, fmtRelativeTime } from '../lib/format.js';

const DEFAULT_SYMBOLS = 'SPY, QQQ, NVDA, AAPL, MSFT';
const MAX_SYMBOLS = 5;

function parseSymbols(text) {
  return text
    .split(/[,\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter((s) => s.length > 0)
    .filter((s, i, arr) => arr.indexOf(s) === i)
    .slice(0, MAX_SYMBOLS);
}

function fmtPct(value, { signed = true, digits = 1 } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = signed && value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

function pnlTone(value) {
  if (value === null || value === undefined) return 'text-text-secondary';
  if (value > 0) return 'text-bull';
  if (value < 0) return 'text-bear';
  return 'text-text-secondary';
}

function verdictPillClass(verdict) {
  if (verdict === 'buy') return 'pill-bull';
  if (verdict === 'sell') return 'pill-bear';
  return 'pill-default';
}

export default function ArenaPage() {
  const queryClient = useQueryClient();
  const personasQ = useQuery({ queryKey: ['agent-personas'], queryFn: listPersonas });
  const scoreboardQ = useQuery({
    queryKey: ['arena-scoreboard'],
    queryFn: () => getArenaScoreboard(90),
    refetchInterval: 60_000,
  });

  const [symbolText, setSymbolText] = useState(DEFAULT_SYMBOLS);
  const [selectedPersonas, setSelectedPersonas] = useState(null); // null = all

  const allPersonas = personasQ.data?.items || [];
  const effectivePersonaIds = selectedPersonas ?? allPersonas.map((p) => p.id);

  const runMut = useMutation({
    mutationFn: runArena,
    onSuccess: async () => {
      try {
        await queryClient.invalidateQueries({ queryKey: ['arena-scoreboard'] });
        await queryClient.invalidateQueries({ queryKey: ['agent-history'] });
      } catch (err) {
        // Cache invalidation is best-effort — never blow up the UI.
      }
    },
  });

  const symbols = parseSymbols(symbolText);

  async function submit(e) {
    e.preventDefault();
    if (symbols.length === 0 || effectivePersonaIds.length === 0) return;
    try {
      await runMut.mutateAsync({
        symbols,
        persona_ids: selectedPersonas,
      });
    } catch (err) {
      // The mutation's error state is already rendered via ApiErrorBanner.
    }
  }

  function togglePersona(id) {
    setSelectedPersonas((prev) => {
      const base = prev ?? allPersonas.map((p) => p.id);
      return base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
    });
  }

  function selectAll() {
    setSelectedPersonas(null);
  }

  // Index current verdicts by (persona_id, symbol) for the grid.
  const verdictMap = useMemo(() => {
    const out = new Map();
    for (const c of runMut.data?.current || []) {
      out.set(`${c.persona_id}::${c.symbol}`, c);
    }
    return out;
  }, [runMut.data]);

  // Prefer the freshly-run scoreboard if available; otherwise fall back to
  // the standalone /scoreboard query so the page is useful before any run.
  const scoreboard = runMut.data?.scoreboard || scoreboardQ.data?.scoreboard || [];

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={5}
        title="Alpha Arena"
        segments={[
          { label: '6 personas · same symbols · measurable verdicts' },
          { label: 'P7 · COUNCIL', accent: true },
        ]}
        live={false}
      />

      <RunControls
        symbolText={symbolText}
        setSymbolText={setSymbolText}
        symbols={symbols}
        personas={allPersonas}
        personasLoading={personasQ.isLoading}
        selectedPersonas={selectedPersonas}
        togglePersona={togglePersona}
        selectAll={selectAll}
        runMut={runMut}
        onSubmit={submit}
        effectiveCount={effectivePersonaIds.length}
      />

      {runMut.isError && <ApiErrorBanner error={runMut.error} label="Arena run" />}

      {runMut.isPending && (
        <div className="card">
          <LoadingState rows={6} label={`Running ${effectivePersonaIds.length} personas × ${symbols.length} symbols…`} />
        </div>
      )}

      {runMut.data && (
        <CurrentVerdictsGrid
          symbols={symbols}
          personas={allPersonas.filter((p) => effectivePersonaIds.includes(p.id))}
          verdictMap={verdictMap}
        />
      )}

      <ScoreboardCard q={scoreboardQ} entries={scoreboard} personas={allPersonas} />
    </div>
  );
}

// ---------------------------------------------------------- Run controls

function RunControls({
  symbolText, setSymbolText,
  symbols,
  personas, personasLoading,
  selectedPersonas, togglePersona, selectAll,
  runMut, onSubmit,
  effectiveCount,
}) {
  return (
    <form onSubmit={onSubmit} className="card space-y-5">
      <SectionHeader
        title="Watchlist + personas"
        subtitle={`Up to ${MAX_SYMBOLS} symbols · all 6 personas by default`}
      />

      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-7">
          <label className="h-caption block mb-2">Symbols</label>
          <textarea
            className="input h-20 uppercase font-mono"
            value={symbolText}
            onChange={(e) => setSymbolText(e.target.value)}
            placeholder="SPY, QQQ, NVDA"
          />
          <div className="text-caption text-text-muted mt-1">
            Parsed: {symbols.length > 0 ? symbols.join(' · ') : '—'}
          </div>
        </div>

        <div className="col-span-5">
          <div className="flex items-center justify-between mb-2">
            <label className="h-caption">Personas</label>
            <button
              type="button"
              onClick={selectAll}
              className="text-caption text-cyan hover:text-cyan/80"
            >
              Select all
            </button>
          </div>
          {personasLoading ? (
            <LoadingState rows={1} />
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {personas.map((p) => {
                const active =
                  selectedPersonas == null || selectedPersonas.includes(p.id);
                return (
                  <button
                    type="button"
                    key={p.id}
                    onClick={() => togglePersona(p.id)}
                    className={classNames(
                      'card-dense text-left card-hover relative px-3 py-2',
                      active ? 'border-steel-500 shadow-focus' : 'opacity-60',
                    )}
                  >
                    {active && <Check size={12} className="absolute top-1.5 right-1.5 text-steel-500" />}
                    <div className="font-mono text-caption text-accent-silver">{p.id}</div>
                    <div className="text-body-sm font-semibold text-steel-50 truncate">{p.name}</div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="btn-primary"
          disabled={
            runMut.isPending || symbols.length === 0 || effectiveCount === 0
          }
        >
          <Send size={14} />
          {runMut.isPending
            ? 'Running…'
            : `Run arena (${effectiveCount} × ${symbols.length})`}
        </button>
        <span className="text-caption text-text-muted">
          Each cell is a fresh LLM call · ~{effectiveCount * symbols.length * 2000} tokens
        </span>
      </div>
    </form>
  );
}

// ---------------------------------------------------------- Current verdicts grid

function CurrentVerdictsGrid({ symbols, personas, verdictMap }) {
  if (symbols.length === 0 || personas.length === 0) return null;
  return (
    <div className="card">
      <SectionHeader
        title="Current verdicts"
        subtitle="Rows = personas · Columns = symbols"
      />
      <div className="overflow-x-auto">
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-border-subtle">
              <th className="text-left h-caption py-2 pr-3">Persona</th>
              {symbols.map((s) => (
                <th key={s} className="text-left h-caption py-2 pr-3 font-mono">{s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {personas.map((p) => (
              <tr key={p.id} className="border-b border-border-subtle">
                <td className="py-3 pr-3">
                  <div className="font-mono text-caption text-accent-silver">{p.id}</div>
                  <div className="text-body-sm font-semibold text-steel-50">{p.name}</div>
                </td>
                {symbols.map((s) => {
                  const v = verdictMap.get(`${p.id}::${s}`);
                  return (
                    <td key={s} className="py-3 pr-3 align-top">
                      {v ? <VerdictCell verdict={v} /> : <span className="text-text-muted">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VerdictCell({ verdict }) {
  return (
    <details className="group">
      <summary className="cursor-pointer flex items-center gap-2 list-none">
        <span className={verdictPillClass(verdict.verdict)}>
          {(verdict.verdict || '?').toUpperCase()}
        </span>
        <span className="text-caption text-text-muted tabular">
          {(verdict.confidence || 0).toFixed(2)}
        </span>
      </summary>
      <div className="mt-2 text-caption text-steel-200 max-w-[220px] space-y-1">
        {verdict.reasoning_summary && (
          <p className="line-clamp-3">{verdict.reasoning_summary}</p>
        )}
        {verdict.action_plan && (
          <ActionPlanPreview plan={verdict.action_plan} />
        )}
      </div>
    </details>
  );
}

function ActionPlanPreview({ plan }) {
  const bits = [];
  if (plan.entry_zone_low != null && plan.entry_zone_high != null) {
    bits.push(`entry ${plan.entry_zone_low.toFixed(2)}–${plan.entry_zone_high.toFixed(2)}`);
  }
  if (plan.stop_loss != null) bits.push(`stop ${plan.stop_loss.toFixed(2)}`);
  if (plan.take_profit != null) bits.push(`tp ${plan.take_profit.toFixed(2)}`);
  if (plan.time_horizon) bits.push(plan.time_horizon);
  if (bits.length === 0) return null;
  return <div className="font-mono text-[11px] text-steel-300">{bits.join(' · ')}</div>;
}

// ---------------------------------------------------------- Scoreboard

function ScoreboardCard({ q, entries, personas }) {
  if (q.isLoading && entries.length === 0) {
    return (
      <div className="card">
        <SectionHeader title="Scoreboard" subtitle="Hypothetical P&L on past buy verdicts" />
        <LoadingState rows={3} />
      </div>
    );
  }
  if (q.isError && entries.length === 0) {
    return (
      <div className="card">
        <SectionHeader title="Scoreboard" />
        <ErrorState error={q.error} onRetry={q.refetch} />
      </div>
    );
  }
  const meaningful = entries.filter((e) => e.buy_calls > 0);
  if (meaningful.length === 0) {
    return (
      <div className="card">
        <SectionHeader title="Scoreboard" subtitle="Hypothetical P&L on past buy verdicts" />
        <EmptyState
          icon={Trophy}
          title="No track record yet"
          hint="Run the arena above. Each buy verdict becomes a measurable call once a few days pass."
        />
      </div>
    );
  }
  return (
    <div className="card">
      <SectionHeader
        title="Scoreboard"
        subtitle="Sorted by avg P&L on past buy verdicts (last 90 days)"
        action={<BarChart3 size={16} className="text-text-muted" />}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-border-subtle">
              <th className="text-left h-caption py-2 pr-3">#</th>
              <th className="text-left h-caption py-2 pr-3">Persona</th>
              <th className="text-left h-caption py-2 pr-3">Style</th>
              <th className="text-right h-caption py-2 pr-3">Buy calls</th>
              <th className="text-right h-caption py-2 pr-3">Hit rate</th>
              <th className="text-right h-caption py-2 pr-3">Avg P&L</th>
              <th className="text-left h-caption py-2 pr-3">Best</th>
              <th className="text-left h-caption py-2 pr-3">Worst</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, idx) => (
              <tr key={e.persona_id} className="border-b border-border-subtle">
                <td className="py-3 pr-3 tabular text-text-muted">{idx + 1}</td>
                <td className="py-3 pr-3">
                  <div className="font-mono text-caption text-accent-silver">{e.persona_id}</div>
                  <div className="text-body-sm font-semibold text-steel-50">
                    {e.name || personas.find((p) => p.id === e.persona_id)?.name || e.persona_id}
                  </div>
                </td>
                <td className="py-3 pr-3 text-steel-200">{e.style || '—'}</td>
                <td className="py-3 pr-3 text-right tabular">{e.buy_calls}</td>
                <td className="py-3 pr-3 text-right tabular">
                  {e.hit_rate_pct == null ? '—' : `${e.hit_rate_pct.toFixed(0)}%`}
                </td>
                <td className={classNames('py-3 pr-3 text-right tabular font-semibold', pnlTone(e.avg_buy_pnl_pct))}>
                  {fmtPct(e.avg_buy_pnl_pct)}
                </td>
                <td className="py-3 pr-3"><CallTag call={e.best_call} /></td>
                <td className="py-3 pr-3"><CallTag call={e.worst_call} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CallTag({ call }) {
  if (!call || call.symbol == null) return <span className="text-text-muted">—</span>;
  return (
    <div className="text-body-sm">
      <span className="font-mono">{call.symbol}</span>{' '}
      <span className={classNames('tabular font-semibold', pnlTone(call.pnl_pct))}>
        {fmtPct(call.pnl_pct)}
      </span>
      <div className="text-caption text-text-muted">{fmtRelativeTime(call.created_at)}</div>
    </div>
  );
}
