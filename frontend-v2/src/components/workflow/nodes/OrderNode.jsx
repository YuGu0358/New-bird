import { NodeShell, NodeField, NODE_INPUT_CLASS, useNodeDataSetter } from './nodeShell.jsx';

/**
 * @param {{ id: string, data: { side?: 'buy'|'sell', qty?: number, paper?: boolean } }} props
 */
export default function OrderNode({ id, data }) {
  const setData = useNodeDataSetter(id);
  const side = data?.side ?? 'buy';
  const qty = data?.qty ?? 10;
  return (
    <NodeShell id={id} title="ORDER" tone={side === 'buy' ? 'profit' : 'loss'}>
      <NodeField label="Side">
        <select
          className={NODE_INPUT_CLASS}
          value={side}
          onChange={(e) => setData({ side: e.target.value })}
        >
          <option value="buy">BUY</option>
          <option value="sell">SELL</option>
        </select>
      </NodeField>
      <NodeField label="Qty">
        <input
          type="number"
          min={1}
          className={NODE_INPUT_CLASS}
          value={qty}
          onChange={(e) => setData({ qty: Number(e.target.value) || 0 })}
        />
      </NodeField>
      <label className="flex items-center gap-2 text-[11px] text-text-muted nodrag">
        <input type="checkbox" checked readOnly disabled />
        <span>Paper trading (locked)</span>
      </label>
    </NodeShell>
  );
}
