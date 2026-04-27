import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Sparkles, Users, History, Send, Check } from 'lucide-react';
import {
  listPersonas,
  analyzeWithPersona,
  councilAnalyze,
  listAgentHistory,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtRelativeTime, classNames } from '../lib/format.js';

const TABS = [
  { id: 'personas', label: 'Personas', icon: Sparkles },
  { id: 'council', label: 'Council', icon: Users },
  { id: 'history', label: 'History', icon: History },
];

export default function IntelligencePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState('personas');

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={5}
        title={t('intelligence.title')}
        segments={[
          { label: t('intelligence.subtitle') },
          { label: 'P7 · OPENAI', accent: true },
        ]}
        live={false}
      />

      <div className="flex items-center gap-6 border-b border-border-subtle">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={classNames(
              'h-10 -mb-px border-b-2 font-mono text-[11px] tracking-[0.15em] uppercase font-medium transition duration-150 inline-flex items-center gap-2 px-2',
              tab === t.id
                ? 'border-cyan text-cyan'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            )}
            onClick={() => setTab(t.id)}
          >
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'personas' && <SinglePersonaTab />}
      {tab === 'council' && <CouncilTab />}
      {tab === 'history' && <HistoryTab />}
    </div>
  );
}

// ---------------------------------------------------------- Persona card

function PersonaCard({ persona, selected, onSelect, compact = false }) {
  const { t } = useTranslation();
  const isOurs = persona.id === 'sentinel';
  return (
    <button
      type="button"
      onClick={() => onSelect(persona.id)}
      className={classNames(
        'card-dense text-left card-hover relative',
        selected ? 'border-steel-500 shadow-focus' : '',
        isOurs ? 'bg-social-tint/10' : ''
      )}
    >
      {selected && <Check size={14} className="absolute top-2 right-2 text-steel-500" />}
      <div className="flex items-start justify-between mb-1">
        <div className="font-mono text-caption text-accent-silver">{persona.id}</div>
        {isOurs && !compact && <span className="pill-social">{t('intelligence.ours')}</span>}
      </div>
      <div className="text-body font-semibold text-steel-50 mb-1">
        {compact ? persona.name.split(' ')[0] : persona.name}
      </div>
      {!compact && (
        <>
          <div className="text-caption text-steel-200 mb-2">{persona.style}</div>
          <p className="text-body-sm text-steel-100 line-clamp-2">{persona.description}</p>
          <div className="mt-2 flex items-center gap-1 text-caption text-steel-300 tabular">
            Social {persona.weights.social.toFixed(2)} · Fund {persona.weights.fundamentals.toFixed(2)}
          </div>
        </>
      )}
    </button>
  );
}

// ---------------------------------------------------------- Single Persona

function SinglePersonaTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const personasQ = useQuery({ queryKey: ['agent-personas'], queryFn: listPersonas });

  const [personaId, setPersonaId] = useState('buffett');
  const [symbol, setSymbol] = useState('NVDA');
  const [question, setQuestion] = useState('');

  const analyzeMut = useMutation({
    mutationFn: analyzeWithPersona,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-history'] }),
  });

  function submit(e) {
    e.preventDefault();
    if (!symbol.trim() || !personaId) return;
    analyzeMut.mutate({
      persona_id: personaId,
      symbol: symbol.trim().toUpperCase(),
      question: question.trim() || null,
    });
  }

  return (
    <div className="grid grid-cols-12 gap-6">
      <form onSubmit={submit} className="col-span-7 card space-y-5">
        <SectionHeader title={t('intelligence.pickPersona')} subtitle={t('intelligence.pickPersonaSubtitle')} />

        {personasQ.isLoading ? (
          <LoadingState rows={2} />
        ) : personasQ.isError ? (
          <ErrorState error={personasQ.error} onRetry={personasQ.refetch} />
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {(personasQ.data?.items || []).map((p) => (
              <PersonaCard
                key={p.id}
                persona={p}
                selected={personaId === p.id}
                onSelect={setPersonaId}
              />
            ))}
          </div>
        )}

        <div>
          <label className="h-caption block mb-2">{t('common.symbol')}</label>
          <input
            className="input uppercase max-w-xs"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          />
        </div>

        <div>
          <label className="h-caption block mb-2">{t('intelligence.questionOptional')}</label>
          <textarea
            className="input h-20"
            placeholder={t('intelligence.questionPlaceholder')}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>

        {analyzeMut.isError && <ApiErrorBanner error={analyzeMut.error} label={t('intelligence.analyzing')} />}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            className="btn-primary"
            disabled={analyzeMut.isPending || !symbol.trim()}
          >
            <Send size={14} /> {analyzeMut.isPending ? t('intelligence.analyzing') : t('intelligence.runAnalysis')}
          </button>
          <span className="text-caption text-text-muted">{t('intelligence.tokenHint')}</span>
        </div>
      </form>

      <div className="col-span-5">
        {analyzeMut.isPending && (
          <div className="card">
            <LoadingState rows={4} label={t('common.thinking')} />
          </div>
        )}
        {analyzeMut.data && <AnalysisResultCard analysis={analyzeMut.data} />}
        {!analyzeMut.data && !analyzeMut.isPending && (
          <div className="card">
            <EmptyState icon={Sparkles} title={t('intelligence.notRunYet')} hint={t('intelligence.notRunYetHint')} />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------- Council

function CouncilTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const personasQ = useQuery({ queryKey: ['agent-personas'], queryFn: listPersonas });

  const [selected, setSelected] = useState(['buffett', 'graham', 'sentinel']);
  const [symbol, setSymbol] = useState('NVDA');
  const [question, setQuestion] = useState('');

  const councilMut = useMutation({
    mutationFn: councilAnalyze,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-history'] }),
  });

  function togglePersona(id) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  function submit(e) {
    e.preventDefault();
    if (!symbol.trim() || selected.length === 0) return;
    councilMut.mutate({
      persona_ids: selected,
      symbol: symbol.trim().toUpperCase(),
      question: question.trim() || null,
    });
  }

  const analyses = councilMut.data?.analyses || [];
  const consensus = computeConsensus(analyses);

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="card space-y-4">
        <SectionHeader
          title={t('intelligence.councilMode')}
          subtitle={t('intelligence.councilSubtitle')}
        />

        {personasQ.isLoading ? (
          <LoadingState rows={2} />
        ) : (
          <div className="grid grid-cols-6 gap-2">
            {(personasQ.data?.items || []).map((p) => (
              <PersonaCard
                key={p.id}
                persona={p}
                selected={selected.includes(p.id)}
                onSelect={togglePersona}
                compact
              />
            ))}
          </div>
        )}

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="h-caption block mb-2">{t('common.symbol')}</label>
            <input
              className="input uppercase"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </div>
          <div className="col-span-2">
            <label className="h-caption block mb-2">{t('intelligence.questionOptional')}</label>
            <input
              className="input"
              placeholder={t('intelligence.questionPlaceholder')}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </div>
        </div>

        {councilMut.isError && <ApiErrorBanner error={councilMut.error} label={t('intelligence.councilMode')} />}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            className="btn-primary"
            disabled={councilMut.isPending || selected.length === 0}
          >
            <Users size={14} /> {councilMut.isPending ? t('common.running') : t('intelligence.summon', { count: selected.length })}
          </button>
          <span className="text-caption text-text-muted">{t('intelligence.tokenEstimate', { count: selected.length, tokens: selected.length * 2000 })}</span>
        </div>
      </form>

      {councilMut.isPending && (
        <div className="card">
          <LoadingState rows={6} label={t('intelligence.thinking')} />
        </div>
      )}

      {analyses.length > 0 && (
        <>
          {consensus && (
            <div className="card">
              <SectionHeader title={t('intelligence.consensus')} />
              <div className="grid grid-cols-3 gap-4">
                <Tile label={t('common.buy')} value={consensus.buy} color="text-profit" />
                <Tile label={t('common.hold')} value={consensus.hold} color="text-text-primary" />
                <Tile label={t('common.sell')} value={consensus.sell} color="text-loss" />
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            {analyses.map((a) => (
              <AnalysisResultCard key={a.id} analysis={a} compact />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, color }) {
  return (
    <div className="card-dense text-center">
      <div className="metric-caption">{label}</div>
      <div className={classNames('text-display font-bold tabular mt-1', color)}>{value}</div>
    </div>
  );
}

function computeConsensus(analyses) {
  if (!analyses || analyses.length === 0) return null;
  const counts = { buy: 0, hold: 0, sell: 0 };
  for (const a of analyses) counts[a.verdict] = (counts[a.verdict] || 0) + 1;
  return counts;
}

// ---------------------------------------------------------- History

function HistoryTab() {
  const { t } = useTranslation();
  const [symbolFilter, setSymbolFilter] = useState('');
  const historyQ = useQuery({
    queryKey: ['agent-history', symbolFilter],
    queryFn: () => listAgentHistory({ symbol: symbolFilter || undefined, limit: 100 }),
    refetchInterval: 30_000,
  });

  return (
    <div className="card">
      <SectionHeader title={t('intelligence.history')} subtitle={t('intelligence.historySubtitle')} />
      <div className="flex gap-3 items-end mb-4">
        <div className="max-w-xs flex-1">
          <label className="h-caption block mb-2">{t('intelligence.filterSymbol')}</label>
          <input
            className="input uppercase"
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
            placeholder="NVDA"
          />
        </div>
      </div>
      <HistoryList q={historyQ} t={t} />
    </div>
  );
}

function HistoryList({ q, t }) {
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0)
    return <EmptyState icon={History} title={t('intelligence.noHistory')} hint={t('intelligence.noHistoryHint')} />;

  return (
    <div className="space-y-3">
      {items.map((a) => (
        <details key={a.id} className="card-dense">
          <summary className="cursor-pointer flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span className="font-mono text-caption text-accent-silver">{a.persona_id}</span>
              <span className="font-medium text-steel-50">{a.symbol}</span>
              <VerdictPill verdict={a.verdict} confidence={a.confidence} />
              <span className="text-body-sm text-steel-200 truncate">{a.reasoning_summary}</span>
            </div>
            <span className="text-caption text-steel-300 shrink-0">{fmtRelativeTime(a.created_at)}</span>
          </summary>
          <div className="mt-3 pl-3 border-l-2 border-steel-400">
            <AnalysisDetail a={a} />
          </div>
        </details>
      ))}
    </div>
  );
}

// ---------------------------------------------------------- Result card

function AnalysisResultCard({ analysis, compact = false }) {
  const { t } = useTranslation();
  return (
    <div className="card">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-mono text-caption text-accent-silver mb-0.5">{analysis.persona_id}</div>
          <div className="h-section text-h2">{analysis.symbol}</div>
        </div>
        <VerdictPill verdict={analysis.verdict} confidence={analysis.confidence} />
      </div>
      <p className="text-body text-steel-100 leading-relaxed mb-4">{analysis.reasoning_summary}</p>
      <AnalysisDetail a={analysis} compact={compact} />
      <div className="text-caption text-text-muted mt-3">
        {fmtRelativeTime(analysis.created_at)} · {analysis.model || '—'}
      </div>
    </div>
  );
}

function AnalysisDetail({ a, compact = false }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      {a.key_factors?.length > 0 && (
        <div>
          <div className="h-caption mb-2">{t('intelligence.keyFactors')}</div>
          <ul className="space-y-1.5">
            {a.key_factors.map((kf, i) => (
              <li key={i} className="flex items-start gap-2 text-body-sm">
                <span
                  className={classNames(
                    'shrink-0 mt-0.5',
                    kf.signal === 'social' ? 'pill-social' :
                    kf.signal === 'fundamentals' ? 'pill-cyan' :
                    kf.signal === 'technical' ? 'pill-warn' : 'pill-default'
                  )}
                >{kf.signal}</span>
                <span className="text-text-primary">{kf.interpretation}</span>
                <span className="ml-auto text-caption text-text-muted tabular shrink-0">
                  w={(kf.weight || 0).toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!compact && a.follow_up_questions?.length > 0 && (
        <div>
          <div className="h-caption mb-2">{t('intelligence.followUp')}</div>
          <ul className="list-disc list-inside text-body-sm text-text-primary space-y-1">
            {a.follow_up_questions.map((q, i) => <li key={i}>{q}</li>)}
          </ul>
        </div>
      )}

      {a.question && (
        <div className="text-caption text-text-muted italic">{t('intelligence.userQuestion')}: {a.question}</div>
      )}
    </div>
  );
}

function VerdictPill({ verdict, confidence }) {
  const { t } = useTranslation();
  const cls = verdict === 'buy' ? 'pill-bull' : verdict === 'sell' ? 'pill-bear' : 'pill-default';
  return (
    <div className="text-right shrink-0">
      <span className={cls}>{verdict?.toUpperCase()}</span>
      <div className="text-caption text-text-muted mt-1 tabular">{t('intelligence.confidence')} {(confidence || 0).toFixed(2)}</div>
    </div>
  );
}
