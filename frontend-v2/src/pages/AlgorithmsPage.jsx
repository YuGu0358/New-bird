import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Power, Trash2, GitBranch, BookOpen, Sparkles, Upload, Code2, Play, Save, X, Eye } from 'lucide-react';
import {
  listStrategies,
  listRegisteredStrategies,
  activateStrategy,
  deleteStrategy,
  analyzeStrategy,
  analyzeStrategyUpload,
  analyzeFactorCode,
  analyzeFactorUpload,
  observeMarket,
  previewStrategy,
  saveStrategy,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { fmtRelativeTime, classNames } from '../lib/format.js';

export default function AlgorithmsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const registeredQ = useQuery({ queryKey: ['registered-strategies'], queryFn: listRegisteredStrategies });
  const libraryQ = useQuery({ queryKey: ['strategies'], queryFn: listStrategies, refetchInterval: 30_000 });

  const activateMut = useMutation({
    mutationFn: activateStrategy,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  });
  const deleteMut = useMutation({
    mutationFn: deleteStrategy,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  });

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={7}
        title={t('algorithms.title')}
        segments={[
          { label: t('algorithms.subtitle') },
          { label: 'P2 · FRAMEWORK', accent: true },
        ]}
        live={false}
      />

      <GenerateStrategyCard
        onSaved={() => queryClient.invalidateQueries({ queryKey: ['strategies'] })}
      />

      {/* Registered strategy types (P2 framework) */}
      <div className="card">
        <SectionHeader
          title={t('algorithms.registeredTitle')}
          subtitle={t('algorithms.registeredSubtitle')}
        />
        <RegisteredGrid q={registeredQ} t={t} />
      </div>

      {/* User strategy library */}
      <div className="card">
        <SectionHeader
          title={t('algorithms.myLibrary')}
          subtitle={t('algorithms.myLibrarySubtitle', {
            count: libraryQ.data?.items?.length ?? 0,
            max: libraryQ.data?.max_slots ?? 5,
          })}
        />
        <StrategyLibrary
          q={libraryQ}
          t={t}
          onActivate={(id) => activateMut.mutate(id)}
          onDelete={(id) => deleteMut.mutate(id)}
          activating={activateMut.isPending}
          deleting={deleteMut.isPending}
        />
        <p className="text-caption text-text-muted mt-4">{t('algorithms.uploadHint')}</p>
      </div>
    </div>
  );
}

function RegisteredGrid({ q, t }) {
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={BookOpen} title={t('algorithms.registryEmpty')} />;

  return (
    <div className="grid grid-cols-2 gap-4">
      {items.map((s) => (
        <div key={s.name} className="card-dense card-hover">
          <div className="flex items-start justify-between mb-2">
            <div>
              <div className="font-mono text-body-sm text-accent-silver">{s.name}</div>
              <div className="h-section text-h2 mt-0.5">{(s.description || '').split('.')[0] || s.name}</div>
            </div>
            <span className="pill-active">registered</span>
          </div>
          <p className="text-body-sm text-steel-100 leading-relaxed mb-3">{s.description}</p>
          <details className="text-caption">
            <summary className="cursor-pointer text-text-secondary hover:text-text-primary">{t('algorithms.schemaToggle')}</summary>
            <pre className="mt-2 p-3 bg-void border border-border-subtle font-mono text-[11px] text-text-secondary overflow-auto max-h-48">
              {JSON.stringify(extractProperties(s.parameters_schema), null, 2)}
            </pre>
          </details>
        </div>
      ))}
    </div>
  );
}

function extractProperties(schema) {
  if (!schema || typeof schema !== 'object') return {};
  return schema.properties || schema;
}

// ---------------------------------------------------------------------------
// Generate Strategy card — natural-language / file / factor-code → draft → preview
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'describe', label: 'Describe',    icon: Sparkles },
  { id: 'upload',   label: 'Upload',      icon: Upload },
  { id: 'factor',   label: 'Factor code', icon: Code2 },
  { id: 'observe',  label: 'Observe market', icon: Eye },
];

