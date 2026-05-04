// JournalPage — daily investment notes (Task 4 of the journal feature).
//
// Backend shapes (see `backend/app/models/journal.py`):
//   GET    /api/journal           -> { items: JournalEntryView[], total, limit, offset }
//   POST   /api/journal           -> JournalEntryView
//   PATCH  /api/journal/{id}      -> JournalEntryView
//   DELETE /api/journal/{id}      -> { removed: true }
//   GET    /api/journal/symbols/autocomplete?prefix= -> { symbols: string[] }
//
// JournalEntryView = { id, title, body, symbols[], mood, created_at, updated_at }
// mood ∈ {"bullish","bearish","neutral","watching"}
//
// Layout matches MacroPage's Tokyo-cyber theme (PageHeader + card sections,
// neon-cyan accents, JetBrains Mono for the date/numerics). The editor is an
// inline modal at the bottom of this file — same pattern as
// ThresholdEditModal in MacroPage.jsx.
import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Plus, Pencil, Trash2, X as XIcon, Save } from 'lucide-react';
import {
  listJournal,
  createJournalEntry,
  updateJournalEntry,
  deleteJournalEntry,
  autocompleteJournalSymbols,
} from '../lib/api.js';
import {
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { classNames, fmtRelativeTime } from '../lib/format.js';

const MOODS = ['bullish', 'bearish', 'neutral', 'watching'];

function moodPillClass(mood) {
  // Mapping defined in the task spec — mood pill colors.
  return (
    {
      bullish: 'pill-bull',
      bearish: 'pill-bear',
      neutral: 'pill-default',
      watching: 'pill-cyan',
    }[mood] || 'pill-default'
  );
}

// Robust comma-split: trims tokens, drops empties, dedupes (case-insensitive,
// preserves the first-seen casing). Backend dedupes too, but we mirror the UX.
function parseSymbols(raw) {
  const seen = new Set();
  const out = [];
  for (const tok of String(raw || '').split(',')) {
    const trimmed = tok.trim();
    if (!trimmed) continue;
    const key = trimmed.toUpperCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed.toUpperCase());
  }
  return out;
}

