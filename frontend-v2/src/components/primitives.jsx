// Shared presentational primitives for the Tradewell Tokyo aesthetic.
//
// Visual language:
//   - Pure black void background with subtle grid + noise overlays
//   - Sharp corners (no border-radius); decorative L-bracket frames on KPI cards
//   - Neon cyan (#14F1D9) primary accent with glow
//   - All numerics in JetBrains Mono (tabular)
//   - Section headers: Chakra Petch uppercase + monospace meta annotation
//   - Signal dots: glowing filled circles tied to status semantics

import {
  ArrowUpRight, ArrowDownRight, Loader2, Inbox, ServerCrash,
} from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import { classNames, fmtPct } from '../lib/format.js';

/* ---------------------------------------------------------- Section header */

export function SectionHeader({ title, subtitle, action, meta }) {
  return (
    <div className="section-head flex items-baseline justify-between mb-4">
      <div className="flex items-baseline gap-4">
        <h2 className="h-section">{title}</h2>
        {subtitle && <span className="font-mono text-[11px] text-text-secondary tracking-wider">{subtitle}</span>}
      </div>
      <div className="flex items-center gap-3">
        {meta && <span className="section-meta">{meta}</span>}
        {action}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- Crumb header (per-page) */

export function PageHeader({ moduleId, title, segments = [], live = true }) {
  return (
    <div className="mb-10">
      <div className="flex items-baseline justify-between mb-2">
        <div className="crumb">
          SYS // MODULE.{String(moduleId).padStart(2, '0')} · {(title || '').toUpperCase()}
        </div>
        {live && (
          <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase inline-flex items-center gap-2">
            <span className="w-1.5 h-1.5 bg-cyan shadow-glow-cyan animate-pulse" /> LIVE
          </div>
        )}
      </div>
      <h1 className="h-page">{title}</h1>
      {segments.length > 0 && (
        <div className="font-mono text-[12px] text-text-secondary tracking-wider mt-2 flex flex-wrap items-center gap-2">
          {segments.map((s, i) => (
            <span key={i} className="inline-flex items-center gap-2">
              {i > 0 && <span className="text-text-muted">//</span>}
              <span className={s.accent ? 'text-cyan' : ''}>{s.label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- KPI card */

export function KpiCard({ label, value, delta, deltaLabel, loading, sparkline, tag, tagTone = 'neutral' }) {
  const positive = typeof delta === 'number' && delta > 0;
  const negative = typeof delta === 'number' && delta < 0;
  const tagToneClass = {
    pos: 'text-profit',
    neg: 'text-loss',
    warn: 'text-warn',
    cyan: 'text-cyan',
    neutral: 'text-text-secondary',
  }[tagTone] || 'text-text-secondary';

  return (
    <div className="kpi card-bracket flex flex-col">
      <div className="kpi-label">
        <span>{label}</span>
        {tag && <span className={classNames('kpi-tag', tagToneClass)}>{tag}</span>}
      </div>
      <div
        className={classNames(
          'kpi-value',
          positive ? 'text-profit' : negative ? 'text-loss' : 'text-text-primary',
        )}
      >
        {loading ? <span className="text-text-muted text-[14px]">loading…</span> : value}
      </div>
      <div className="flex items-center justify-between gap-2">
        {delta !== undefined && delta !== null ? (
          <span
            className={classNames(
              'kpi-delta tabular',
              positive ? 'text-profit' : negative ? 'text-loss' : 'text-text-secondary',
            )}
          >
            {positive ? '▲ ' : negative ? '▼ ' : ''}
            {typeof delta === 'number' ? fmtPct(delta) : delta}
            {deltaLabel && <span className="text-text-muted ml-1">{deltaLabel}</span>}
          </span>
        ) : (
          <span />
        )}
        {sparkline && (
          <div className="w-20 h-7">
            <Sparkline data={sparkline} positive={!negative} />
          </div>
        )}
      </div>
    </div>
  );
}

export function Sparkline({ data, positive = true }) {
  if (!data || data.length === 0) return null;
  const colour = positive ? '#00D980' : '#FF3366';
  const points = data.map((v, i) => ({ x: i, y: v }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={points} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`spark-${positive ? 'up' : 'dn'}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={colour} stopOpacity={0.5} />
            <stop offset="100%" stopColor={colour} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="y"
          stroke={colour}
          strokeWidth={1.5}
          fill={`url(#spark-${positive ? 'up' : 'dn'})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ---------------------------------------------------------- Loading / Empty / Error */

export function LoadingState({ rows = 3, label = 'Loading…' }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 font-mono text-[11px] text-text-muted tracking-[0.15em] uppercase">
        <Loader2 size={12} className="animate-spin" /> {label}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-9 bg-elevated animate-pulse" />
      ))}
    </div>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, hint }) {
  return (
    <div className="border border-dashed border-border-subtle py-10 px-6 flex flex-col items-center text-center">
      <Icon size={28} className="text-text-muted mb-3" strokeWidth={1.5} />
      <div className="font-mono text-[11px] text-text-primary tracking-[0.15em] uppercase">{title}</div>
      {hint && <div className="text-body-sm text-text-secondary mt-2">{hint}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  const message = error?.detail?.toString() || error?.message || String(error);
  return (
    <div className="border border-loss/40 bg-loss-tint p-4 flex items-start gap-3">
      <ServerCrash size={16} className="text-loss shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="font-mono text-[11px] text-loss tracking-[0.15em] uppercase">DATA SOURCE FAULT</div>
        <div className="text-body-sm text-text-secondary mt-1.5 break-all">{message}</div>
      </div>
      {onRetry && (
        <button className="btn-secondary btn-sm shrink-0" onClick={onRetry}>
          retry
        </button>
      )}
    </div>
  );
}

export function StatusBadge({ status }) {
  const map = {
    completed: 'pill-bull',
    running:   'pill-cyan',
    failed:    'pill-bear',
    pending:   'pill-warn',
    new:       'pill-default',
    filled:    'pill-bull',
    canceled:  'pill-default',
    expired:   'pill-default',
    rejected:  'pill-bear',
    accepted:  'pill-default',
    active:    'pill-cyan',
    idle:      'pill-default',
    disabled:  'pill-default',
  };
  const cls = map[(status || '').toLowerCase()] || 'pill-default';
  return <span className={cls}>{status || '—'}</span>;
}

/* Glowing dot helper — for table signal columns */
export function SignalDot({ tone = 'neutral' }) {
  const cls = {
    ok: 'dot-ok', warn: 'dot-warn', danger: 'dot-danger',
    cyan: 'dot-cyan', neutral: 'dot-neutral',
  }[tone] || 'dot-neutral';
  return <span className={classNames('dot', cls)} />;
}