/** @param {{ onSaved: () => void }} props */
function GenerateStrategyCard({ onSaved }) {
  const [tab, setTab] = useState('describe');
  const [draft, setDraft] = useState(/** @type {any} */ (null));
  const [preview, setPreview] = useState(/** @type {any} */ (null));
  const [editName, setEditName] = useState('');

  function setDraftFromResponse(d) {
    setDraft(d);
    setEditName(d?.suggested_name ?? '');
    setPreview(null);
  }

  // Three analyze mutations — one per tab — all land in the same draft state.
  const analyzeText = useMutation({
    mutationFn: (description) => analyzeStrategy({ description }),
    onSuccess: setDraftFromResponse,
  });
  const analyzeFiles = useMutation({
    mutationFn: (files) => analyzeStrategyUpload(files),
    onSuccess: setDraftFromResponse,
  });
  const analyzeCode = useMutation({
    mutationFn: (body) => analyzeFactorCode(body),
    onSuccess: setDraftFromResponse,
  });
  const analyzeObserve = useMutation({
    mutationFn: (symbols) => observeMarket(symbols),
    onSuccess: setDraftFromResponse,
  });

  const previewMut = useMutation({
    mutationFn: () => previewStrategy({
      normalized_strategy: draft.normalized_strategy,
      parameters: draft.parameters,
    }),
    onSuccess: setPreview,
  });

  const saveMut = useMutation({
    mutationFn: (activate) => saveStrategy({
      name: editName || draft.suggested_name,
      original_description: draft.original_description,
      normalized_strategy: draft.normalized_strategy,
      improvement_points: draft.improvement_points,
      risk_warnings: draft.risk_warnings,
      execution_notes: draft.execution_notes,
      parameters: draft.parameters,
      activate,
    }),
    onSuccess: async () => {
      // Clear draft so the user sees a fresh slate after a save.
      setDraft(null);
      setPreview(null);
      setEditName('');
      onSaved();
    },
  });

  const anyAnalyzing = analyzeText.isPending || analyzeFiles.isPending
    || analyzeCode.isPending || analyzeObserve.isPending;
  const anyError = analyzeText.error || analyzeFiles.error || analyzeCode.error
    || analyzeObserve.error || previewMut.error || saveMut.error;

  return (
    <div className="card">
      <SectionHeader
        title="GENERATE STRATEGY"
        subtitle="OpenAI 解析 → normalized 参数 → 试跑 / 保存"
        meta={<Sparkles size={14} className="text-cyan" />}
      />

      {/* Tab pills */}
      <div className="flex gap-2 mb-4">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={
              'inline-flex items-center gap-2 px-3 py-1.5 border font-mono text-[11px] tracking-[0.15em] uppercase ' +
              (id === tab
                ? 'border-cyan text-cyan bg-cyan/10'
                : 'border-border-subtle text-text-secondary hover:text-text-primary')
            }
          >
            <Icon size={12} /> {label}
          </button>
        ))}
      </div>

      {/* Tab body */}
      {tab === 'describe' && (
        <DescribeForm
          onSubmit={(text) => analyzeText.mutate(text)}
          pending={analyzeText.isPending}
        />
      )}
      {tab === 'upload' && (
        <UploadForm
          onSubmit={(files) => analyzeFiles.mutate(files)}
          pending={analyzeFiles.isPending}
        />
      )}
      {tab === 'factor' && (
        <FactorCodeForm
          onSubmit={(body) => analyzeCode.mutate(body)}
          pending={analyzeCode.isPending}
        />
      )}
      {tab === 'observe' && (
        <ObserveMarketForm
          onSubmit={(symbols) => analyzeObserve.mutate(symbols)}
          pending={analyzeObserve.isPending}
        />
      )}

      {anyAnalyzing && <div className="mt-4"><LoadingState rows={3} label="AI 解析中…" /></div>}
      {anyError && <div className="mt-4"><ErrorState error={anyError} /></div>}

      {/* Draft preview */}
      {draft && !anyAnalyzing && (
        <DraftPanel
          draft={draft}
          editName={editName}
          onEditName={setEditName}
          onPreview={() => previewMut.mutate()}
          previewPending={previewMut.isPending}
          onSave={(activate) => {
            try { saveMut.mutate(activate); } catch { /* surfaced via saveMut.isError */ }
          }}
          savePending={saveMut.isPending}
          onDiscard={() => { setDraft(null); setPreview(null); }}
        />
      )}

      {preview && <PreviewPanel preview={preview} />}
    </div>
  );
}

function DescribeForm({ onSubmit, pending }) {
  const [text, setText] = useState('');
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (text.trim()) onSubmit(text.trim()); }}
      className="space-y-3"
    >
      <textarea
        className="input min-h-[120px] font-mono text-body-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Buy NVDA when RSI < 30 and price drops 2% in a day, sell when up 8% or after 30 days. Max $1000 per entry."
      />
      <div className="flex justify-end">
        <button type="submit" className="btn-primary btn-sm inline-flex items-center gap-2"
          disabled={!text.trim() || pending}>
          <Sparkles size={12} /> AI 解析
        </button>
      </div>
    </form>
  );
}

