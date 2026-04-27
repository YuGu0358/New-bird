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
    <div className="space-y-6">
      <div>
        <h1 className="h-page">{t('algorithms.title')}</h1>
        <p className="text-body-sm text-steel-200 mt-1">{t('algorithms.subtitle')}</p>
      </div>

      {/* Registered strategy types (P2 framework) */}
      <div className="card">
        <SectionHeader
          title="注册的策略类型"
          subtitle="@register_strategy 装饰器注入的所有 Strategy 子类"
        />
        <RegisteredGrid q={registeredQ} />
      </div>

      {/* User strategy library */}
      <div className="card">
        <SectionHeader
          title="我的策略库"
          subtitle={`${libraryQ.data?.items?.length ?? 0} 条 · 最多 ${libraryQ.data?.max_slots ?? 5} 条`}
        />
        <StrategyLibrary
          q={libraryQ}
          onActivate={(id) => activateMut.mutate(id)}
          onDelete={(id) => deleteMut.mutate(id)}
          activating={activateMut.isPending}
          deleting={deleteMut.isPending}
        />
        <p className="text-caption text-steel-300 mt-4">
          创建 / 编辑流程使用 OpenAI 解析自然语言描述,后端 P2 通过 registry 校验参数 schema。前端编辑器在 P9 Code 里实现。
        </p>
      </div>
    </div>
  );
}

function RegisteredGrid({ q }) {
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={BookOpen} title="registry 为空" />;

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
            <summary className="cursor-pointer text-steel-200 hover:text-steel-50">参数 schema</summary>
            <pre className="mt-2 p-3 bg-ink-900 border border-steel-400 rounded font-mono text-[11px] text-steel-200 overflow-auto max-h-48">
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

function StrategyLibrary({ q, onActivate, onDelete, activating, deleting }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={GitBranch} title="策略库是空的" hint="将来在 Code 编辑器里上传策略 (P9)。" />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>名称</th>
          <th>描述</th>
          <th>状态</th>
          <th>更新</th>
          <th className="text-right">操作</th>
        </tr>
      </thead>
      <tbody>
        {items.map((s) => (
          <tr key={s.id}>
            <td className="font-medium text-steel-50">{s.name}</td>
            <td className="text-steel-200 max-w-md truncate">{s.normalized_strategy || s.raw_description}</td>
            <td>
              {s.is_active ? <span className="pill-active">active</span> : <span className="pill-default">idle</span>}
            </td>
            <td className="text-caption text-steel-200">{fmtRelativeTime(s.updated_at)}</td>
            <td className="text-right">
              <div className="inline-flex gap-2">
                {!s.is_active && (
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => onActivate(s.id)}
                    disabled={activating}
                    title="激活"
                  >
                    <Power size={12} /> 激活
                  </button>
                )}
                <button
                  className={classNames('btn-sm', s.is_active ? 'btn-ghost' : 'btn-destructive')}
                  onClick={() => {
                    if (confirm(`确认删除策略 "${s.name}" ?`)) onDelete(s.id);
                  }}
                  disabled={deleting || s.is_active}
                  title={s.is_active ? '激活中不能删' : '删除'}
                >
                  <Trash2 size={12} /> 删除
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
