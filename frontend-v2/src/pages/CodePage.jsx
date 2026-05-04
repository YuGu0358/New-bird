import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { oneDark } from '@codemirror/theme-one-dark';
import {
  Code2, Upload, Trash2, RefreshCw, FileCode, Sparkles, AlertTriangle,
} from 'lucide-react';
import {
  listUserStrategies,
  uploadUserStrategy,
  getUserStrategySource,
  reloadUserStrategy,
  deleteUserStrategy,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
  StatusBadge,
} from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtRelativeTime, classNames } from '../lib/format.js';


const STARTER_TEMPLATE = `from __future__ import annotations
from datetime import datetime

from core.strategy import Strategy, register_strategy
from app.models import StrategyExecutionParameters


@register_strategy("__SLOT_NAME__")
class MyStrategy(Strategy):
    description = "Buy on -3% drop, hold."

    @classmethod
    def parameters_schema(cls):
        return StrategyExecutionParameters

    def __init__(self, parameters, *, broker=None) -> None:
        super().__init__(parameters)
        self._broker = broker

    def universe(self) -> list[str]:
        return list(self.parameters.universe_symbols)

    async def on_start(self, ctx) -> None:
        return None

    async def on_periodic_sync(self, ctx, now: datetime) -> None:
        return None

    async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None):
        if previous_close <= 0:
            return
        drop = (price - previous_close) / previous_close
        if drop <= -0.03 and self._broker is not None:
            await self._broker.submit_order(
                symbol=symbol, side="buy", notional=1000.0,
            )
`;


export default function CodePage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [slotName, setSlotName] = useState('user_my_strategy_v1');
  const [displayName, setDisplayName] = useState('My strategy');
  const [description, setDescription] = useState('');
  const [source, setSource] = useState(STARTER_TEMPLATE.replace('__SLOT_NAME__', 'user_my_strategy_v1'));

  const listQ = useQuery({ queryKey: ['user-strategies'], queryFn: listUserStrategies, refetchInterval: 30_000 });

  const uploadMut = useMutation({
    mutationFn: uploadUserStrategy,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['user-strategies'] }),
  });
  const reloadMut = useMutation({
    mutationFn: reloadUserStrategy,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['user-strategies'] }),
  });
  const deleteMut = useMutation({
    mutationFn: deleteUserStrategy,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['user-strategies'] }),
  });

  function submit(e) {
    e.preventDefault();
    if (!slotName.trim() || !source.trim()) return;
    uploadMut.mutate({
      slot_name: slotName.trim(),
      display_name: displayName.trim(),
      description: description.trim(),
      source_code: source,
    });
  }

  function insertStarter() {
    setSource(STARTER_TEMPLATE.replace('__SLOT_NAME__', slotName.trim() || 'user_my_strategy_v1'));
  }

  async function loadIntoEditor(item) {
    try {
      const detail = await getUserStrategySource(item.id);
      setSlotName(detail.slot_name);
      setDisplayName(detail.display_name);
      setDescription(detail.description);
      setSource(detail.source_code);
    } catch (e) {
      console.error('Failed to load source:', e);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={9}
        title={t('code.title')}
        segments={[
          { label: t('code.subtitle') },
          { label: 'P9 · SANDBOX', accent: true },
        ]}
        live={false}
      />

      <div className="grid grid-cols-12 gap-6">
        {/* Left: editor */}
        <form onSubmit={submit} className="col-span-8 card space-y-4">
          <SectionHeader title={t('code.newUpload')} action={
            <button type="button" className="btn-secondary btn-sm" onClick={insertStarter}>
              <Sparkles size={12} /> {t('code.starterTemplate')}
            </button>
          } />

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="h-caption block mb-2">{t('code.slotName')}</label>
              <input className="input font-mono" value={slotName} onChange={(e) => setSlotName(e.target.value)} required />
              <p className="text-caption text-steel-300 mt-1">{t('code.slotNameHint')}</p>
            </div>
            <div>
              <label className="h-caption block mb-2">{t('code.displayName')}</label>
              <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
              <p className="text-caption text-steel-300 mt-1">{t('code.displayNameHint')}</p>
            </div>
            <div>
              <label className="h-caption block mb-2">{t('code.descriptionField')}</label>
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
              <p className="text-caption text-steel-300 mt-1">{t('code.descriptionHint')}</p>
            </div>
          </div>

          <div>
            <label className="h-caption block mb-2">{t('code.sourceCode')}</label>
            <div className="border border-steel-400 rounded-md overflow-hidden">
              <CodeMirror
                value={source}
                height="540px"
                theme={oneDark}
                extensions={[python()]}
                onChange={setSource}
                basicSetup={{
                  lineNumbers: true,
                  foldGutter: true,
                  highlightActiveLine: true,
                  bracketMatching: true,
                  closeBrackets: true,
                  autocompletion: true,
                  indentOnInput: true,
                }}
              />
            </div>
            <p className="text-caption text-steel-300 mt-2">{t('code.sourceHint')}</p>
          </div>

          {uploadMut.isError && <ApiErrorBanner error={uploadMut.error} label={t('code.uploadFailed')} />}
          {uploadMut.isSuccess && (
            <div className="border border-bull/40 rounded-md bg-bull-tint px-3 py-2 text-body-sm text-bull">
              ✓ {t('code.uploadSuccess')}
            </div>
          )}

          <button type="submit" className="btn-primary" disabled={uploadMut.isPending || !slotName.trim() || !source.trim()}>
            <Upload size={14} /> {uploadMut.isPending ? t('code.uploading') : t('code.uploadButton')}
          </button>
        </form>

        {/* Right: list of uploads */}
        <div className="col-span-4 card">
          <SectionHeader
            title={t('code.uploadedList')}
            subtitle={t('code.uploadedSubtitle', { count: listQ.data?.items?.length ?? 0 })}
          />
          <UploadedList
            q={listQ}
            t={t}
            onLoad={loadIntoEditor}
            onReload={(id) => reloadMut.mutate(id)}
            onDelete={(item) => {
              if (confirm(t('code.deleteConfirm', { name: item.slot_name }))) {
                deleteMut.mutate(item.id);
              }
            }}
            reloading={reloadMut.isPending}
            deleting={deleteMut.isPending}
          />
        </div>
      </div>
    </div>
  );
}


