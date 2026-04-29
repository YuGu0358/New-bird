import { useCallback, useEffect, useMemo, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Plus } from 'lucide-react';
import DataFetchNode from './nodes/DataFetchNode.jsx';
import IndicatorNode from './nodes/IndicatorNode.jsx';
import SignalNode from './nodes/SignalNode.jsx';
import RiskCheckNode from './nodes/RiskCheckNode.jsx';
import OrderNode from './nodes/OrderNode.jsx';

/**
 * @typedef {import('../../lib/api.js').WorkflowNode} WorkflowNode
 * @typedef {import('../../lib/api.js').WorkflowEdge} WorkflowEdge
 */

const NODE_TYPES = {
  'data-fetch': DataFetchNode,
  indicator: IndicatorNode,
  signal: SignalNode,
  'risk-check': RiskCheckNode,
  order: OrderNode,
};

const PALETTE = [
  { type: 'data-fetch', label: 'Data fetch', defaults: { ticker: 'SPY', lookback_days: 30 } },
  { type: 'indicator', label: 'Indicator', defaults: { name: 'rsi', period: 14 } },
  { type: 'signal', label: 'Signal', defaults: { expr: 'rsi < 30' } },
  { type: 'risk-check', label: 'Risk check', defaults: { max_position_size: 1000 } },
  { type: 'order', label: 'Order', defaults: { side: 'buy', qty: 10, paper: true } },
];

const DEFAULT_FIT_VIEW_OPTIONS = { padding: 0.2, maxZoom: 1.25 };

/**
 * Visual workflow editor backed by React Flow. Persists the graph as
 * `{ nodes, edges }` matching the backend's WorkflowDefinition schema.
 *
 * @param {{
 *   initialNodes: WorkflowNode[],
 *   initialEdges: WorkflowEdge[],
 *   onChange: (graph: { nodes: WorkflowNode[], edges: WorkflowEdge[] }) => void,
 * }} props
 */
export default function WorkflowCanvas({ initialNodes, initialEdges, onChange }) {
  return (
    <ReactFlowProvider>
      <CanvasInner
        initialNodes={initialNodes}
        initialEdges={initialEdges}
        onChange={onChange}
      />
    </ReactFlowProvider>
  );
}

function CanvasInner({ initialNodes, initialEdges, onChange }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes ?? []);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges ?? []);

  // Hold the latest onChange in a ref so the propagation effect doesn't
  // re-fire just because the parent re-renders with a new function identity.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (typeof onChangeRef.current === 'function') {
      onChangeRef.current({ nodes, edges });
    }
  }, [nodes, edges]);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge({ ...params, id: makeEdgeId(params) }, eds)),
    [setEdges],
  );

  const addNode = useCallback(
    (type, defaults) => {
      setNodes((current) => {
        const id = makeNodeId(current, type);
        const offset = current.length * 24;
        const newNode = {
          id,
          type,
          position: { x: 80 + offset, y: 80 + offset },
          data: { ...defaults },
        };
        return [...current, newNode];
      });
    },
    [setNodes],
  );

  const nodeTypes = useMemo(() => NODE_TYPES, []);

  return (
    <div className="border border-border-subtle bg-void">
      <Palette onAdd={addNode} />
      <div style={{ width: '100%', height: 520 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={DEFAULT_FIT_VIEW_OPTIONS}
          deleteKeyCode={['Backspace', 'Delete']}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} color="#1f2937" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}

/** @param {{ onAdd: (type: string, defaults: Record<string, unknown>) => void }} props */
function Palette({ onAdd }) {
  return (
    <div className="flex flex-wrap gap-2 p-2 border-b border-border-subtle bg-surface">
      <span className="font-mono text-[10px] tracking-[0.15em] uppercase text-text-muted self-center mr-2">
        Add node
      </span>
      {PALETTE.map((item) => (
        <button
          key={item.type}
          type="button"
          className="btn-secondary btn-sm inline-flex items-center gap-1.5"
          onClick={() => onAdd(item.type, item.defaults)}
        >
          <Plus size={12} /> {item.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Produce a stable, collision-free node id for a freshly-added node.
 *
 * @param {WorkflowNode[]} existing
 * @param {string} type
 * @returns {string}
 */
function makeNodeId(existing, type) {
  const prefix = type.replace(/[^a-z]/gi, '').slice(0, 4) || 'node';
  let counter = existing.length + 1;
  let candidate = `${prefix}_${counter}`;
  const used = new Set(existing.map((n) => n.id));
  while (used.has(candidate)) {
    counter += 1;
    candidate = `${prefix}_${counter}`;
  }
  return candidate;
}

/** @param {{ source: string, target: string }} params */
function makeEdgeId(params) {
  return `e_${params.source}_${params.target}_${Math.random().toString(36).slice(2, 7)}`;
}
