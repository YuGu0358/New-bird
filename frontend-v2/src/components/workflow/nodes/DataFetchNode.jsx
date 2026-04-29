import { NodeShell, NodeField, NODE_INPUT_CLASS, useNodeDataSetter } from './nodeShell.jsx';

/**
 * @param {{ id: string, data: { ticker?: string, lookback_days?: number } }} props
 */
export default function DataFetchNode({ id, data }) {
  const setData = useNodeDataSetter(id);
  const ticker = data?.ticker ?? '';
  const lookback = data?.lookback_days ?? 30;
  return (
    <NodeShell id={id} title="DATA FETCH" tone="cyan">
      <NodeField label="Ticker">
        <input
          className={NODE_INPUT_CLASS}
          value={ticker}
          onChange={(e) => setData({ ticker: e.target.value.toUpperCase() })}
          placeholder="SPY"
        />
      </NodeField>
      <NodeField label="Lookback days">
        <input
          type="number"
          min={1}
          className={NODE_INPUT_CLASS}
          value={lookback}
          onChange={(e) => setData({ lookback_days: Number(e.target.value) || 0 })}
        />
      </NodeField>
    </NodeShell>
  );
}
