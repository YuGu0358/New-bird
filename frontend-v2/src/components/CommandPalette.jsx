// Global command palette (Cmd/Ctrl+K).
//
// Backed by the `cmdk` library so we get fuzzy search, keyboard nav, and
// composable primitives for free. The visible label and grouping come from
// our own registry (lib/commandRegistry.js), keyed against i18n.
import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Command } from 'cmdk';
import {
  ACTIONS,
  PAGES,
  loadRecent,
  pushRecent,
} from '../lib/commandRegistry.js';

export default function CommandPalette({ open, onOpenChange }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [recent, setRecent] = useState(() => loadRecent());

  useEffect(() => {
    if (!open) setSearch('');
    else setRecent(loadRecent());
  }, [open]);

  const ctx = useMemo(() => ({ i18n, queryClient, navigate }), [i18n, queryClient, navigate]);

  function close() {
    onOpenChange(false);
  }

  function runPage(page) {
    pushRecent(page.id);
    navigate(page.to);
    close();
  }

  function runAction(action) {
    pushRecent(`action:${action.id}`);
    Promise.resolve(action.run(ctx)).finally(close);
  }

  // Resolve recent items back into entries; entries that no longer exist
  // are silently dropped.
  const recentEntries = recent
    .map((key) => {
      if (key.startsWith('action:')) {
        const id = key.slice('action:'.length);
        const a = ACTIONS.find((x) => x.id === id);
        return a ? { kind: 'action', entry: a } : null;
      }
      const p = PAGES.find((x) => x.id === key);
      return p ? { kind: 'page', entry: p } : null;
    })
    .filter(Boolean);

  if (!open) return null;

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label={t('cmdk.dialogLabel')}
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        // Click outside the dialog body closes the palette
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="w-full max-w-xl bg-surface border border-border-subtle shadow-2xl">
        <Command shouldFilter={true} loop>
          <div className="border-b border-border-subtle px-4 py-3">
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder={t('cmdk.placeholder')}
              autoFocus
              className="w-full bg-transparent outline-none text-text-primary placeholder:text-text-muted text-body"
            />
          </div>

          <Command.List className="max-h-[50vh] overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-body-sm text-text-muted">
              {t('cmdk.empty')}
            </Command.Empty>

            {recentEntries.length > 0 && search === '' && (
              <Command.Group
                heading={
                  <span className="font-mono text-[10px] tracking-[0.2em] text-text-muted uppercase px-2">
                    {t('cmdk.groups.recent')}
                  </span>
                }
              >
                {recentEntries.map(({ kind, entry }) => {
                  const Icon = entry.icon;
                  const value = kind === 'page' ? `recent:${entry.id}` : `recent-action:${entry.id}`;
                  const label =
                    kind === 'page'
                      ? t(entry.navKey)
                      : t(`cmdk.actions.${entry.id}`);
                  return (
                    <Command.Item
                      key={value}
                      value={value}
                      onSelect={() =>
                        kind === 'page' ? runPage(entry) : runAction(entry)
                      }
                      className="flex items-center gap-3 px-2 py-2 cursor-pointer aria-selected:bg-elevated text-text-secondary aria-selected:text-text-primary"
                    >
                      {Icon && <Icon size={14} className="text-text-muted" />}
                      <span className="text-body-sm">{label}</span>
                    </Command.Item>
                  );
                })}
              </Command.Group>
            )}

            <Command.Group
              heading={
                <span className="font-mono text-[10px] tracking-[0.2em] text-text-muted uppercase px-2">
                  {t('cmdk.groups.pages')}
                </span>
              }
            >
              {PAGES.map((page) => {
                const Icon = page.icon;
                return (
                  <Command.Item
                    key={page.id}
                    value={`page:${page.id} ${t(page.navKey)}`}
                    onSelect={() => runPage(page)}
                    className="flex items-center gap-3 px-2 py-2 cursor-pointer aria-selected:bg-elevated text-text-secondary aria-selected:text-text-primary"
                  >
                    <Icon size={14} className="text-text-muted" />
                    <span className="text-body-sm">{t(page.navKey)}</span>
                    <span className="ml-auto font-mono text-[10px] text-text-muted">
                      {page.to}
                    </span>
                  </Command.Item>
                );
              })}
            </Command.Group>

            <Command.Group
              heading={
                <span className="font-mono text-[10px] tracking-[0.2em] text-text-muted uppercase px-2">
                  {t('cmdk.groups.actions')}
                </span>
              }
            >
              {ACTIONS.map((action) => {
                const Icon = action.icon;
                return (
                  <Command.Item
                    key={action.id}
                    value={`action:${action.id} ${t(`cmdk.actions.${action.id}`)}`}
                    onSelect={() => runAction(action)}
                    className="flex items-center gap-3 px-2 py-2 cursor-pointer aria-selected:bg-elevated text-text-secondary aria-selected:text-text-primary"
                  >
                    {Icon && <Icon size={14} className="text-text-muted" />}
                    <span className="text-body-sm">{t(`cmdk.actions.${action.id}`)}</span>
                  </Command.Item>
                );
              })}
            </Command.Group>
          </Command.List>

          <div className="border-t border-border-subtle px-4 py-2 flex items-center justify-between font-mono text-[10px] text-text-muted tracking-[0.15em]">
            <span>{t('cmdk.kbd.navigate')}</span>
            <span>{t('cmdk.kbd.close')}</span>
          </div>
        </Command>
      </div>
    </Command.Dialog>
  );
}