function UploadedList({ q, t, onLoad, onReload, onDelete, reloading, deleting }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={Code2} title={t('code.uploadedEmpty')} hint={t('code.uploadedEmptyHint')} />;

  return (
    <ul className="space-y-3 max-h-[640px] overflow-auto pr-1">
      {items.map((it) => (
        <li key={it.id} className="card-dense">
          <div className="flex items-start justify-between gap-2 mb-1">
            <div className="min-w-0 flex-1">
              <div className="font-mono text-caption text-accent-silver truncate">{it.slot_name}</div>
              <div className="text-body font-semibold text-steel-50 truncate">{it.display_name || it.slot_name}</div>
            </div>
            <StrategyStatusBadge status={it.status} t={t} />
          </div>
          {it.description && (
            <p className="text-caption text-steel-200 mb-2 line-clamp-2">{it.description}</p>
          )}
          {it.last_error && (
            <div className="border border-bear/40 rounded bg-bear-tint/40 px-2 py-1.5 mb-2 text-caption text-bear flex items-start gap-1.5">
              <AlertTriangle size={11} className="shrink-0 mt-0.5" />
              <div>
                <div className="font-medium">{t('code.lastError')}:</div>
                <div className="text-bear/90 break-all">{it.last_error}</div>
              </div>
            </div>
          )}
          <div className="text-caption text-steel-300 mb-2">{fmtRelativeTime(it.updated_at)}</div>
          <div className="flex gap-1.5 flex-wrap">
            <button className="btn-secondary btn-sm" onClick={() => onLoad(it)} title={t('code.loadIntoEditor')}>
              <FileCode size={11} /> {t('code.loadIntoEditor')}
            </button>
            <button className="btn-ghost btn-sm" onClick={() => onReload(it.id)} disabled={reloading} title={t('code.reload')}>
              <RefreshCw size={11} className={reloading ? 'animate-spin' : ''} />
            </button>
            <button className="btn-destructive btn-sm" onClick={() => onDelete(it)} disabled={deleting} title={t('code.delete')}>
              <Trash2 size={11} />
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}


function StrategyStatusBadge({ status, t }) {
  const map = {
    active: 'pill-bull',
    failed: 'pill-bear',
    disabled: 'pill-default',
  };
  return (
    <span className={classNames(map[status] || 'pill-default', 'shrink-0')}>
      {t(`code.registryStatus.${status}`, status)}
    </span>
  );
}
