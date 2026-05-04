import { Handle, Position, useReactFlow } from 'reactflow';
import { classNames } from '../../../lib/format.js';

/**
 * Shared chrome for every workflow node: target/source handles, header, body.
 *
 * @param {{ id: string, title: string, tone?: 'cyan'|'profit'|'warn'|'loss'|'neutral', children: import('react').ReactNode }} props
 */
export function NodeShell({ id: _id, title, tone = 'neutral', children }) {
  const toneClass = {
    cyan: 'border-cyan/60',
    profit: 'border-profit/60',
    warn: 'border-warn/60',
    loss: 'border-loss/60',
    neutral: 'border-border-subtle',
  }[tone] || 'border-border-subtle';

  return (
    <div
      className={classNames(
        'bg-surface text-text-primary border min-w-[180px] shadow-sm',
        toneClass,
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-cyan !border-0"
      />
      <div className="px-3 py-1.5 border-b border-border-subtle font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted">
        {title}
      </div>
      <div className="px-3 py-2 space-y-1.5 text-[12px]">{children}</div>
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-cyan !border-0"
      />
    </div>
  );
}

/**
 * Hook returning a setter that immutably updates `data` on the node with `id`.
 *
 * @param {string} id
 * @returns {(patch: Record<string, unknown>) => void}
 */
export function useNodeDataSetter(id) {
  const rf = useReactFlow();
  return (patch) => {
    rf.setNodes((nodes) =>
      nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)),
    );
  };
}

export const NODE_INPUT_CLASS =
  'w-full bg-elevated border border-border-subtle px-2 py-1 text-[12px] font-mono text-text-primary focus:border-cyan focus:outline-none nodrag';

/** @param {{ label: string, children: import('react').ReactNode }} props */
export function NodeField({ label, children }) {
  return (
    <label className="block">
      <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-text-muted block mb-0.5">
        {label}
      </span>
      {children}
    </label>
  );
}
