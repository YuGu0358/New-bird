import { NodeShell, NodeField, NODE_INPUT_CLASS, useNodeDataSetter } from './nodeShell.jsx';

/**
 * @param {{ id: string, data: { max_position_size?: number } }} props
 */
export default function RiskCheckNode({ id, data }) {
  const setData = useNodeDataSetter(id);
  const max = data?.max_position_size ?? 1000;
  return (
    <NodeShell id={id} title="RISK CHECK" tone="warn">
      <NodeField label="Max position size ($)">
        <input
          type="number"
          min={0}
          className={NODE_INPUT_CLASS}
          value={max}
          onChange={(e) =>
            setData({ max_position_size: Number(e.target.value) || 0 })
          }
        />
      </NodeField>
    </NodeShell>
  );
}
