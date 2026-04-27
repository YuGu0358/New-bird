// Reusable presentational primitives: KPI card, empty/error/loading state,
// section heading, sparkline-only chart, status pill helpers.

import { ArrowUpRight, ArrowDownRight, Loader2, Inbox, ServerCrash } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import { classNames, fmtPct } from '../lib/format.js';

export function SectionHeader({ title, subtitle, action }) {
  return (
    <div className="flex items-end justify-between mb-4">
      <div>
        <h2 className="h-section">{title}</h2>
        {subtitle && <p className="text-body-sm text-steel-200 mt-1">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function KpiCard({ label, value, delta, deltaLabel, loading, sparkline }) {
  const positive = typeof delta === 'number' && delta > 0;
  const negative = typeof delta === 'number' && delta < 0;
  return (
    <div className="card flex flex-col">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="metric-caption">{label}</div>
          <div className="metric-value mt-1">
            {loading ? <span className="text-steel-300 text-body">loading…</span> : value}
          </div>
          {delta !== undefined && delta !== null && (
            <div
              className={classNames(
                'mt-2 flex items-center gap-1 text-body-sm font-medium tabular',
                positive ? 'text-bull' : negative ? 'text-bear' : 'text-steel-200'
              )}
            >
              {positive ? <ArrowUpRight size={14} /> : negative ? <ArrowDownRight size={14} /> : null}
              <span>{typeof delta === 'number' ? fmtPct(delta) : delta}</span>
              {deltaLabel && <span className="text-steel-200 font-normal">{deltaLabel}</span>}
            </div>
          )}
        </div>
        {sparkline && (
          <div className="w-24 h-10 -mt-1 -mr-1 shrink-0">
            <Sparkline data={sparkline} positive={!negative} />
          </div>
        )}
      </div>
    </div>
  );
}

export function Sparkline({ data, positive = true }) {
  if (!data || data.length === 0) return null;
  const colour = positive ? '#26D9A5' : '#FF5C7A';
  const points = data.map((v, i) => ({ x: i, y: v }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={points} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`spark-${positive ? 'up' : 'dn'}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colour} stopOpacity={0.6} />
            <stop offset="100%" stopColor={colour} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="y" stroke={colour} strokeWidth={1.5} fill={`url(#spark-${positive ? 'up' : 'dn'})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function LoadingState({ rows = 3, label = 'Loading…' }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-steel-200 text-body-sm">
        <Loader2 size={14} className="animate-spin" /> {label}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-9 bg-ink-700 rounded animate-pulse" />
      ))}
    </div>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, hint }) {
  return (
    <div className="border border-dashed border-steel-400 rounded-lg py-10 px-6 flex flex-col items-center text-center">
      <Icon size={28} className="text-steel-300 mb-3" strokeWidth={1.5} />
      <div className="text-body text-steel-100 font-medium">{title}</div>
      {hint && <div className="text-body-sm text-steel-200 mt-1">{hint}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  const message = error?.detail?.toString() || error?.message || String(error);
  return (
    <div className="border border-bear/40 rounded-lg bg-bear-tint/40 p-5 flex items-start gap-3">
      <ServerCrash size={18} className="text-bear shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-body font-medium text-bear">数据源不可用</div>
        <div className="text-body-sm text-steel-200 mt-1 break-all">{message}</div>
      </div>
      {onRetry && (
        <button className="btn-secondary btn-sm shrink-0" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

export function StatusBadge({ status }) {
  const map = {
    completed: 'pill-bull',
    running: 'pill-active',
    failed: 'pill-bear',
    pending: 'pill-warn',
    new: 'pill-default',
    filled: 'pill-bull',
    canceled: 'pill-default',
    expired: 'pill-default',
    rejected: 'pill-bear',
    accepted: 'pill-default',
  };
  const cls = map[(status || '').toLowerCase()] || 'pill-default';
  return <span className={cls}>{status || '—'}</span>;
}

export function PageError({ error, retry }) {
  return (
    <div className="max-w-2xl">
      <ErrorState error={error} onRetry={retry} />
    </div>
  );
}
