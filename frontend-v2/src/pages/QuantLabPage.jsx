import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Calculator, Sigma, Coins, BarChart3, Send } from 'lucide-react';
import {
  optionPrice,
  optionGreeks,
  bondYield,
  bondRisk,
  valueAtRisk,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  EmptyState,
  ErrorState,
  LoadingState,
} from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtUsd, fmtPct, fmtNumber, classNames } from '../lib/format.js';

const TABS = [
  { id: 'option', icon: Send },
  { id: 'greeks', icon: Sigma },
  { id: 'bondYield', icon: Coins },
  { id: 'bondRisk', icon: BarChart3 },
  { id: 'var', icon: Calculator },
];

export default function QuantLabPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState('option');

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={8}
        title={t('quantlab.title')}
        segments={[
          { label: t('quantlab.subtitle') },
          { label: 'P8 · QUANTLIB', accent: true },
        ]}
        live={false}
      />

      <div className="flex items-center gap-6 border-b border-border-subtle overflow-x-auto">
        {TABS.map((tt) => (
          <button
            key={tt.id}
            className={classNames(
              'h-10 -mb-px border-b-2 font-mono text-[11px] tracking-[0.15em] uppercase font-medium transition duration-150 inline-flex items-center gap-2 px-2 whitespace-nowrap',
              tab === tt.id
                ? 'border-cyan text-cyan'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            )}
            onClick={() => setTab(tt.id)}
          >
            <tt.icon size={12} /> {t(`quantlab.tabs.${tt.id}`)}
          </button>
        ))}
      </div>

      {tab === 'option' && <OptionPriceForm />}
      {tab === 'greeks' && <GreeksForm />}
      {tab === 'bondYield' && <BondYieldForm />}
      {tab === 'bondRisk' && <BondRiskForm />}
      {tab === 'var' && <VaRForm />}
    </div>
  );
}

// ============================================================ shared layout

function FormShell({ children, result, mut, t, runFn, runDisabled }) {
  return (
    <div className="grid grid-cols-12 gap-6">
      <form
        className="col-span-7 card space-y-4"
        onSubmit={(e) => { e.preventDefault(); runFn(); }}
      >
        {children}
        {mut.isError && <ApiErrorBanner error={mut.error} label={t('quantlab.computeFailed')} />}
        <button type="submit" className="btn-primary" disabled={mut.isPending || runDisabled}>
          <Send size={14} /> {mut.isPending ? t('quantlab.computing') : t('quantlab.compute')}
        </button>
      </form>
      <div className="col-span-5">
        {mut.isPending && <div className="card"><LoadingState rows={3} label={t('quantlab.computing')} /></div>}
        {!mut.isPending && !mut.data && <div className="card"><EmptyState icon={Calculator} title={t('quantlab.noResultYet')} /></div>}
        {mut.data && result(mut.data)}
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="h-caption block mb-2">{label}</label>
      {children}
      {hint && <p className="text-caption text-steel-300 mt-1">{hint}</p>}
    </div>
  );
}

function ResultRow({ label, value, hint, valueClass = 'text-steel-50' }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-steel-400 last:border-0">
      <div>
        <div className="text-body-sm text-steel-100">{label}</div>
        {hint && <div className="text-caption text-steel-300">{hint}</div>}
      </div>
      <span className={classNames('text-num-md font-semibold tabular', valueClass)}>{value}</span>
    </div>
  );
}

// ============================================================ Option price

