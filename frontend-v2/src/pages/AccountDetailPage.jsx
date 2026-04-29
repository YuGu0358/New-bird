// AccountDetailPage — Phase 2.5 single-account drill-down: alias/tier edit,
// latest position snapshots, per-position override editor, and a link out to
// the options chain for the deeper trade simulator.
import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Save, Trash2, ExternalLink } from 'lucide-react';
import { PageHeader, SectionHeader, LoadingState, ErrorState, EmptyState } from '../components/primitives.jsx';
import {
  getBrokerAccount, updateBrokerAccountAlias, updateBrokerAccountTier,
  listAccountSnapshots, getOverride, upsertOverride, deleteOverride,
} from '../lib/api.js';
import { fmtUsd, fmtSignedUsd, fmtPct, classNames } from '../lib/format.js';

const TIER_OPTIONS = ['TIER_1', 'TIER_2', 'TIER_3'];

/**
 * @typedef {{ id: number, broker: string, account_id: string, alias: string,
 *   tier: 'TIER_1'|'TIER_2'|'TIER_3', is_active: boolean }} BrokerAccount
 * @typedef {{ id: number, broker_account_id: number, symbol: string,
 *   snapshot_at: string, qty: number, avg_cost: number|null,
 *   market_value: number|null, current_price: number|null,
 *   unrealized_pl: number|null, side: string }} PositionSnapshot
 * @typedef {{ id: number, broker_account_id: number, ticker: string,
 *   stop_price: number|null, take_profit_price: number|null,
 *   notes: string|null, tier_override: string|null }} PositionOverride
 */

export default function AccountDetailPage() {
  const { id } = useParams();
  const accountPk = Number.parseInt(id ?? '', 10);
  const isValidId = Number.isFinite(accountPk) && accountPk > 0;

  const [selectedTicker, setSelectedTicker] = useState(/** @type {string|null} */ (null));

  const accountQ = useQuery({
    queryKey: ['broker-account', accountPk],
    queryFn: () => getBrokerAccount(accountPk),
    enabled: isValidId,
  });

  const snapshotsQ = useQuery({
    queryKey: ['account-snapshots', accountPk],
    queryFn: () => listAccountSnapshots(accountPk),
    enabled: isValidId,
    refetchInterval: 30_000,
  });

  if (!isValidId) {
    return (
      <div className="space-y-6">
        <BackLink />
        <ErrorState error={{ message: `Invalid account id: ${id}` }} />
      </div>
    );
  }

  if (accountQ.isLoading) return <div className="space-y-6"><BackLink /><LoadingState rows={6} /></div>;
  if (accountQ.isError) return <div className="space-y-6"><BackLink /><ErrorState error={accountQ.error} onRetry={accountQ.refetch} /></div>;

  /** @type {BrokerAccount} */
  const account = accountQ.data;
  const latestRows = pickLatestPerSymbol(snapshotsQ.data?.items ?? []);
  const selectedRow = latestRows.find((r) => r.symbol === selectedTicker) ?? null;

  const segments = [
    { label: account.broker.toUpperCase() },
    { label: account.tier, accent: true },
    { label: account.is_active ? 'ACTIVE' : 'INACTIVE' },
  ];
  const posMeta = <span className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase">{latestRows.length} symbols</span>;
  const opMeta = <span className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase">{selectedTicker} · {selectedRow?.current_price != null ? fmtUsd(selectedRow.current_price) : '—'}</span>;
  return (
    <div className="space-y-8">
      <BackLink />
      <PageHeader moduleId={3} title={`Account · ${account.alias || account.account_id}`} segments={segments} />
      <AccountEditor account={account} />
      <div className="card">
        <SectionHeader title="POSITIONS" subtitle="Latest snapshot per symbol" meta={posMeta} />
        <PositionsTable rows={latestRows} loading={snapshotsQ.isLoading} error={snapshotsQ.error}
          isError={snapshotsQ.isError} onRetry={snapshotsQ.refetch}
          selectedTicker={selectedTicker} onSelect={setSelectedTicker} />
      </div>
      {selectedTicker && (
        <OverrideEditor accountPk={accountPk} ticker={selectedTicker} onClear={() => setSelectedTicker(null)} />
      )}
      {selectedTicker && (
        <div className="card">
          <SectionHeader title="OPERATION PANEL" subtitle="Open this ticker in the options chain to run scenarios" meta={opMeta} />
          <Link to={`/options?ticker=${encodeURIComponent(selectedTicker)}`}
            className="btn-primary btn-sm inline-flex items-center gap-2">
            <ExternalLink size={12} /> Open {selectedTicker} in Options Chain
          </Link>
          <div className="text-caption text-text-muted mt-3">
            The OperationPanel needs an expiry focus from a chain query; we link out instead of inlining an empty sandbox.
          </div>
        </div>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/portfolio" className="inline-flex items-center gap-2 text-body-sm text-text-secondary hover:text-cyan">
      <ArrowLeft size={14} /> Back to portfolio
    </Link>
  );
}

/** @param {{ account: BrokerAccount }} props */
function AccountEditor({ account }) {
  const queryClient = useQueryClient();
  const [alias, setAlias] = useState(account.alias ?? '');
  const [tier, setTier] = useState(account.tier);

  useEffect(() => {
    setAlias(account.alias ?? '');
    setTier(account.tier);
  }, [account.alias, account.tier]);

  const aliasMut = useMutation({
    mutationFn: (next) => updateBrokerAccountAlias(account.id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['broker-account', account.id] }),
  });
  const tierMut = useMutation({
    mutationFn: (next) => updateBrokerAccountTier(account.id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['broker-account', account.id] }),
  });

  const isDirty = alias !== (account.alias ?? '') || tier !== account.tier;
  const isPending = aliasMut.isPending || tierMut.isPending;

  const onSave = async () => {
    // Catch here so a failing alias mutation doesn't skip tier (or vice versa
    // via unhandled rejection). Each mutation surfaces its own error in the
    // ErrorState row below; we just need to keep the function from rejecting.
    try {
      if (alias !== (account.alias ?? '')) await aliasMut.mutateAsync(alias);
    } catch { /* error rendered via aliasMut.isError */ }
    try {
      if (tier !== account.tier) await tierMut.mutateAsync(tier);
    } catch { /* error rendered via tierMut.isError */ }
  };

  return (
    <div className="card">
      <SectionHeader title="ACCOUNT" subtitle="Alias + tier" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <FieldLabel>Alias</FieldLabel>
          <input type="text" className="input" value={alias}
            onChange={(e) => setAlias(e.target.value)} placeholder={account.account_id} />
        </div>
        <div>
          <FieldLabel>Tier</FieldLabel>
          <select className="select" value={tier} onChange={(e) => setTier(e.target.value)}>
            {TIER_OPTIONS.map((t) => (<option key={t} value={t}>{t}</option>))}
          </select>
        </div>
        <div className="flex items-end">
          <button type="button" className="btn-primary btn-sm inline-flex items-center gap-2"
            onClick={onSave} disabled={!isDirty || isPending}>
            <Save size={12} /> Save changes
          </button>
        </div>
      </div>
      {(aliasMut.isError || tierMut.isError) && (
        <div className="mt-3"><ErrorState error={aliasMut.error || tierMut.error} /></div>
      )}
    </div>
  );
}

