import { NodeShell, NodeField, NODE_INPUT_CLASS, useNodeDataSetter } from './nodeShell.jsx';

/**
 * @param {{ id: string, data: { expr?: string } }} props
 */
export default function SignalNode({ id, data }) {
  const setData = useNodeDataSetter(id);
  const expr = data?.expr ?? '';
  return (
    <NodeShell id={id} title="SIGNAL" tone="warn">
      <NodeField label="Expression">
        <input
          className={NODE_INPUT_CLASS}
          value={expr}
          onChange={(e) => setData({ expr: e.target.value })}
          placeholder="rsi < 30"
          spellCheck={false}
        />
      </NodeField>
      <p className="text-[10px] text-text-muted">
        Reference upstream indicator outputs by name.
      </p>
    </NodeShell>
  );
}
