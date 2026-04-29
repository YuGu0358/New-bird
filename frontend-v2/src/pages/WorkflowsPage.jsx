import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Play,
  Pencil,
  Trash2,
  Power,
  PowerOff,
  Save,
  X,
  Workflow as WorkflowIcon,
} from 'lucide-react';
import {
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import WorkflowCanvas from '../components/workflow/WorkflowCanvas.jsx';
import {
  listWorkflows,
  upsertWorkflow,
  deleteWorkflow,
  runWorkflow,
  enableWorkflow,
  disableWorkflow,
} from '../lib/api.js';
import { classNames, fmtRelativeTime } from '../lib/format.js';

/**
 * @typedef {import('../lib/api.js').WorkflowView} WorkflowView
 * @typedef {import('../lib/api.js').WorkflowDefinition} WorkflowDefinition
 * @typedef {import('../lib/api.js').WorkflowRunView} WorkflowRunView
 */

const EMPTY_DEFINITION = { nodes: [], edges: [] };

/** Initial state for a freshly-clicked "New workflow". */
const NEW_DRAFT = {
  name: '',
  definition: EMPTY_DEFINITION,
  schedule_seconds: 0,
  is_active: false,
};

export default function WorkflowsPage() {
  const queryClient = useQueryClient();
  const listQ = useQuery({ queryKey: ['workflows'], queryFn: listWorkflows });

  // Editor state. `mode === 'new'` → name editable; `mode === 'edit'` → name locked.
  const [editor, setEditor] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [runError, setRunError] = useState(null);

  const invalidateList = async () => {
    await queryClient.invalidateQueries({ queryKey: ['workflows'] });
  };

  const upsertMut = useMutation({
    mutationFn: upsertWorkflow,
    onSuccess: async () => {
      await invalidateList();
    },
  });
  const deleteMut = useMutation({
    mutationFn: deleteWorkflow,
    onSuccess: async () => {
      await invalidateList();
    },
  });
  const runMut = useMutation({ mutationFn: runWorkflow });
  const enableMut = useMutation({
    mutationFn: enableWorkflow,
    onSuccess: async () => {
      await invalidateList();
    },
  });
  const disableMut = useMutation({
    mutationFn: disableWorkflow,
    onSuccess: async () => {
      await invalidateList();
    },
  });

  const startNew = () => {
    setRunResult(null);
    setRunError(null);
    setEditor({ mode: 'new', draft: { ...NEW_DRAFT, definition: { ...EMPTY_DEFINITION } } });
  };

  /** @param {WorkflowView} wf */
  const startEdit = (wf) => {
    setRunResult(null);
    setRunError(null);
    setEditor({
      mode: 'edit',
      draft: {
        name: wf.name,
        definition: wf.definition ?? EMPTY_DEFINITION,
        schedule_seconds: wf.schedule_seconds ?? 0,
        is_active: Boolean(wf.is_active),
      },
    });
  };

  const cancelEdit = () => {
    setEditor(null);
    setRunResult(null);
    setRunError(null);
  };

  /** @param {{nodes: any[], edges: any[]}} graph */
  const updateDefinition = (graph) => {
    setEditor((prev) => (prev ? { ...prev, draft: { ...prev.draft, definition: graph } } : prev));
  };

  /** @param {Partial<typeof NEW_DRAFT>} patch */
  const patchDraft = (patch) => {
    setEditor((prev) => (prev ? { ...prev, draft: { ...prev.draft, ...patch } } : prev));
  };

  const save = async () => {
    if (!editor) return;
    const { draft } = editor;
    const trimmedName = (draft.name || '').trim();
    if (!trimmedName) {
      setRunError(new Error('Name is required'));
      return;
    }
    try {
      await upsertMut.mutateAsync({
        name: trimmedName,
        definition: draft.definition || EMPTY_DEFINITION,
        schedule_seconds: draft.schedule_seconds ? Number(draft.schedule_seconds) : null,
        is_active: Boolean(draft.is_active),
      });
      setEditor(null);
    } catch (err) {
      setRunError(err);
    }
  };

  const runNow = async () => {
    if (!editor || editor.mode !== 'edit') return;
    setRunError(null);
    try {
      const result = await runMut.mutateAsync(editor.draft.name);
      setRunResult(result);
    } catch (err) {
      setRunError(err);
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={11}
        title="Workflows"
        segments={[
          { label: 'Visual node editor' },
          { label: 'P5.6 · STRATEGY DAG', accent: true },
        ]}
        live={false}
      />

      <div className="card">
        <SectionHeader
          title="Workflows"
          subtitle={`${listQ.data?.workflows?.length ?? 0} saved`}
          action={
            <button type="button" className="btn-primary btn-sm inline-flex items-center gap-1.5" onClick={startNew}>
              <Plus size={14} /> New workflow
            </button>
          }
        />
        <WorkflowList
          q={listQ}
          onEdit={startEdit}
          onRun={async (name) => {
            setRunError(null);
            try {
              const result = await runMut.mutateAsync(name);
              setRunResult(result);
            } catch (err) {
              setRunError(err);
            }
          }}
          onToggle={async (wf) => {
            try {
              if (wf.is_active) await disableMut.mutateAsync(wf.name);
              else await enableMut.mutateAsync(wf.name);
            } catch (err) {
              setRunError(err);
            }
          }}
          onDelete={async (name) => {
            try {
              await deleteMut.mutateAsync(name);
            } catch (err) {
              setRunError(err);
            }
          }}
          deleting={deleteMut.isPending}
          toggling={enableMut.isPending || disableMut.isPending}
        />
      </div>

      {editor && (
        <div className="card">
          <SectionHeader
            title={editor.mode === 'new' ? 'New workflow' : `Editing: ${editor.draft.name}`}
            subtitle="Drag handles between nodes to connect"
            action={
              <div className="flex items-center gap-2">
                {editor.mode === 'edit' && (
                  <button
                    type="button"
                    className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                    onClick={runNow}
                    disabled={runMut.isPending}
                  >
                    <Play size={14} /> Run now
                  </button>
                )}
                <button
                  type="button"
                  className="btn-primary btn-sm inline-flex items-center gap-1.5"
                  onClick={save}
                  disabled={upsertMut.isPending}
                >
                  <Save size={14} /> Save
                </button>
                <button
                  type="button"
                  className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                  onClick={cancelEdit}
                >
                  <X size={14} /> Cancel
                </button>
              </div>
            }
          />
          <EditorForm draft={editor.draft} mode={editor.mode} onPatch={patchDraft} />
          <div className="mt-4">
            <WorkflowCanvas
              key={`${editor.mode}-${editor.draft.name || 'new'}`}
              initialNodes={editor.draft.definition?.nodes ?? []}
              initialEdges={editor.draft.definition?.edges ?? []}
              onChange={updateDefinition}
            />
          </div>
          {runError && (
            <div className="mt-4">
              <ErrorState error={runError} />
            </div>
          )}
          {runResult && <RunResultPanel result={runResult} />}
        </div>
      )}
    </div>
  );
}

function EditorForm({ draft, mode, onPatch }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Field label="Name">
        <input
          type="text"
          className="form-input"
          value={draft.name}
          disabled={mode === 'edit'}
          onChange={(e) => onPatch({ name: e.target.value })}
          placeholder="e.g. spy_rsi_buy"
        />
      </Field>
      <Field label="Schedule (seconds, 0 = manual)">
        <input
          type="number"
          min={0}
          className="form-input"
          value={draft.schedule_seconds || 0}
          onChange={(e) => onPatch({ schedule_seconds: Number(e.target.value) || 0 })}
        />
      </Field>
      <Field label="Active">
        <label className="inline-flex items-center gap-2 mt-2">
          <input
            type="checkbox"
            checked={Boolean(draft.is_active)}
            onChange={(e) => onPatch({ is_active: e.target.checked })}
          />
          <span className="text-body-sm text-text-secondary">
            {draft.is_active ? 'Scheduled runs enabled' : 'Manual / paused'}
          </span>
        </label>
      </Field>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted block mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function WorkflowList({ q, onEdit, onRun, onToggle, onDelete, deleting, toggling }) {
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.workflows ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={WorkflowIcon}
        title="No workflows yet"
        hint="Click New workflow to wire up your first DAG."
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body-sm">
        <thead>
          <tr className="text-left font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted border-b border-border-subtle">
            <th className="py-2 pr-4">Name</th>
            <th className="py-2 pr-4">Status</th>
            <th className="py-2 pr-4">Schedule</th>
            <th className="py-2 pr-4">Updated</th>
            <th className="py-2 pr-4 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((wf) => (
            <tr key={wf.id ?? wf.name} className="border-b border-border-subtle/40">
              <td className="py-2 pr-4 font-mono text-text-primary">{wf.name}</td>
              <td className="py-2 pr-4">
                <span className={wf.is_active ? 'pill-cyan' : 'pill-default'}>
                  {wf.is_active ? 'active' : 'inactive'}
                </span>
              </td>
              <td className="py-2 pr-4 text-text-secondary">
                {wf.schedule_seconds ? `every ${wf.schedule_seconds}s` : 'manual'}
              </td>
              <td className="py-2 pr-4 text-text-secondary">{fmtRelativeTime(wf.updated_at)}</td>
              <td className="py-2 pr-4">
                <div className="flex items-center gap-2 justify-end">
                  <button
                    type="button"
                    className="btn-secondary btn-sm inline-flex items-center gap-1"
                    onClick={() => onRun(wf.name)}
                    title="Run now"
                  >
                    <Play size={12} /> Run
                  </button>
                  <button
                    type="button"
                    className="btn-secondary btn-sm inline-flex items-center gap-1"
                    onClick={() => onEdit(wf)}
                    title="Edit"
                  >
                    <Pencil size={12} /> Edit
                  </button>
                  <button
                    type="button"
                    className="btn-secondary btn-sm inline-flex items-center gap-1"
                    onClick={() => onToggle(wf)}
                    disabled={toggling}
                    title={wf.is_active ? 'Disable' : 'Enable'}
                  >
                    {wf.is_active ? <PowerOff size={12} /> : <Power size={12} />}
                    {wf.is_active ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary btn-sm inline-flex items-center gap-1 text-loss"
                    onClick={() => onDelete(wf.name)}
                    disabled={deleting}
                    title="Delete"
                  >
                    <Trash2 size={12} /> Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** @param {{ result: WorkflowRunView }} props */
function RunResultPanel({ result }) {
  const [open, setOpen] = useState(true);
  const ok = Boolean(result?.succeeded);
  const nodes = useMemo(() => result?.nodes ?? [], [result]);
  return (
    <div className="mt-4 border border-border-subtle">
      <button
        type="button"
        className={classNames(
          'w-full text-left px-3 py-2 flex items-center justify-between font-mono text-[11px] tracking-[0.15em] uppercase',
          ok ? 'text-profit' : 'text-loss',
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <span>
          Last run: {ok ? 'succeeded' : 'failed'} · {result?.duration_ms ?? 0} ms
        </span>
        <span className="text-text-muted">{open ? 'hide' : 'show'}</span>
      </button>
      {open && (
        <div className="px-3 py-3 space-y-3 border-t border-border-subtle">
          {nodes.length === 0 ? (
            <p className="text-body-sm text-text-secondary">No nodes executed.</p>
          ) : (
            nodes.map((n) => (
              <div
                key={n.node_id}
                className={classNames(
                  'border px-3 py-2',
                  n.error ? 'border-loss/40 bg-loss-tint' : 'border-profit/40',
                )}
              >
                <div className="flex items-center justify-between font-mono text-[11px] tracking-[0.1em] uppercase">
                  <span className="text-text-primary">{n.node_id}</span>
                  <span className="text-text-muted">{n.node_type}</span>
                </div>
                {n.error ? (
                  <pre className="mt-1.5 text-[12px] text-loss whitespace-pre-wrap break-all">
                    {String(n.error)}
                  </pre>
                ) : (
                  <pre className="mt-1.5 text-[12px] text-text-secondary whitespace-pre-wrap break-all font-mono">
                    {JSON.stringify(n.output, null, 2)}
                  </pre>
                )}
              </div>
            ))
          )}
          {result?.final_output !== undefined && (
            <div className="border border-border-subtle px-3 py-2">
              <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted mb-1">
                Final output
              </div>
              <pre className="text-[12px] text-text-secondary whitespace-pre-wrap break-all font-mono">
                {JSON.stringify(result.final_output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
