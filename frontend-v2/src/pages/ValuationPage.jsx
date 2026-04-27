// ValuationPage — DCF + PE-channel sandbox.
//
// Two side-by-side cards:
//   1. DCF: user enters FCFE/growth/discount/terminal/years → POST returns
//      fair value + ±1pt sensitivity grid; we show the central value and the
//      low/high band from the grid.
//   2. PE-channel: user enters a ticker → GET returns historical PE p5/p25/
//      p50/p75/p95 + corresponding fair price bands.
//
// Both ports of Tradewell's Sprint-5 Research sandbox, rebuilt for the
// Newbird Tokyo aesthetic and i18n-aware.
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Calculator, BarChart3 } from 'lucide-react';
import { runDcf, getPeChannel } from '../lib/api.js';
import {
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { fmtUsd, classNames } from '../lib/format.js';

export default function ValuationPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={6}
        title={t('valuation.title')}
        segments={[{ label: t('valuation.subtitle') }]}
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DCFCard t={t} />
        <PEChannelCard t={t} />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- DCF */

function DCFCard({ t }) {
  const [form, setForm] = useState({
    fcfe0: 10,
    growth_stage1: 0.10,
    growth_terminal: 0.025,
    discount_rate: 0.10,
    years_stage1: 7,
  });
  const [result, setResult] = useState(null);
  const dcfMut = useMutation({
    mutationFn: runDcf,
    onSuccess: (data) => setResult(data),
    onError: () => setResult(null),
  });

  function update(field, value) {
    setForm({ ...form, [field]: value });
  }

  function submit(e) {
    e.preventDefault();
    dcfMut.mutate(form);
  }

  return (
    <div className="card">
      <SectionHeader
        title={t('valuation.dcfTitle')}
        subtitle={t('valuation.dcfSubtitle')}
      />
      <form onSubmit={submit} className="space-y-3">
        <NumberField label={t('valuation.fcfe0')} value={form.fcfe0} step="0.1" onChange={(v) => update('fcfe0', v)} />
        <NumberField label={t('valuation.growthStage1')} value={form.growth_stage1} step="0.005" onChange={(v) => update('growth_stage1', v)} hint="0.10 = 10%" />
        <NumberField label={t('valuation.growthTerminal')} value={form.growth_terminal} step="0.005" onChange={(v) => update('growth_terminal', v)} hint="0.025 = 2.5%" />
        <NumberField label={t('valuation.discountRate')} value={form.discount_rate} step="0.005" onChange={(v) => update('discount_rate', v)} hint="0.10 = 10%" />
        <NumberField label={t('valuation.yearsStage1')} value={form.years_stage1} step="1" onChange={(v) => update('years_stage1', v)} integer />
        <button type="submit" className="btn-primary" disabled={dcfMut.isPending}>
          <Calculator size={14} /> {t('valuation.runDcf')}
        </button>
      </form>

      {dcfMut.isPending && <div className="mt-4"><LoadingState rows={3} label={t('valuation.computing')} /></div>}
      {dcfMut.isError && <div className="mt-4"><ErrorState error={dcfMut.error} /></div>}

      {result && (
        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-3 gap-px bg-border-subtle">
            <BandCell label={t('valuation.fairLow')} value={result.fair_low} tone="bear" />
            <BandCell label={t('valuation.fairValue')} value={result.fair_value_per_share} tone="primary" />
            <BandCell label={t('valuation.fairHigh')} value={result.fair_high} tone="bull" />
          </div>
          <div className="text-caption text-text-muted">
            {t('valuation.pvStage1')}: <span className="text-text-primary font-mono">{fmtUsd(result.breakdown?.pv_stage1)}</span>
            {' · '}
            {t('valuation.pvTerminal')}: <span className="text-text-primary font-mono">{fmtUsd(result.breakdown?.pv_terminal)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- PE channel */

function PEChannelCard({ t }) {
  const [draft, setDraft] = useState('NVDA');
  const [ticker, setTicker] = useState('NVDA');

  const peQ = useQuery({
    queryKey: ['pe-channel', ticker],
    queryFn: () => getPeChannel(ticker),
    enabled: !!ticker,
    retry: false,
  });

  function submit(e) {
    e.preventDefault();
    if (draft.trim()) setTicker(draft.trim().toUpperCase());
  }

  const d = peQ.data;
  const hasBands = d && d.pe_p50 != null;

  return (
    <div className="card">
      <SectionHeader
        title={t('valuation.peChannelTitle')}
        subtitle={t('valuation.peChannelSubtitle')}
      />
      <form onSubmit={submit} className="flex items-end gap-3 mb-4">
        <div className="flex-1 max-w-xs">
          <label className="h-caption block mb-1">{t('valuation.ticker')}</label>
          <input
            className="input uppercase"
            value={draft}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
          />
        </div>
        <button type="submit" className="btn-secondary">
          <BarChart3 size={14} /> {t('valuation.compute')}
        </button>
      </form>

      {peQ.isLoading ? (
        <LoadingState rows={4} />
      ) : peQ.isError ? (
        <ErrorState error={peQ.error} onRetry={peQ.refetch} />
      ) : !hasBands ? (
        <EmptyState title={t('valuation.peEmpty')} hint={t('valuation.peEmptyHint')} />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3 text-center">
            <Stat label={t('valuation.currentPrice')} value={d.current_price ? fmtUsd(d.current_price) : '—'} />
            <Stat label={t('valuation.ttmEps')} value={d.ttm_eps != null ? d.ttm_eps.toFixed(2) : '—'} />
            <Stat label={t('valuation.currentPe')} value={d.current_pe != null ? d.current_pe.toFixed(1) + '×' : '—'} />
          </div>

          <div>
            <div className="font-mono text-[11px] text-text-muted tracking-[0.15em] uppercase mb-2">
              {t('valuation.peBands')} ({d.sample_size} {t('valuation.sampleDays')})
            </div>
            <div className="grid grid-cols-5 gap-px bg-border-subtle">
              <PEBand label="p5" pe={d.pe_p5} fair={d.fair_p5} />
              <PEBand label="p25" pe={d.pe_p25} fair={d.fair_p25} />
              <PEBand label="p50" pe={d.pe_p50} fair={d.fair_p50} highlight />
              <PEBand label="p75" pe={d.pe_p75} fair={d.fair_p75} />
              <PEBand label="p95" pe={d.pe_p95} fair={d.fair_p95} />
            </div>
            {d.current_price != null && d.fair_p50 != null && (
              <div className="text-caption text-text-secondary mt-3">
                {d.current_price < d.fair_p25
                  ? t('valuation.veryCheap')
                  : d.current_price < d.fair_p50
                    ? t('valuation.cheap')
                    : d.current_price < d.fair_p75
                      ? t('valuation.fair')
                      : d.current_price < d.fair_p95
                        ? t('valuation.expensive')
                        : t('valuation.veryExpensive')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- Helpers */

function NumberField({ label, value, step, onChange, hint, integer }) {
  return (
    <div>
      <label className="h-caption block mb-1">{label}</label>
      <input
        type="number"
        step={step}
        className="input tabular"
        value={value}
        onChange={(e) => {
          const v = integer ? parseInt(e.target.value || '0', 10) : parseFloat(e.target.value || '0');
          if (!Number.isNaN(v)) onChange(v);
        }}
      />
      {hint && <div className="text-[10px] text-text-muted font-mono tracking-[0.1em] mt-1">{hint}</div>}
    </div>
  );
}

function BandCell({ label, value, tone }) {
  const toneClass =
    tone === 'bear' ? 'text-bear' :
    tone === 'bull' ? 'text-bull' :
    'text-cyan';
  return (
    <div className="bg-surface px-4 py-3">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">{label}</div>
      <div className={classNames('font-display text-[22px] font-light tabular leading-tight', toneClass)}>
        {value != null ? fmtUsd(value) : '—'}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="border border-border-subtle py-3 px-2">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">{label}</div>
      <div className="font-display text-[18px] tabular text-text-primary">{value}</div>
    </div>
  );
}

function PEBand({ label, pe, fair, highlight }) {
  return (
    <div className={classNames('px-3 py-2 bg-surface', highlight && 'bg-elevated border-y border-cyan/40')}>
      <div className={classNames('font-mono text-[10px] tracking-[0.1em] uppercase mb-1', highlight ? 'text-cyan' : 'text-text-muted')}>
        {label}
      </div>
      <div className="font-display text-[14px] tabular text-text-primary">
        {pe != null ? pe.toFixed(1) + '×' : '—'}
      </div>
      <div className="text-caption text-text-secondary tabular">
        {fair != null ? fmtUsd(fair) : '—'}
      </div>
    </div>
  );
}
