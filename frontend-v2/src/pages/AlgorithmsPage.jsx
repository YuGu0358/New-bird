import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Power, Trash2, GitBranch, BookOpen } from 'lucide-react';
import {
  listStrategies,
  listRegisteredStrategies,
  activateStrategy,
  deleteStrategy,
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
