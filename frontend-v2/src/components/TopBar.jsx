import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Play, Square, RefreshCw, ShieldCheck, ShieldOff, AlertCircle } from 'lucide-react';
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

export default function TopBar() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const accountQ = useQuery({ queryKey: ['account'], queryFn: getAccount, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['strategy-health'], queryFn: getStrategyHealth, refetchInterval: 30_000 });
  const botQ = useQuery({ queryKey: ['bot-status'], queryFn: getBotStatus, refetchInterval: 5_000 });
  const riskQ = useQuery({ queryKey: ['risk-policies'], queryFn: getRiskPolicies, refetchInterval: 60_000 });

  const startMut = useMutation({ mutationFn: startBot, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bot-status'] }) });
  const stopMut = useMutation({ mutationFn: stopBot, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bot-status'] }) });

  const equity = accountQ.data?.equity;
  const lastEquity = accountQ.data?.last_equity;
  const equityDelta = equity != null && lastEquity != null && lastEquity !== 0
    ? ((equity - lastEquity) / lastEquity) * 100
    : null;

  const realizedToday = healthQ.data?.realized_pnl_today ?? 0;
  const isRunning = !!botQ.data?.is_running;
  const riskEnabled = !!riskQ.data?.enabled;

  return (
    <header className="h-14 px-6 border-b border-steel-400 bg-ink-900 flex items-center justify-between">
      <div className="flex items-center gap-8">
        <Metric label={t('topbar.equity')} value={fmtUsd(equity)} delta={equityDelta} loading={accountQ.isLoading} />
        <Metric
          label={t('topbar.todayPnl')}
          value={fmtSignedUsd(realizedToday)}
          valueColor={realizedToday > 0 ? 'text-bull' : realizedToday < 0 ? 'text-bear' : 'text-steel-50'}
          loading={healthQ.isLoading}
        />
        <Metric label={t('topbar.openPositions')} value={String(healthQ.data?.open_position_count ?? '—')} loading={healthQ.isLoading} />
      </div>

      <div className="flex items-center gap-3">
        <RiskBadge enabled={riskEnabled} loading={riskQ.isLoading} t={t} />
        <BotBadge running={isRunning} loading={botQ.isLoading} t={t} />
        {isRunning ? (
          <button
            className="btn-destructive btn-sm"
            onClick={() => stopMut.mutate()}
            disabled={stopMut.isPending}
          >
            <Square size={14} /> {t('topbar.stopBot')}
          </button>
        ) : (
          <button
            className="btn-primary btn-sm"
            onClick={() => startMut.mutate()}
            disabled={startMut.isPending}
          >
            <Play size={14} /> {t('topbar.startBot')}
          </button>
        )}
        <button
          className="btn-ghost btn-sm"
          title={t('topbar.refreshAll')}
          onClick={() => queryClient.invalidateQueries()}
        >
          <RefreshCw size={14} />
        </button>
        <LanguageSwitcher />
      </div>
    </header>
  );
}

function Metric({ label, value, delta, valueColor = 'text-steel-50', loading }) {
  return (
    <div className="flex flex-col">
      <span className="h-caption">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className={classNames('text-num-md font-semibold tabular', valueColor)}>
          {loading ? <span className="text-steel-300">…</span> : value}
        </span>
        {delta != null && (
          <span className={classNames('text-body-sm tabular font-medium', deltaClass(delta))}>
            {delta > 0 ? '+' : ''}
            {delta.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  );
}

function BotBadge({ running, loading, t }) {
  if (loading) return <span className="pill-default">Bot …</span>;
  return running ? (
    <span className="pill-bull">
      <span className="w-1.5 h-1.5 rounded-full bg-bull mr-1.5 animate-pulse" /> {t('topbar.botRunning')}
    </span>
  ) : (
    <span className="pill-default">{t('topbar.botIdle')}</span>
  );
}

function RiskBadge({ enabled, loading, t }) {
  if (loading) return <span className="pill-default">…</span>;
  return enabled ? (
    <span className="pill-active inline-flex items-center gap-1.5">
      <ShieldCheck size={12} /> {t('topbar.riskOn')}
    </span>
  ) : (
    <span className="pill-warn inline-flex items-center gap-1.5">
      <ShieldOff size={12} /> {t('topbar.riskOff')}
    </span>
  );
}

export function ApiErrorBanner({ error, label }) {
  const { t } = useTranslation();
  if (!error) return null;
  const message = error?.detail?.toString() || error?.message || String(error);
  return (
    <div className="border border-warn rounded-md bg-warn-tint px-4 py-2 flex items-center gap-2 text-body-sm text-warn">
      <AlertCircle size={14} /> {label || t('common.errorState')}: {message}
    </div>
  );
}
