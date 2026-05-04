import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Play, Square, RefreshCw, AlertCircle } from 'lucide-react';
import {
  getAccount,
  getStrategyHealth,
  getBotStatus,
  startBot,
  stopBot,
  getRiskPolicies,
} from '../lib/api.js';
import { fmtUsd, fmtSignedUsd, deltaClass, classNames } from '../lib/format.js';
import LanguageSwitcher from './LanguageSwitcher.jsx';

/**
 * TopBar layout:
 *
 *  ┌──────────────────────────────────────────────────────────────────┐
 *  │ SYS // MODULE.XX · PORTFOLIO       ● LIVE · IBKR-Uxxxx  Time  Day│  ← crumb row
 *  ├──────────────────────────────────────────────────────────────────┤
 *  │ [Equity 12,432] [Day P&L +341] [Open 5]  [start bot] [refresh] [lang]
 *  └──────────────────────────────────────────────────────────────────┘
 */
export default function TopBar() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const accountQ = useQuery({ queryKey: ['account'], queryFn: getAccount, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['strategy-health'], queryFn: getStrategyHealth, refetchInterval: 30_000 });
  const botQ = useQuery({ queryKey: ['bot-status'], queryFn: getBotStatus, refetchInterval: 5_000 });
  const riskQ = useQuery({ queryKey: ['risk-policies'], queryFn: getRiskPolicies, refetchInterval: 60_000 });

  const startMut = useMutation({
    mutationFn: startBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
  });
  const stopMut = useMutation({
    mutationFn: stopBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
  });

  // Live clock
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const equity = accountQ.data?.equity;
  const lastEquity = accountQ.data?.last_equity;
  const equityDelta = equity != null && lastEquity != null && lastEquity !== 0
    ? ((equity - lastEquity) / lastEquity) * 100
    : null;

  const realizedToday = healthQ.data?.realized_pnl_today ?? 0;
  const isRunning = !!botQ.data?.is_running;
  const riskEnabled = !!riskQ.data?.enabled;

  return (
    <header className="border-b border-border-subtle bg-surface px-12 py-4 flex flex-col gap-3">
      {/* Crumb row */}
      <div className="flex items-center justify-between">
        <div className="crumb">SYS // {t('nav.brand').toUpperCase()} · {t('nav.tagline').toUpperCase()}</div>
        <div className="flex items-center gap-6 font-mono text-[10px] tracking-[0.15em] text-text-secondary uppercase">
          <span className="inline-flex items-center gap-2">
            <span
              className={classNames(
                'w-1.5 h-1.5',
                isRunning ? 'bg-cyan shadow-glow-cyan animate-pulse' : 'bg-text-muted',
              )}
            />
            <span>{isRunning ? t('topbar.botRunning') : t('topbar.botIdle')}</span>
          </span>
          <span>{riskEnabled ? `RISK · ON` : `RISK · OFF`}</span>
          <span>{now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
          <span>{now.toISOString().slice(0, 10)}</span>
        </div>
      </div>

      {/* Compact KPI + actions row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-10">
          <Metric
            label={t('topbar.equity')}
            value={fmtUsd(equity)}
            delta={equityDelta}
            loading={accountQ.isLoading}
          />
          <Metric
            label={t('topbar.todayPnl')}
            value={fmtSignedUsd(realizedToday)}
            valueColor={
              realizedToday > 0 ? 'text-profit'
              : realizedToday < 0 ? 'text-loss'
              : 'text-text-primary'
            }
            loading={healthQ.isLoading}
          />
          <Metric
            label={t('topbar.openPositions')}
            value={String(healthQ.data?.open_position_count ?? '—')}
            loading={healthQ.isLoading}
          />
        </div>

        <div className="flex items-center gap-2">
          {isRunning ? (
            <button
              className="btn-destructive btn-sm"
              onClick={() => stopMut.mutate()}
              disabled={stopMut.isPending}
            >
              <Square size={11} /> {t('topbar.stopBot')}
            </button>
          ) : (
            <button
              className="btn-primary btn-sm"
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
            >
              <Play size={11} /> {t('topbar.startBot')}
            </button>
          )}
          <button
            className="btn-ghost btn-sm"
            title={t('topbar.refreshAll')}
            onClick={() => queryClient.invalidateQueries()}
          >
            <RefreshCw size={12} />
          </button>
          <LanguageSwitcher />
        </div>
      </div>
    </header>
  );
}

function Metric({ label, value, delta, valueColor = 'text-text-primary', loading }) {
  return (
    <div className="flex flex-col">
      <span className="font-mono text-[10px] tracking-[0.15em] text-text-muted uppercase">{label}</span>
      <div className="flex items-baseline gap-2 mt-1">
        <span
          className={classNames(
            'font-mono tabular text-[18px] font-medium leading-none',
            valueColor,
          )}
        >
          {loading ? <span className="text-text-muted">…</span> : value}
        </span>
        {delta != null && (
          <span className={classNames('font-mono text-[10px] tabular tracking-tight', deltaClass(delta))}>
            {delta > 0 ? '▲ +' : delta < 0 ? '▼ ' : ''}
            {delta.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  );
}

export function ApiErrorBanner({ error, label }) {
  const { t } = useTranslation();
  if (!error) return null;
  const message = formatApiError(error);
  return (
    <div className="border border-warn px-4 py-2 flex items-start gap-2 font-mono text-[11px] text-warn tracking-wider uppercase">
      <AlertCircle size={14} className="shrink-0 mt-0.5" />
      <span>{label || t('common.errorState')}: <span className="break-all">{message}</span></span>
    </div>
  );
}

/** FastAPI's 422 response has detail as an array of {loc, msg, type} objects.
 *  503 / 500 usually returns a string detail. We normalise both, plus any
 *  other shape we might see, into a single readable line. */
function formatApiError(error) {
  if (!error) return '';
  const d = error.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        const loc = Array.isArray(entry?.loc) ? entry.loc.filter((p) => p !== 'body').join('.') : '';
        const msg = entry?.msg || JSON.stringify(entry);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join(' · ');
  }
  if (d && typeof d === 'object') return JSON.stringify(d);
  return error.message || String(error);
}