export default function JournalPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // Filter state — bound to the toolbar inputs.
  const [search, setSearch] = useState('');
  const [symbol, setSymbol] = useState('');
  const [mood, setMood] = useState('');

  // Editor state — `editing` is null (closed), 'new' (creating), or an
  // entry object (editing).
  const [editing, setEditing] = useState(null);

  const filters = { search: search.trim() || undefined, symbol: symbol.trim() || undefined, mood: mood || undefined };

  const journalQ = useQuery({
    queryKey: ['journal', filters],
    queryFn: () => listJournal(filters),
    retry: false,
  });

  const deleteMut = useMutation({
    mutationFn: (id) => deleteJournalEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['journal'] }),
  });

  const items = journalQ.data?.items || [];
  const total = journalQ.data?.total ?? 0;

  function onDelete(entry) {
    // Native confirm — task spec calls this out explicitly.
    if (!window.confirm(t('journal.actions.deleteConfirm'))) return;
    deleteMut.mutate(entry.id);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={8}
        title={t('journal.title')}
        segments={[{ label: t('journal.subtitle') }]}
      />

      {/* Toolbar — search / filters / new */}
      <div className="card space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3">
          <div className="md:col-span-5">
            <input
              type="text"
              className="input"
              placeholder={t('journal.searchPlaceholder')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="md:col-span-3">
            <input
              type="text"
              className="input"
              placeholder={t('journal.symbolFilter')}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </div>
          <div className="md:col-span-2">
            <select
              className="select"
              value={mood}
              onChange={(e) => setMood(e.target.value)}
            >
              <option value="">{t('journal.anyMood')}</option>
              {MOODS.map((m) => (
                <option key={m} value={m}>
                  {t(`journal.moods.${m}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="md:col-span-2 flex justify-end">
            <button
              className="btn-primary btn-sm w-full md:w-auto"
              onClick={() => setEditing('new')}
            >
              <Plus size={12} /> {t('journal.newEntry')}
            </button>
          </div>
        </div>
        {(symbol || mood || search) && (
          <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase">
            {total} {t('journal.entriesCount')}
          </div>
        )}
      </div>

      {/* List */}
      {journalQ.isLoading ? (
        <LoadingState rows={4} />
      ) : journalQ.isError ? (
        <ErrorState error={journalQ.error} onRetry={journalQ.refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t('journal.empty')}
          hint={t('journal.emptyHint')}
        />
      ) : (
        <div className="space-y-3">
          {items.map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              t={t}
              onEdit={() => setEditing(entry)}
              onDelete={() => onDelete(entry)}
              onSymbolClick={(sym) => setSymbol(sym)}
            />
          ))}
        </div>
      )}

      {editing && (
        <EntryEditorModal
          mode={editing === 'new' ? 'create' : 'edit'}
          initial={editing === 'new' ? null : editing}
          t={t}
          onClose={() => setEditing(null)}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: ['journal'] });
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

/* ---------------------------------------------------------- Entry list card */

function EntryCard({ entry, t, onEdit, onDelete, onSymbolClick }) {
  // First-200-chars preview — strip leading whitespace per line for a cleaner
  // truncation, but keep newlines so multi-paragraph notes render naturally.
  const preview = (entry.body || '').slice(0, 200);
  const truncated = (entry.body || '').length > 200;

  return (
    <div className="card-dense relative group hover:border-border-accent transition duration-150">
      <div className="flex items-start gap-4">
        <div className="font-mono text-[11px] text-text-muted tracking-[0.1em] whitespace-nowrap pt-0.5">
          {fmtRelativeTime(entry.created_at)}
        </div>
        <span className={moodPillClass(entry.mood)}>{t(`journal.moods.${entry.mood}`)}</span>
        <h3 className="h-section flex-1 truncate">{entry.title}</h3>
        <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition duration-150">
          <button
            onClick={onEdit}
            className="text-text-muted hover:text-cyan"
            title={t('journal.actions.edit')}
            aria-label={t('journal.actions.edit')}
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={onDelete}
            className="text-text-muted hover:text-loss"
            title={t('journal.actions.delete')}
            aria-label={t('journal.actions.delete')}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {preview && (
        <div className="text-body-sm text-text-secondary leading-relaxed whitespace-pre-wrap mt-3 pl-0 break-words">
          {preview}
          {truncated && <span className="text-text-muted">…</span>}
        </div>
      )}

      {entry.symbols && entry.symbols.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {entry.symbols.map((sym) => (
            <button
              key={sym}
              onClick={() => onSymbolClick(sym)}
              className="pill-default hover:text-cyan hover:border-cyan transition duration-150 cursor-pointer"
              title={sym}
            >
              {sym}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- Editor modal */

function EntryEditorModal({ mode, initial, t, onClose, onSaved }) {
  const [title, setTitle] = useState(initial?.title || '');
  const [body, setBody] = useState(initial?.body || '');
  const [symbolsRaw, setSymbolsRaw] = useState((initial?.symbols || []).join(', '));
  const [mood, setMood] = useState(initial?.mood || 'neutral');
  const [validationError, setValidationError] = useState(null);

  // Symbol autocomplete: query the API on the *last token* whenever the user
  // has typed at least one char into it. We only call when prefix is
  // non-empty so we don't spam the backend.
  const lastToken = useMemo(() => {
    const parts = symbolsRaw.split(',');
    return (parts[parts.length - 1] || '').trim();
  }, [symbolsRaw]);
  const [autocompleteOpen, setAutocompleteOpen] = useState(false);
  const acQ = useQuery({
    queryKey: ['journal', 'autocomplete', lastToken],
    queryFn: () => autocompleteJournalSymbols(lastToken, 8),
    enabled: lastToken.length >= 1,
    retry: false,
    staleTime: 30_000,
  });

  const saveMut = useMutation({
    mutationFn: () => {
      const symbols = parseSymbols(symbolsRaw);
      if (mode === 'create') {
        return createJournalEntry({ title: title.trim(), body, symbols, mood });
      }
      // PATCH: only send fields that actually changed vs the loaded entry.
      const patch = {};
      if (title.trim() !== (initial.title || '')) patch.title = title.trim();
      if (body !== (initial.body || '')) patch.body = body;
      // For symbols/mood we compare canonical forms.
      const initSyms = (initial.symbols || []).slice().sort().join(',');
      const newSyms = symbols.slice().sort().join(',');
      if (initSyms !== newSyms) patch.symbols = symbols;
      if (mood !== initial.mood) patch.mood = mood;
      return updateJournalEntry(initial.id, patch);
    },
    onSuccess: onSaved,
  });

  // Esc has historically been left to the click-outside-overlay; matching
  // ThresholdEditModal which also relies only on the overlay click.

  function onSubmit(e) {
    e.preventDefault();
    if (!title.trim()) {
      setValidationError(t('journal.validation.titleRequired'));
      return;
    }
    setValidationError(null);
    saveMut.mutate();
  }

  function pickSuggestion(sym) {
    // Replace the last token with the chosen symbol + a trailing comma so the
    // user can keep typing the next one.
    const parts = symbolsRaw.split(',');
    parts[parts.length - 1] = ` ${sym}`;
    setSymbolsRaw(parts.join(',') + ', ');
    setAutocompleteOpen(false);
  }

  // Keep the dropdown closed once the user types past the last suggestion.
  useEffect(() => {
    if (lastToken.length >= 1) setAutocompleteOpen(true);
    else setAutocompleteOpen(false);
  }, [lastToken]);

  const suggestions = (acQ.data?.symbols || []).filter(
    (s) => s.toUpperCase() !== lastToken.toUpperCase(),
  );

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center px-4 py-8 overflow-y-auto"
      onClick={onClose}
    >
      <form
        className="bg-surface border border-border-subtle max-w-2xl w-full p-6"
        onClick={(e) => e.stopPropagation()}
        onSubmit={onSubmit}
      >
        <div className="flex items-start justify-between mb-5">
          <div>
            <div className="font-mono text-[10px] text-text-muted tracking-[0.2em] uppercase mb-1">
              {mode === 'create' ? 'NEW' : `#${initial.id}`}
            </div>
            <h3 className="h-section">
              {mode === 'create' ? t('journal.newEntry') : t('journal.actions.edit')}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary"
            aria-label={t('journal.actions.cancel')}
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="space-y-4">
          {/* Title */}
          <div>
            <label className="h-caption block mb-1">{t('journal.fields.title')}</label>
            <input
              type="text"
              className={classNames('input', validationError && 'input-error')}
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (validationError) setValidationError(null);
              }}
              autoFocus
            />
            {validationError && (
              <div className="text-caption text-loss mt-1">{validationError}</div>
            )}
          </div>

          {/* Body */}
          <div>
            <label className="h-caption block mb-1">{t('journal.fields.body')}</label>
            <textarea
              rows={10}
              className="input font-mono"
              style={{ height: 'auto', minHeight: '220px', paddingTop: '8px', paddingBottom: '8px' }}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>

          {/* Symbols + autocomplete */}
          <div className="relative">
            <label className="h-caption block mb-1">{t('journal.fields.symbols')}</label>
            <input
              type="text"
              className="input"
              value={symbolsRaw}
              onChange={(e) => setSymbolsRaw(e.target.value)}
              onFocus={() => lastToken.length >= 1 && setAutocompleteOpen(true)}
              onBlur={() => setTimeout(() => setAutocompleteOpen(false), 150)}
              placeholder="NVDA, AAPL, SPY"
            />
            {autocompleteOpen && suggestions.length > 0 && (
              <div className="absolute z-10 left-0 right-0 mt-1 bg-surface border border-border-subtle max-h-48 overflow-y-auto">
                {suggestions.map((sym) => (
                  <button
                    type="button"
                    key={sym}
                    onMouseDown={(e) => {
                      // onMouseDown so it fires before the input's onBlur.
                      e.preventDefault();
                      pickSuggestion(sym);
                    }}
                    className="w-full text-left px-3 py-1.5 font-mono text-[12px] text-text-secondary hover:bg-elevated hover:text-cyan transition duration-150"
                  >
                    {sym}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Mood */}
          <div>
            <label className="h-caption block mb-1">{t('journal.fields.mood')}</label>
            <div className="flex flex-wrap gap-2">
              {MOODS.map((m) => {
                const active = mood === m;
                return (
                  <button
                    type="button"
                    key={m}
                    onClick={() => setMood(m)}
                    className={classNames(
                      'inline-flex items-center h-8 px-3 font-mono text-[11px] tracking-[0.15em] uppercase border transition duration-150',
                      active
                        ? m === 'bullish'
                          ? 'border-profit text-profit bg-profit/10'
                          : m === 'bearish'
                            ? 'border-loss text-loss bg-loss/10'
                            : m === 'watching'
                              ? 'border-cyan text-cyan bg-cyan/10'
                              : 'border-text-secondary text-text-primary bg-elevated'
                        : 'border-border-subtle text-text-muted hover:border-border-accent hover:text-text-secondary',
                    )}
                  >
                    {t(`journal.moods.${m}`)}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 mt-6 pt-4 border-t border-border-subtle">
          <button type="button" className="btn-ghost btn-sm" onClick={onClose}>
            {t('journal.actions.cancel')}
          </button>
          <button
            type="submit"
            className="btn-primary btn-sm"
            disabled={saveMut.isPending}
          >
            <Save size={12} /> {t('journal.actions.save')}
          </button>
        </div>

        {saveMut.isError && (
          <div className="text-caption text-loss mt-3 break-all">
            {String(saveMut.error?.detail || saveMut.error?.message || saveMut.error)}
          </div>
        )}
      </form>
    </div>
  );
}
