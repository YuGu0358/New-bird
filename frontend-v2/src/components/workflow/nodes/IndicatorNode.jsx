import { NodeShell, NodeField, NODE_INPUT_CLASS, useNodeDataSetter } from './nodeShell.jsx';

const INDICATOR_OPTIONS = ['rsi', 'sma', 'ema', 'macd'];

/**
 * @param {{ id: string, data: { name?: string, period?: number } }} props
 */
export default function IndicatorNode({ id, data }) {
  const setData = useNodeDataSetter(id);
  const name = data?.name ?? 'rsi';
  const period = data?.period ?? 14;
  return (
    <NodeShell id={id} title="INDICATOR" tone="cyan">
      <NodeField label="Name">
        <select
          className={NODE_INPUT_CLASS}
          value={name}
          onChange={(e) => setData({ name: e.target.value })}
        >
          {INDICATOR_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt.toUpperCase()}
            </option>
          ))}
        </select>
      </NodeField>
      <NodeField label="Period">
        <input
          type="number"
          min={1}
          className={NODE_INPUT_CLASS}
          value={period}
          onChange={(e) => setData({ period: Number(e.target.value) || 0 })}
        />
      </NodeField>
    </NodeShell>
  );
}
