// PositionCostEditor — inline form for setting cost basis + custom stops on
// one (broker_account, ticker) pair. Used inside AccountDetailPage rows.
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Save, Trash2, X } from 'lucide-react';
import {
  deletePositionCost,
  getPositionCost,
  recordPositionBuy,
  upsertPositionCost,
} from '../lib/api.js';
import { ErrorState, LoadingState } from './primitives.jsx';

/**
 * @param {{ accountPk: number, ticker: string, onClose?: () => void }} props
 */
export default function PositionCostEditor({ accountPk, ticker, onClose }) {
  const queryClient = useQueryClient();
  const ctxQ = useQuery({
    queryKey: ['position-cost', accountPk, ticker],
    queryFn: () => getPositionCost(accountPk, ticker),
    retry: false,
  });

  const isNotFound = ctxQ.isError && /** @type {any} */ (ctxQ.error)?.status === 404;
  const existing = isNotFound || ctxQ.isLoading ? null : /** @type {any} */ (ctxQ.data);

  const [avgCost, setAvgCost] = useState('');
  const [totalShares, setTotalShares] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [notes, setNotes] = useState('');
  const [buyPrice, setBuyPrice] = useState('');
  const [buyQty, setBuyQty] = useState('');

  useEffect(() => {
    // Reset on ticker change so a row from one ticker can't leak into another.
    if (existing) {
      setAvgCost(String(existing.avg_cost_basis ?? ''));
      setTotalShares(String(existing.total_shares ?? ''));
      setStopLoss(existing.custom_stop_loss != null ? String(existing.custom_stop_loss) : '');
      setTakeProfit(existing.custom_take_profit != null ? String(existing.custom_take_profit) : '');
      setNotes(existing.notes ?? '');
    } else if (isNotFound) {
      setAvgCost(''); setTotalShares(''); setStopLoss(''); setTakeProfit(''); setNotes('');
    } else {
      // Loading or transient state — clear so we don't show last ticker's values.
      setAvgCost(''); setTotalShares(''); setStopLoss(''); setTakeProfit(''); setNotes('');
    }
    setBuyPrice(''); setBuyQty('');
  }, [ticker, existing, isNotFound]);

  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['position-cost', accountPk, ticker] }),
    queryClient.invalidateQueries({ queryKey: ['position-costs', accountPk] }),
  ]);

  const canSaveAvgAndShares = avgCost.trim() !== '' && totalShares.trim() !== '';
  const upsertMut = useMutation({
    mutationFn: () => {
      // Refuse to silently zero-overwrite cost basis on empty input. The
      // user must enter both avg cost and total shares (or use "Add buy"
      // for incremental). Setting only stops/TP through this form is not
      // supported — that path also requires both anchor values.
      if (!canSaveAvgAndShares) {
        throw new Error('avg_cost_basis and total_shares are required');
      }
      return upsertPositionCost({
        broker_account_id: accountPk, ticker,
        avg_cost_basis: Number.parseFloat(avgCost),
        total_shares: Number.parseFloat(totalShares),
        custom_stop_loss: stopLoss === '' ? null : Number.parseFloat(stopLoss),
        custom_take_profit: takeProfit === '' ? null : Number.parseFloat(takeProfit),
        notes,
      });
    },
    onSuccess: async () => { await invalidate(); },
  });
  const buyMut = useMutation({
    mutationFn: () => recordPositionBuy({
      broker_account_id: accountPk, ticker,
      fill_price: Number.parseFloat(buyPrice),
      fill_qty: Number.parseFloat(buyQty),
    }),
    onSuccess: async () => {
      await invalidate();
      setBuyPrice(''); setBuyQty('');
    },
  });
  const deleteMut = useMutation({
    mutationFn: () => deletePositionCost(accountPk, ticker),
    onSuccess: async () => {
      await invalidate();
      if (onClose) onClose();
    },
  });

  if (ctxQ.isLoading) return <LoadingState rows={3} />;
  if (ctxQ.isError && !isNotFound) return <ErrorState error={ctxQ.error} onRetry={ctxQ.refetch} />;

  return (
    <div className="border border-border-subtle p-4 space-y-3 bg-elevated">
      <div className="flex items-baseline justify-between">
        <div className="font-mono text-[11px] tracking-[0.15em] uppercase text-text-muted">
          Cost basis · {ticker}
        </div>
        {onClose && (
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={14} /></button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Avg cost basis" value={avgCost} onChange={setAvgCost} placeholder="180.00" />
        <Field label="Total shares" value={totalShares} onChange={setTotalShares} placeholder="10" />
        <Field label="Custom stop-loss" value={stopLoss} onChange={setStopLoss} placeholder="—" />
        <Field label="Custom take-profit" value={takeProfit} onChange={setTakeProfit} placeholder="—" />
      </div>
      <div>
        <FieldLabel>Notes</FieldLabel>
        <textarea className="input min-h-[64px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>

      <div className="flex items-center gap-2">
        <button className="btn-primary btn-sm inline-flex items-center gap-1"
          onClick={() => upsertMut.mutate()}
          disabled={upsertMut.isPending || !canSaveAvgAndShares}
          title={canSaveAvgAndShares ? 'Save cost basis' : 'Enter avg cost AND total shares first'}>
          <Save size={12} /> Save
        </button>
        {existing && (
          <button className="btn-destructive btn-sm inline-flex items-center gap-1"
            onClick={() => {
              if (typeof window !== 'undefined' && window.confirm(`Clear cost basis for ${ticker}?`)) {
                deleteMut.mutate();
              }
            }}
            disabled={deleteMut.isPending}>
            <Trash2 size={12} /> Clear
          </button>
        )}
      </div>

      <div className="border-t border-border-subtle pt-3">
        <FieldLabel>Record a buy (auto-recomputes avg)</FieldLabel>
        <div className="grid grid-cols-3 gap-2">
          <input className="input" type="number" step="0.01" placeholder="Fill price"
            value={buyPrice} onChange={(e) => setBuyPrice(e.target.value)} />
          <input className="input" type="number" step="0.0001" placeholder="Fill qty"
            value={buyQty} onChange={(e) => setBuyQty(e.target.value)} />
          <button className="btn-secondary btn-sm"
            onClick={() => buyMut.mutate()}
            disabled={buyMut.isPending || !buyPrice || !buyQty}>
            Add buy
          </button>
        </div>
      </div>

      {(upsertMut.isError || buyMut.isError || deleteMut.isError) && (
        <div className="mt-2"><ErrorState error={upsertMut.error || buyMut.error || deleteMut.error} /></div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder }) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <input type="number" step="0.01" className="input tabular"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

function FieldLabel({ children }) {
  return (
    <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">
      {children}
    </div>
  );
}
