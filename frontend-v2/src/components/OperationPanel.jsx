// OperationPanel — paper-trade sandbox: pick contract, see entry/exit/Greeks impact + RR.
// Pure frontend; uses bsm.js (Black-Scholes) for client-side Greeks and scenario pricing.
import { useEffect, useMemo, useState } from 'react';
import { Calculator, TrendingUp } from 'lucide-react';
import { SectionHeader, EmptyState } from './primitives.jsx';
import { classNames, fmtUsd } from '../lib/format.js';
import { greeks, priceOption } from '../lib/bsm.js';

const CONTRACT_MULTIPLIER = 100;

/**
 * @param {{ ticker: string, expiry: string, spot: number|undefined, expiryFocus: any }} props
 */
export default function OperationPanel({ ticker, expiry, spot, expiryFocus }) {
  const choices = useMergedStrikes(expiryFocus);
  const [side, setSide] = useState('call');
  const [strikeChoice, setStrikeChoice] = useState(null);
  const [exitSpotPct, setExitSpotPct] = useState(0);
  const dte = expiryFocus?.dte ?? 0;
  const [daysToExit, setDaysToExit] = useState(0);
  const [ivShiftPct, setIvShiftPct] = useState(0);
  const [stopSpot, setStopSpot] = useState('');
  const [targetSpot, setTargetSpot] = useState('');

  // Reset selection whenever the chain (expiry/ticker) changes — a strike from
  // expiry A is meaningless against expiry B's strike list and would silently
  // fall through to atm_iv if we left it.
  useEffect(() => {
    setStrikeChoice(null);
  }, [expiryFocus]);

  const selectedRow = useMemo(() => {
    if (strikeChoice == null) return null;
    return choices.find((c) => c.strike === strikeChoice && c.bucket === side) ?? null;
  }, [choices, strikeChoice, side]);

  if (!spot || !expiryFocus) {
    return <EmptyState icon={Calculator} title="OPERATION PANEL" hint="Waiting for spot + expiry focus data..." />;
  }

  const sigma = selectedRow?.iv ?? expiryFocus.atm_iv ?? 0.3;
  const tYears = Math.max(dte / 365, 1 / 365);
  const current = selectedRow
    ? greeks({ spot, strike: selectedRow.strike, t: tYears, sigma, side })
    : null;

  const exitSpot = spot * (1 + exitSpotPct / 100);
  const exitT = Math.max((dte - daysToExit) / 365, 0.5 / 365);
  const exitSigma = Math.max(sigma + ivShiftPct / 100, 0.01);
  const exitPrice = selectedRow
    ? priceOption({ spot: exitSpot, strike: selectedRow.strike, t: exitT, sigma: exitSigma, side })
    : 0;
  const entryPrice = current?.price ?? 0;
  const pnlPerContract = (exitPrice - entryPrice) * CONTRACT_MULTIPLIER;
  const pnlPct = entryPrice > 0 ? ((exitPrice - entryPrice) / entryPrice) * 100 : 0;

  const stopNum = parseFloat(stopSpot);
  const targetNum = parseFloat(targetSpot);
  const rr = computeRr({ selectedRow, side, spot, sigma, tYears, dte, daysToExit, ivShiftPct, stopNum, targetNum });

  return (
    <div className="card">
      <SectionHeader
        title="OPERATION PANEL"
        subtitle="Paper-trade sandbox · client-side BSM"
        meta={<span className="font-mono text-[10px] tracking-[0.15em] text-text-muted uppercase">{ticker} · {expiry}</span>}
      />

      <div className="space-y-5">
        <div>
          <Label>Side</Label>
          <div className="flex gap-2">
            {['call', 'put'].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => { setSide(s); setStrikeChoice(null); }}
                className={classNames('btn-sm', side === s ? 'btn-primary' : 'btn-secondary')}
              >
                {s.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div>
          <Label>Strike (top {side}s by OI)</Label>
          <div className="flex flex-wrap gap-2">
            {choices.filter((c) => c.bucket === side).map((c) => (
              <button
                key={c.strike}
                type="button"
                onClick={() => setStrikeChoice(c.strike)}
                className={classNames('btn-sm', strikeChoice === c.strike ? 'btn-primary' : 'btn-secondary')}
              >
                {fmtUsd(c.strike)}
              </button>
            ))}
            {choices.filter((c) => c.bucket === side).length === 0 && (
              <span className="text-caption text-text-muted">No top strikes available.</span>
            )}
          </div>
        </div>

        {!selectedRow ? (
          <EmptyState icon={Calculator} title="SELECT A STRIKE" hint="Pick a strike above to compute Greeks and run scenarios." />
        ) : (
          <>
            <Block title="Selected contract">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-px bg-border-subtle">
                <Stat label="Ticker" value={ticker} />
                <Stat label="Expiry" value={expiry} />
                <Stat label="Strike" value={fmtUsd(selectedRow.strike)} />
                <Stat label="Side" value={side.toUpperCase()} tone={side === 'call' ? 'bull' : 'bear'} />
                <Stat label="DTE / IV" value={`${dte}d · ${(sigma * 100).toFixed(1)}%`} />
              </div>
            </Block>

            <Block title="Current Greeks">
              <div className="grid grid-cols-2 md:grid-cols-6 gap-px bg-border-subtle">
                <Stat label="Price" value={fmtUsd(current.price)} />
                <Stat label="Delta" value={current.delta.toFixed(3)} />
                <Stat label="Gamma" value={current.gamma.toFixed(4)} />
                <Stat label="Theta/d" value={current.theta.toFixed(3)} />
                <Stat label="Vega" value={current.vega.toFixed(3)} />
                <Stat label="Rho" value={current.rho.toFixed(3)} />
              </div>
            </Block>

            <Block title="Scenario inputs">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <Label>Target spot move (%)</Label>
                  <input
                    type="number"
                    step="0.1"
                    className="input tabular"
                    value={exitSpotPct}
                    onChange={(e) => setExitSpotPct(parseFloat(e.target.value) || 0)}
                  />
                  <div className="flex flex-wrap gap-1 mt-2">
                    {[-5, -2, -1, 1, 2, 5].map((p) => (
                      <button key={p} type="button" className="btn-sm btn-secondary" onClick={() => setExitSpotPct(p)}>
                        {p > 0 ? `+${p}%` : `${p}%`}
                      </button>
                    ))}
                  </div>
                  <div className="text-caption text-text-muted mt-1">Exit spot: {fmtUsd(exitSpot)}</div>
                </div>
                <div>
                  <Label>Days to exit ({daysToExit}/{dte})</Label>
                  <input
                    type="range" min={0} max={Math.max(dte, 0)} step={1}
                    value={daysToExit}
                    onChange={(e) => setDaysToExit(parseInt(e.target.value, 10))}
                    className="w-full"
                  />
                </div>
                <div>
                  <Label>IV shift ({ivShiftPct >= 0 ? '+' : ''}{ivShiftPct}pp)</Label>
                  <input
                    type="range" min={-10} max={10} step={0.5}
                    value={ivShiftPct}
                    onChange={(e) => setIvShiftPct(parseFloat(e.target.value))}
                    className="w-full"
                  />
                </div>
              </div>
            </Block>

            <Block title="Scenario result" icon={TrendingUp}>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-border-subtle">
                <Stat label="Exit price" value={fmtUsd(exitPrice)} />
                <Stat label="P&L / contract" value={fmtUsd(pnlPerContract)} tone={pnlPerContract >= 0 ? 'bull' : 'bear'} />
                <Stat label="P&L %" value={`${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%`} tone={pnlPct >= 0 ? 'bull' : 'bear'} />
                <Stat label="Entry mid" value={fmtUsd(entryPrice)} />
              </div>
            </Block>

            <Block title="Risk / Reward">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-3">
                <div>
                  <Label>Stop spot (underlying)</Label>
                  <input type="number" step="0.01" className="input tabular" value={stopSpot}
                    onChange={(e) => setStopSpot(e.target.value)} placeholder={fmtUsd(spot * 0.98)} />
                </div>
                <div>
                  <Label>Target spot (underlying)</Label>
                  <input type="number" step="0.01" className="input tabular" value={targetSpot}
                    onChange={(e) => setTargetSpot(e.target.value)} placeholder={fmtUsd(spot * 1.02)} />
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-px bg-border-subtle">
                <Stat label="Max profit" value={rr.maxProfit != null ? fmtUsd(rr.maxProfit) : '—'} tone="bull" />
                <Stat label="Max loss" value={rr.maxLoss != null ? fmtUsd(rr.maxLoss) : '—'} tone="bear" />
                <Stat label="RR ratio" value={rr.ratio != null ? `${rr.ratio.toFixed(2)} : 1` : '—'} />
              </div>
            </Block>
          </>
        )}
      </div>
    </div>
  );
}

function useMergedStrikes(expiryFocus) {
  return useMemo(() => {
    const calls = (expiryFocus?.top_call_strikes || []).map((r) => ({ ...r, bucket: 'call' }));
    const puts = (expiryFocus?.top_put_strikes || []).map((r) => ({ ...r, bucket: 'put' }));
    return [...calls, ...puts];
  }, [expiryFocus]);
}

function computeRr({ selectedRow, side, spot, sigma, tYears, dte, daysToExit, ivShiftPct, stopNum, targetNum }) {
  if (!selectedRow || !Number.isFinite(stopNum) || !Number.isFinite(targetNum)) {
    return { maxProfit: null, maxLoss: null, ratio: null };
  }
  const exitT = Math.max((dte - daysToExit) / 365, 0.5 / 365);
  const exitSigma = Math.max(sigma + ivShiftPct / 100, 0.01);
  const entry = priceOption({ spot, strike: selectedRow.strike, t: tYears, sigma, side });
  const atTarget = priceOption({ spot: targetNum, strike: selectedRow.strike, t: exitT, sigma: exitSigma, side });
  const atStop = priceOption({ spot: stopNum, strike: selectedRow.strike, t: exitT, sigma: exitSigma, side });
  const maxProfit = (atTarget - entry) * CONTRACT_MULTIPLIER;
  const maxLoss = (atStop - entry) * CONTRACT_MULTIPLIER;
  const ratio = maxLoss < 0 ? Math.abs(maxProfit / maxLoss) : null;
  return { maxProfit, maxLoss, ratio };
}

function Label({ children }) {
  return <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-2">{children}</div>;
}

function Block({ title, icon: Icon, children }) {
  return (
    <div>
      <div className="font-mono text-[11px] text-text-muted tracking-[0.15em] uppercase mb-2 flex items-center gap-2">
        {Icon && <Icon size={12} />} {title}
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, tone = 'primary' }) {
  const toneClass =
    tone === 'bull' ? 'text-bull' :
    tone === 'bear' ? 'text-bear' :
    'text-text-primary';
  return (
    <div className="bg-surface px-4 py-3">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">{label}</div>
      <div className={classNames('font-display text-[16px] tabular leading-tight', toneClass)}>{value}</div>
    </div>
  );
}
