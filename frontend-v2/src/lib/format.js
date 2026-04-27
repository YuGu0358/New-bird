// Number / time formatting helpers.

const usdFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const compactUsdFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
});

export function fmtUsd(value, { compact = false } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return compact ? compactUsdFormatter.format(value) : usdFormatter.format(value);
}

export function fmtPct(value, { fractionDigits = 2, withSign = true } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = withSign && value > 0 ? '+' : '';
  return `${sign}${value.toFixed(fractionDigits)}%`;
}

export function fmtNumber(value, { fractionDigits = 2 } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-US', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

export function fmtSignedUsd(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${usdFormatter.format(Math.abs(value))}`;
}

export function fmtRelativeTime(input) {
  if (!input) return '—';
  const ts = typeof input === 'string' ? new Date(input) : input;
  if (Number.isNaN(ts.getTime())) return '—';
  const diffMs = Date.now() - ts.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (Math.abs(diffSec) < 60) return diffSec <= 0 ? 'just now' : `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (Math.abs(diffMin) < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (Math.abs(diffHr) < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (Math.abs(diffDay) < 7) return `${diffDay}d ago`;
  return ts.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function fmtAbsTime(input) {
  if (!input) return '—';
  const ts = typeof input === 'string' ? new Date(input) : input;
  if (Number.isNaN(ts.getTime())) return '—';
  return ts.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function deltaClass(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'metric-delta-flat';
  if (value > 0) return 'metric-delta-up';
  if (value < 0) return 'metric-delta-down';
  return 'metric-delta-flat';
}

export function classNames(...args) {
  return args.filter(Boolean).join(' ');
}