function OptionPriceForm() {
  const { t } = useTranslation();
  const [spot, setSpot] = useState(100);
  const [strike, setStrike] = useState(100);
  const [rate, setRate] = useState(0.05);
  const [dividend, setDividend] = useState(0);
  const [vol, setVol] = useState(0.2);
  const [valuation, setValuation] = useState('2025-01-01');
  const [expiry, setExpiry] = useState('2026-01-01');
  const [right, setRight] = useState('call');
  const [style, setStyle] = useState('european');
  const [steps, setSteps] = useState(200);

  const mut = useMutation({ mutationFn: optionPrice });

  function run() {
    mut.mutate({
      spot: parseFloat(spot), strike: parseFloat(strike),
      rate: parseFloat(rate), dividend: parseFloat(dividend),
      volatility: parseFloat(vol),
      valuation, expiry, right, style,
      steps: parseInt(steps, 10),
    });
  }

  return (
    <FormShell t={t} mut={mut} runFn={run} result={(d) => (
      <div className="card">
        <SectionHeader title={t('common.result')} />
        <ResultRow label={t('quantlab.results.price')} value={fmtNumber(d.price, { fractionDigits: 4 })} valueClass={right === 'call' ? 'text-bull' : 'text-bear'} />
        <ResultRow label={t('quantlab.results.daysToExpiry')} value={String(d.days_to_expiry)} />
        <ResultRow label={t('quantlab.fields.right')} value={d.right.toUpperCase()} />
        <ResultRow label={t('quantlab.fields.style')} value={d.style} />
      </div>
    )}>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('quantlab.fields.spot')}><input className="input tabular" type="number" step="0.01" value={spot} onChange={(e) => setSpot(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.strike')}><input className="input tabular" type="number" step="0.01" value={strike} onChange={(e) => setStrike(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.rate')}><input className="input tabular" type="number" step="0.001" value={rate} onChange={(e) => setRate(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.dividend')}><input className="input tabular" type="number" step="0.001" value={dividend} onChange={(e) => setDividend(e.target.value)} /></Field>
        <Field label={t('quantlab.fields.volatility')}><input className="input tabular" type="number" step="0.01" value={vol} onChange={(e) => setVol(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.steps')}><input className="input tabular" type="number" step="10" value={steps} onChange={(e) => setSteps(e.target.value)} /></Field>
        <Field label={t('quantlab.fields.valuation')}><input className="input" type="date" value={valuation} onChange={(e) => setValuation(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.expiry')}><input className="input" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.right')}>
          <select className="select" value={right} onChange={(e) => setRight(e.target.value)}>
            <option value="call">{t('quantlab.fields.right_call')}</option>
            <option value="put">{t('quantlab.fields.right_put')}</option>
          </select>
        </Field>
        <Field label={t('quantlab.fields.style')}>
          <select className="select" value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="european">{t('quantlab.fields.style_european')}</option>
            <option value="american">{t('quantlab.fields.style_american')}</option>
          </select>
        </Field>
      </div>
    </FormShell>
  );
}

// ============================================================ Greeks

function GreeksForm() {
  const { t } = useTranslation();
  const [spot, setSpot] = useState(100);
  const [strike, setStrike] = useState(100);
  const [rate, setRate] = useState(0.05);
  const [dividend, setDividend] = useState(0);
  const [vol, setVol] = useState(0.2);
  const [valuation, setValuation] = useState('2025-01-01');
  const [expiry, setExpiry] = useState('2026-01-01');
  const [right, setRight] = useState('call');

  const mut = useMutation({ mutationFn: optionGreeks });

  function run() {
    mut.mutate({
      spot: parseFloat(spot), strike: parseFloat(strike),
      rate: parseFloat(rate), dividend: parseFloat(dividend),
      volatility: parseFloat(vol), valuation, expiry, right,
    });
  }

  return (
    <FormShell t={t} mut={mut} runFn={run} result={(d) => (
      <div className="card">
        <SectionHeader title={t('common.result')} />
        <ResultRow label={t('quantlab.results.delta')} hint={t('quantlab.results.deltaHint')} value={fmtNumber(d.delta, { fractionDigits: 4 })} valueClass={d.delta > 0 ? 'text-bull' : 'text-bear'} />
        <ResultRow label={t('quantlab.results.gamma')} hint={t('quantlab.results.gammaHint')} value={fmtNumber(d.gamma, { fractionDigits: 4 })} />
        <ResultRow label={t('quantlab.results.vega')}  hint={t('quantlab.results.vegaHint')}  value={fmtNumber(d.vega,  { fractionDigits: 2 })} />
        <ResultRow label={t('quantlab.results.theta')} hint={t('quantlab.results.thetaHint')} value={fmtNumber(d.theta, { fractionDigits: 2 })} valueClass={d.theta < 0 ? 'text-bear' : 'text-bull'} />
        <ResultRow label={t('quantlab.results.rho')}   hint={t('quantlab.results.rhoHint')}   value={fmtNumber(d.rho,   { fractionDigits: 2 })} />
      </div>
    )}>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('quantlab.fields.spot')}><input className="input tabular" type="number" step="0.01" value={spot} onChange={(e) => setSpot(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.strike')}><input className="input tabular" type="number" step="0.01" value={strike} onChange={(e) => setStrike(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.rate')}><input className="input tabular" type="number" step="0.001" value={rate} onChange={(e) => setRate(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.dividend')}><input className="input tabular" type="number" step="0.001" value={dividend} onChange={(e) => setDividend(e.target.value)} /></Field>
        <Field label={t('quantlab.fields.volatility')}><input className="input tabular" type="number" step="0.01" value={vol} onChange={(e) => setVol(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.right')}>
          <select className="select" value={right} onChange={(e) => setRight(e.target.value)}>
            <option value="call">{t('quantlab.fields.right_call')}</option>
            <option value="put">{t('quantlab.fields.right_put')}</option>
          </select>
        </Field>
        <Field label={t('quantlab.fields.valuation')}><input className="input" type="date" value={valuation} onChange={(e) => setValuation(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.expiry')}><input className="input" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} required /></Field>
      </div>
    </FormShell>
  );
}

// ============================================================ Bond yield

function BondAnalyticsFields({ state, setState, t }) {
  const update = (k) => (e) => setState({ ...state, [k]: e.target.value });
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label={t('quantlab.fields.settlement')}><input className="input" type="date" value={state.settlement} onChange={update('settlement')} required /></Field>
      <Field label={t('quantlab.fields.maturity')}><input className="input" type="date" value={state.maturity} onChange={update('maturity')} required /></Field>
      <Field label={t('quantlab.fields.couponRate')}><input className="input tabular" type="number" step="0.001" value={state.coupon_rate} onChange={update('coupon_rate')} required /></Field>
      <Field label={t('quantlab.fields.frequency')}>
        <select className="select" value={state.frequency} onChange={update('frequency')}>
          <option value={1}>1</option><option value={2}>2</option><option value={4}>4</option><option value={12}>12</option>
        </select>
      </Field>
      <Field label={t('quantlab.fields.face')}><input className="input tabular" type="number" step="1" value={state.face} onChange={update('face')} /></Field>
      <Field label={t('quantlab.fields.cleanPrice')}><input className="input tabular" type="number" step="0.01" value={state.clean_price} onChange={update('clean_price')} /></Field>
    </div>
  );
}

function BondYieldForm() {
  const { t } = useTranslation();
  const [state, setState] = useState({
    settlement: '2025-01-01',
    maturity: '2030-01-01',
    coupon_rate: 0.05,
    frequency: 2,
    face: 100,
    clean_price: 100,
  });
  const mut = useMutation({ mutationFn: bondYield });
  function run() {
    mut.mutate({
      ...state,
      coupon_rate: parseFloat(state.coupon_rate),
      frequency: parseInt(state.frequency, 10),
      face: parseFloat(state.face),
      clean_price: parseFloat(state.clean_price),
    });
  }
  return (
    <FormShell t={t} mut={mut} runFn={run} result={(d) => (
      <div className="card">
        <SectionHeader title={t('common.result')} />
        <ResultRow label={t('quantlab.results.ytm')} value={fmtPct(d.yield_to_maturity * 100, { fractionDigits: 4, withSign: false })} valueClass="text-steel-50 font-bold" />
      </div>
    )}>
      <BondAnalyticsFields state={state} setState={setState} t={t} />
    </FormShell>
  );
}

// ============================================================ Bond risk

function BondRiskForm() {
  const { t } = useTranslation();
  const [state, setState] = useState({
    settlement: '2025-01-01',
    maturity: '2030-01-01',
    coupon_rate: 0.05,
    frequency: 2,
    face: 100,
    clean_price: 100,
  });
  const mut = useMutation({ mutationFn: bondRisk });
  function run() {
    mut.mutate({
      ...state,
      coupon_rate: parseFloat(state.coupon_rate),
      frequency: parseInt(state.frequency, 10),
      face: parseFloat(state.face),
      clean_price: parseFloat(state.clean_price),
    });
  }
  return (
    <FormShell t={t} mut={mut} runFn={run} result={(d) => (
      <div className="card">
        <SectionHeader title={t('common.result')} />
        <ResultRow label={t('quantlab.results.ytm')} value={fmtPct(d.yield_to_maturity * 100, { fractionDigits: 4, withSign: false })} />
        <ResultRow label={t('quantlab.results.macaulayDuration')} value={`${fmtNumber(d.macaulay_duration, { fractionDigits: 4 })} y`} />
        <ResultRow label={t('quantlab.results.modifiedDuration')} value={`${fmtNumber(d.modified_duration, { fractionDigits: 4 })} y`} />
        <ResultRow label={t('quantlab.results.convexity')} value={fmtNumber(d.convexity, { fractionDigits: 4 })} />
      </div>
    )}>
      <BondAnalyticsFields state={state} setState={setState} t={t} />
    </FormShell>
  );
}

// ============================================================ VaR

function VaRForm() {
  const { t } = useTranslation();
  const [method, setMethod] = useState('parametric');
  const [notional, setNotional] = useState(1_000_000);
  const [confidence, setConfidence] = useState(0.95);
  const [horizon, setHorizon] = useState(1);
  const [meanReturn, setMeanReturn] = useState(0);
  const [stdReturn, setStdReturn] = useState(0.01);
  const [returns, setReturns] = useState('');

  const mut = useMutation({ mutationFn: valueAtRisk });

  function run() {
    const payload = {
      method,
      notional: parseFloat(notional),
      confidence: parseFloat(confidence),
      horizon_days: parseInt(horizon, 10),
    };
    if (method === 'parametric') {
      payload.mean_return = parseFloat(meanReturn);
      payload.std_return = parseFloat(stdReturn);
    } else {
      payload.returns = returns
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter((s) => s)
        .map((s) => parseFloat(s))
        .filter((n) => !Number.isNaN(n));
    }
    mut.mutate(payload);
  }

  return (
    <FormShell t={t} mut={mut} runFn={run} result={(d) => (
      <div className="card">
        <SectionHeader title={t('common.result')} />
        <ResultRow label={t('quantlab.results.var')}    value={fmtUsd(d.var)}   valueClass="text-bear font-bold" />
        <ResultRow label={t('quantlab.results.cvar')}   value={fmtUsd(d.cvar)}  valueClass="text-bear-weak" />
        <ResultRow label={t('quantlab.fields.confidence')} value={fmtPct(d.confidence * 100, { fractionDigits: 1, withSign: false })} />
        <ResultRow label={t('quantlab.fields.horizonDays')} value={`${d.horizon_days} d`} />
        <ResultRow label={t('quantlab.results.method')} value={d.method} />
      </div>
    )}>
      <Field label={t('quantlab.fields.method')}>
        <select className="select" value={method} onChange={(e) => setMethod(e.target.value)}>
          <option value="parametric">{t('quantlab.fields.method_parametric')}</option>
          <option value="historical">{t('quantlab.fields.method_historical')}</option>
        </select>
      </Field>
      <div className="grid grid-cols-3 gap-4">
        <Field label={t('quantlab.fields.notional')}><input className="input tabular" type="number" step="1000" value={notional} onChange={(e) => setNotional(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.confidence')}><input className="input tabular" type="number" step="0.01" min="0.5" max="0.999" value={confidence} onChange={(e) => setConfidence(e.target.value)} required /></Field>
        <Field label={t('quantlab.fields.horizonDays')}><input className="input tabular" type="number" step="1" min="1" max="365" value={horizon} onChange={(e) => setHorizon(e.target.value)} required /></Field>
      </div>
      {method === 'parametric' ? (
        <div className="grid grid-cols-2 gap-4">
          <Field label={t('quantlab.fields.meanReturn')}><input className="input tabular" type="number" step="0.0001" value={meanReturn} onChange={(e) => setMeanReturn(e.target.value)} /></Field>
          <Field label={t('quantlab.fields.stdReturn')}><input className="input tabular" type="number" step="0.001" value={stdReturn} onChange={(e) => setStdReturn(e.target.value)} required /></Field>
        </div>
      ) : (
        <Field label={t('quantlab.fields.returns')} hint={t('quantlab.fields.returnsHint')}>
          <textarea className="input h-24 font-mono text-body-sm" value={returns} onChange={(e) => setReturns(e.target.value)} required placeholder="-0.01, 0.005, -0.003, ..." />
        </Field>
      )}
    </FormShell>
  );
}