function UploadForm({ onSubmit, pending }) {
  const [file, setFile] = useState(/** @type {File|null} */ (null));
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (file) onSubmit([file]); }}
      className="space-y-3"
    >
      <input
        type="file"
        accept=".txt,.md,.pdf,.docx"
        className="input"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <div className="flex justify-between items-center">
        <span className="text-caption text-text-muted">
          {file ? `${file.name} · ${Math.ceil(file.size / 1024)} KB` : 'No file selected'}
        </span>
        <button type="submit" className="btn-primary btn-sm inline-flex items-center gap-2"
          disabled={!file || pending}>
          <Upload size={12} /> Generate
        </button>
      </div>
    </form>
  );
}

function ObserveMarketForm({ onSubmit, pending }) {
  const [text, setText] = useState('SPY, QQQ, NVDA, AAPL, MSFT');
  function commit(e) {
    e.preventDefault();
    const symbols = text
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter((s) => /^[A-Z]{1,6}$/.test(s));
    if (symbols.length > 0) onSubmit(symbols);
  }
  return (
    <form onSubmit={commit} className="space-y-3">
      <textarea
        className="input min-h-[80px] font-mono uppercase"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="SPY, QQQ, NVDA, AAPL, MSFT — comma or space separated, up to 8 symbols"
      />
      <div className="flex justify-between items-center">
        <span className="text-caption text-text-muted">
          LLM 会读取每个 symbol 的成交量 / 技术指标 / 期权 flow / 行业相对强度，给出适合当前市场状态的策略参数。
        </span>
        <button type="submit" className="btn-primary btn-sm inline-flex items-center gap-2"
          disabled={!text.trim() || pending}>
          <Eye size={12} /> Observe
        </button>
      </div>
    </form>
  );
}

function FactorCodeForm({ onSubmit, pending }) {
  const [code, setCode] = useState('');
  const [description, setDescription] = useState('');
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (code.trim()) onSubmit({ code, description, source_name: 'pasted-factor.py' });
      }}
      className="space-y-3"
    >
      <textarea
        className="input min-h-[160px] font-mono text-[11px]"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="# Paste a QuantBrain-style factor function or class&#10;def my_factor(close, volume):&#10;    ..."
      />
      <input
        type="text"
        className="input"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Optional notes on intent / risk profile"
      />
      <div className="flex justify-end">
        <button type="submit" className="btn-primary btn-sm inline-flex items-center gap-2"
          disabled={!code.trim() || pending}>
          <Code2 size={12} /> Analyze
        </button>
      </div>
    </form>
  );
}

function DraftPanel({ draft, editName, onEditName, onPreview, previewPending, onSave, savePending, onDiscard }) {
  return (
    <div className="mt-6 border-t border-border-subtle pt-6 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[240px]">
          <FieldLabel>Strategy name</FieldLabel>
          <input className="input" value={editName} onChange={(e) => onEditName(e.target.value)} />
        </div>
        <span className={'pill-' + (draft.used_openai ? 'cyan' : 'default')}>
          {draft.used_openai ? 'AI-generated' : 'Deterministic fallback'}
        </span>
      </div>

      <div>
        <FieldLabel>Normalized strategy</FieldLabel>
        <pre className="p-3 bg-void border border-border-subtle font-mono text-[11px] text-text-secondary whitespace-pre-wrap">
          {draft.normalized_strategy}
        </pre>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <BulletList title="Improvements" tone="bull" items={draft.improvement_points} />
        <BulletList title="Risk warnings" tone="bear" items={draft.risk_warnings} />
        <BulletList title="Execution notes" tone="neutral" items={draft.execution_notes} />
      </div>

      <div>
        <FieldLabel>Parameters</FieldLabel>
        <ParamsTable params={draft.parameters} />
      </div>

      {draft.factor_analysis && draft.factor_analysis.factor_names?.length > 0 && (
        <div className="text-caption text-text-secondary">
          Factor mode: {draft.factor_analysis.factor_names.join(', ')}
        </div>
      )}

      <div className="flex flex-wrap gap-2 items-center pt-2">
        <button className="btn-secondary btn-sm inline-flex items-center gap-2"
          onClick={onPreview} disabled={previewPending}>
          <Play size={12} /> Preview run
        </button>
        <button className="btn-primary btn-sm inline-flex items-center gap-2"
          onClick={() => onSave(false)} disabled={savePending || !editName.trim()}>
          <Save size={12} /> Save
        </button>
        <button className="btn-primary btn-sm inline-flex items-center gap-2"
          onClick={() => onSave(true)} disabled={savePending || !editName.trim()}>
          <Power size={12} /> Save & activate
        </button>
        <button className="btn-ghost btn-sm inline-flex items-center gap-2 ml-auto"
          onClick={onDiscard} disabled={savePending}>
          <X size={12} /> Discard
        </button>
      </div>
    </div>
  );
}