/** @param {{ rows: PositionSnapshot[], loading: boolean, isError: boolean,
 *  error: unknown, onRetry: () => void, selectedTicker: string|null,
 *  onSelect: (s: string) => void }} props */
function PositionsTable({ rows, loading, isError, error, onRetry, selectedTicker, onSelect }) {
  if (loading) return <LoadingState rows={5} />;
  if (isError) return <ErrorState error={error} onRetry={onRetry} />;
  if (!rows.length) return <EmptyState title="NO POSITIONS" hint="No snapshots have been recorded for this account yet." />;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Ticker</th>
          <th className="tbl-num">Qty</th>
          <th className="tbl-num">Avg cost</th>
          <th className="tbl-num">Mark</th>
          <th className="tbl-num">Unreal P/L</th>
          <th className="tbl-num">% move</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const avg = r.avg_cost ?? 0;
          const mark = r.current_price ?? avg;
          const upl = r.unrealized_pl ?? (avg > 0 ? (mark - avg) * r.qty : 0);
          const pct = avg > 0 ? ((mark - avg) / avg) * 100 : 0;
          const isSel = selectedTicker === r.symbol;
          return (
            <tr
              key={r.symbol}
              onClick={() => onSelect(r.symbol)}
              className={classNames('cursor-pointer', isSel ? 'bg-elevated' : 'hover:bg-elevated/50')}
            >
              <td className="font-medium text-steel-50">{r.symbol}</td>
              <td className="tbl-num">{Number(r.qty).toFixed(4)}</td>
              <td className="tbl-num">{fmtUsd(avg)}</td>
              <td className="tbl-num">{fmtUsd(mark)}</td>
              <td className={classNames('tbl-num font-medium', upl > 0 ? 'text-bull' : upl < 0 ? 'text-bear' : '')}>
                {fmtSignedUsd(upl)}
              </td>
              <td className={classNames('tbl-num font-medium', pct > 0 ? 'text-bull' : pct < 0 ? 'text-bear' : '')}>
                {fmtPct(pct)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** @param {{ accountPk: number, ticker: string, onClear: () => void }} props */
function OverrideEditor({ accountPk, ticker, onClear }) {
  const queryClient = useQueryClient();

  const overrideQ = useQuery({
    queryKey: ['override', accountPk, ticker],
    queryFn: () => getOverride(accountPk, ticker),
    retry: false,
  });

  // 404 = "no override exists yet" (the NEW form path) and is expected; any
  // other status is a real failure we should surface. ApiError attaches the
  // HTTP status as `.status` (see lib/api.js).
  const isNotFound = overrideQ.isError && /** @type {any} */ (overrideQ.error)?.status === 404;
  const existing = /** @type {PositionOverride|undefined} */ (
    isNotFound ? undefined : (overrideQ.isError ? undefined : overrideQ.data)
  );

  const [notes, setNotes] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [tierOverride, setTierOverride] = useState('');

  useEffect(() => {
    setNotes(existing?.notes ?? '');
    setStopPrice(existing?.stop_price != null ? String(existing.stop_price) : '');
    setTakeProfit(existing?.take_profit_price != null ? String(existing.take_profit_price) : '');
    setTierOverride(existing?.tier_override ?? '');
  }, [existing]);

  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['override', accountPk, ticker] }),
    queryClient.invalidateQueries({ queryKey: ['overrides', accountPk] }),
  ]);

  const upsertMut = useMutation({
    mutationFn: (payload) => upsertOverride(payload),
    onSuccess: async () => { await invalidate(); },
  });
  const deleteMut = useMutation({
    mutationFn: () => deleteOverride(accountPk, ticker),
    onSuccess: async () => { await invalidate(); onClear(); },
  });

  const onSave = () => {
    const payload = {
      broker_account_id: accountPk,
      ticker,
      notes: notes.trim() || null,
      stop_price: stopPrice === '' ? null : Number.parseFloat(stopPrice),
      take_profit_price: takeProfit === '' ? null : Number.parseFloat(takeProfit),
      tier_override: tierOverride || null,
    };
    upsertMut.mutate(payload);
  };

  const onDelete = () => {
    if (!existing) return;
    if (typeof window !== 'undefined' && !window.confirm(`Delete override for ${ticker}?`)) return;
    deleteMut.mutate();
  };

  const metaTag = <span className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase">{existing ? 'EDIT' : 'NEW'}</span>;
  return (
    <div className="card">
      <SectionHeader title="OVERRIDE" subtitle={`Per-position rules for ${ticker}`} meta={metaTag} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <FieldLabel>Stop price</FieldLabel>
          <input type="number" step="0.01" className="input tabular" value={stopPrice}
            onChange={(e) => setStopPrice(e.target.value)} placeholder="—" />
        </div>
        <div>
          <FieldLabel>Take-profit price</FieldLabel>
          <input type="number" step="0.01" className="input tabular" value={takeProfit}
            onChange={(e) => setTakeProfit(e.target.value)} placeholder="—" />
        </div>
        <div>
          <FieldLabel>Tier override</FieldLabel>
          <select className="select" value={tierOverride} onChange={(e) => setTierOverride(e.target.value)}>
            <option value="">(use account tier)</option>
            {TIER_OPTIONS.map((t) => (<option key={t} value={t}>{t}</option>))}
          </select>
        </div>
        <div className="md:col-span-2">
          <FieldLabel>Notes</FieldLabel>
          <textarea className="input min-h-[72px]" value={notes}
            onChange={(e) => setNotes(e.target.value)} placeholder="Free-form trading notes" />
        </div>
      </div>
      <div className="flex items-center gap-2 mt-4">
        <button type="button" className="btn-primary btn-sm inline-flex items-center gap-2"
          onClick={onSave} disabled={upsertMut.isPending}><Save size={12} /> Save override</button>
        {existing && (
          <button type="button" className="btn-destructive btn-sm inline-flex items-center gap-2"
            onClick={onDelete} disabled={deleteMut.isPending}><Trash2 size={12} /> Delete</button>
        )}
        <button type="button" className="btn-secondary btn-sm" onClick={onClear}>Close</button>
      </div>
      {(upsertMut.isError || deleteMut.isError || (overrideQ.isError && !isNotFound)) && (
        <div className="mt-3"><ErrorState error={upsertMut.error || deleteMut.error || overrideQ.error} /></div>
      )}
    </div>
  );
}

function FieldLabel({ children }) {
  return <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-2">{children}</div>;
}

/** @param {PositionSnapshot[]} items @returns {PositionSnapshot[]} */
function pickLatestPerSymbol(items) {
  /** @type {Map<string, PositionSnapshot>} */
  const bySymbol = new Map();
  for (const row of items) {
    const prev = bySymbol.get(row.symbol);
    if (!prev || new Date(row.snapshot_at).getTime() > new Date(prev.snapshot_at).getTime()) {
      bySymbol.set(row.symbol, row);
    }
  }
  return Array.from(bySymbol.values()).sort((a, b) => a.symbol.localeCompare(b.symbol));
}