function PreviewPanel({ preview }) {
  return (
    <div className="mt-4 border border-cyan/40 bg-cyan/5 p-4 space-y-3">
      <div className="font-mono text-[11px] tracking-[0.15em] uppercase text-cyan">Preview run</div>
      <div className="text-body-sm">
        {preview.likely_trade_symbols?.length ?? 0} candidates from {preview.universe_size} symbols
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-caption">
        <div><b>Entry</b>: {preview.entry_trigger_summary}</div>
        <div><b>Add-on</b>: {preview.add_on_summary}</div>
        <div><b>Exit</b>: {preview.exit_summary}</div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-caption text-text-secondary">
        <div>max new/day: {preview.max_new_positions_per_day}</div>
        <div>max capital/sym: {preview.max_capital_per_symbol}</div>
        <div>max new $/day: {preview.max_new_capital_per_day}</div>
        <div>max total $: {preview.max_total_capital_if_fully_scaled}</div>
      </div>
      {preview.likely_trade_candidates?.length > 0 && (
        <table className="tbl text-[11px]">
          <thead>
            <tr><th>Symbol</th><th className="tbl-num">Score</th><th>Note</th><th className="tbl-num">1d %</th></tr>
          </thead>
          <tbody>
            {preview.likely_trade_candidates.slice(0, 8).map((c) => (
              <tr key={c.symbol}>
                <td>{c.symbol}</td>
                <td className="tbl-num">{c.score?.toFixed?.(2) ?? c.score}</td>
                <td className="text-text-secondary">{c.note}</td>
                <td className="tbl-num">{c.day_change_percent != null ? c.day_change_percent.toFixed(2) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {preview.restart_required && (
        <div className="text-caption text-bear">⚠ Activating this strategy requires a bot restart.</div>
      )}
    </div>
  );
}

function FieldLabel({ children }) {
  return <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-2">{children}</div>;
}

function BulletList({ title, tone, items }) {
  if (!items?.length) return null;
  const toneClass = tone === 'bull' ? 'text-bull' : tone === 'bear' ? 'text-bear' : 'text-text-secondary';
  return (
    <div>
      <FieldLabel>{title}</FieldLabel>
      <ul className="space-y-1 text-caption">
        {items.map((it, i) => (
          <li key={i} className={classNames('leading-relaxed', toneClass)}>· {it}</li>
        ))}
      </ul>
    </div>
  );
}

function ParamsTable({ params }) {
  if (!params) return null;
  const rows = Object.entries(params);
  return (
    <table className="tbl text-[11px]">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="font-mono text-text-secondary w-1/3">{k}</td>
            <td className="text-text-primary">
              {Array.isArray(v) ? (v.length === 0 ? '—' : v.join(', ')) : String(v)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StrategyLibrary({ q, t, onActivate, onDelete, activating, deleting }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={GitBranch} title={t('algorithms.libraryEmpty')} hint={t('algorithms.libraryEmptyHint')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{t('common.name')}</th>
          <th>{t('common.description')}</th>
          <th>{t('common.status')}</th>
          <th>{t('common.time')}</th>
          <th className="text-right">{t('common.actions')}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((s) => (
          <tr key={s.id}>
            <td className="font-medium text-text-primary">{s.name}</td>
            <td className="text-text-secondary max-w-md truncate">{s.normalized_strategy || s.raw_description}</td>
            <td>
              {s.is_active ? <span className="pill-cyan">{t('algorithms.active')}</span> : <span className="pill-default">{t('algorithms.idle')}</span>}
            </td>
            <td className="text-caption text-text-secondary">{fmtRelativeTime(s.updated_at)}</td>
            <td className="text-right">
              <div className="inline-flex gap-2">
                {!s.is_active && (
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => onActivate(s.id)}
                    disabled={activating}
                    title={t('algorithms.activate')}
                  >
                    <Power size={12} /> {t('algorithms.activate')}
                  </button>
                )}
                <button
                  className={classNames('btn-sm', s.is_active ? 'btn-ghost' : 'btn-destructive')}
                  onClick={() => {
                    if (confirm(t('algorithms.removeConfirm', { name: s.name }))) onDelete(s.id);
                  }}
                  disabled={deleting || s.is_active}
                  title={s.is_active ? t('algorithms.activeCannotDelete') : t('algorithms.remove')}
                >
                  <Trash2 size={12} /> {t('algorithms.remove')}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
