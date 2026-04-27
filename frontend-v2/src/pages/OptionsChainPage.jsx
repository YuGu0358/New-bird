// OptionsChainPage — gamma exposure (GEX), call/put walls, max pain, zero gamma.
//
// Data shape from /api/options-chain/{ticker}:
//   call_wall, put_wall, zero_gamma, max_pain (numbers)
//   total_gex, call_gex_total, put_gex_total ($)
//   by_strike: [{ strike, call_gex, put_gex, net_gex, oi, ... }]
//   by_expiry: [{ expiry, total_gex, max_pain, contracts }]
//
// We render a stacked-bar chart of call+put GEX per strike, with reference
// lines for walls and the spot. Inspired by Tradewell's /options/[ticker].
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { RefreshCw, TrendingUp, Target, X as XIcon } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getOptionsChainGex, refreshOptionsChainGex, getExpiryFocus } from '../lib/api.js';
import {
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { fmtUsd, classNames } from '../lib/format.js';

export default function OptionsChainPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('SPY');
  const [ticker, setTicker] = useState('SPY');
  const [selectedExpiry, setSelectedExpiry] = useState(null);

  const gexQ = useQuery({
    queryKey: ['gex', ticker],
    queryFn: () => getOptionsChainGex(ticker),
    enabled: !!ticker,
    retry: false,
  });
  const refreshMut = useMutation({
    mutationFn: () => refreshOptionsChainGex(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gex', ticker] });
      queryClient.invalidateQueries({ queryKey: ['expiry-focus', ticker] });
    },
  });
  const focusQ = useQuery({
    queryKey: ['expiry-focus', ticker, selectedExpiry],
    queryFn: () => getExpiryFocus(ticker, selectedExpiry),
    enabled: !!ticker && !!selectedExpiry,
    retry: false,
  });

  function submit(e) {
    e.preventDefault();
    if (draft.trim()) {
      setTicker(draft.trim().toUpperCase());
      setSelectedExpiry(null);  // reset drill-in when ticker changes
    }
  }

  const d = gexQ.data;

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={7}
        title={t('options.title')}
        segments={[{ label: t('options.subtitle') }]}
      />

      <div className="card">
        <form onSubmit={submit} className="flex items-end gap-3 mb-2">
          <div className="flex-1 max-w-sm">
            <label className="h-caption block mb-1">{t('options.ticker')}</label>
            <input
              className="input uppercase"
              value={draft}
              onChange={(e) => setDraft(e.target.value.toUpperCase())}
              placeholder="SPY / QQQ / NVDA / AAPL …"
            />
          </div>
          <button type="submit" className="btn-primary">
            <TrendingUp size={14} /> {t('options.compute')}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending || !ticker}
          >
            <RefreshCw size={14} className={refreshMut.isPending ? 'animate-spin' : ''} />
            {t('options.refreshNow')}
          </button>
        </form>
      </div>

      {gexQ.isLoading ? (
        <LoadingState rows={6} label={t('options.loading')} />
      ) : gexQ.isError ? (
        <ErrorState error={gexQ.error} onRetry={gexQ.refetch} />
      ) : !d || !d.by_strike || d.by_strike.length === 0 ? (
        <EmptyState
          title={t('options.empty')}
          hint={t('options.emptyHint')}
        />
      ) : (
        <>
          {/* Levels grid */}
          <div className="card">
            <SectionHeader
              title={t('options.keyLevels', { ticker: d.ticker })}
              subtitle={`${t('options.spot')}: ${fmtUsd(d.spot)}`}
              meta={d.expiries?.length ? `${d.expiries.length} ${t('options.expiriesScanned')}` : null}
            />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-border-subtle">
              <Level label={t('options.callWall')} value={d.call_wall} tone="bear" hint={t('options.callWallHint')} />
              <Level label={t('options.putWall')} value={d.put_wall} tone="bull" hint={t('options.putWallHint')} />
              <Level label={t('options.zeroGamma')} value={d.zero_gamma} tone="cyan" hint={t('options.zeroGammaHint')} />
              <Level label={t('options.maxPain')} value={d.max_pain} tone="warn" hint={t('options.maxPainHint')} />
            </div>
            <div className="mt-4 grid grid-cols-3 gap-px bg-border-subtle">
              <Stat label={t('options.totalGex')} value={fmtCompact(d.total_gex)} tone={d.total_gex >= 0 ? 'bull' : 'bear'} />
              <Stat label={t('options.callGex')} value={fmtCompact(d.call_gex_total)} tone="bull" />
              <Stat label={t('options.putGex')} value={fmtCompact(d.put_gex_total)} tone="bear" />
            </div>
          </div>

          {/* GEX-by-strike chart */}
          <div className="card">
            <SectionHeader title={t('options.gexByStrikeTitle')} subtitle={t('options.gexByStrikeSubtitle')} />
            <GexByStrikeChart rows={d.by_strike} spot={d.spot} callWall={d.call_wall} putWall={d.put_wall} />
          </div>

          {/* By-expiry table — clickable rows open the drill-in panel below */}
          <div className="card">
            <SectionHeader
              title={t('options.byExpiryTitle')}
              subtitle={t('options.byExpirySubtitle')}
              meta={
                <span className="font-mono text-[10px] tracking-[0.15em] text-text-muted uppercase">
                  {t('options.clickRowToFocus')}
                </span>
              }
            />
            {d.by_expiry?.length === 0 ? (
              <EmptyState title={t('options.noExpiries')} />
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>{t('options.expiry')}</th>
                    <th className="tbl-num">{t('options.contracts')}</th>
                    <th className="tbl-num">{t('options.maxPain')}</th>
                    <th className="tbl-num">{t('options.totalGex')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {(d.by_expiry || []).map((row) => {
                    const isSelected = selectedExpiry === row.expiry;
                    return (
                      <tr
                        key={row.expiry}
                        onClick={() => setSelectedExpiry(isSelected ? null : row.expiry)}
                        className={classNames(
                          'cursor-pointer transition duration-150',
                          isSelected ? 'bg-elevated' : 'hover:bg-elevated/60',
                        )}
                      >
                        <td className="font-mono text-text-primary">{row.expiry}</td>
                        <td className="tbl-num">{row.contracts}</td>
                        <td className="tbl-num">{row.max_pain != null ? fmtUsd(row.max_pain) : '—'}</td>
                        <td className={classNames('tbl-num font-medium', row.total_gex >= 0 ? 'text-bull' : 'text-bear')}>
                          {fmtCompact(row.total_gex)}
                        </td>
                        <td>
                          <Target
                            size={14}
                            className={isSelected ? 'text-cyan' : 'text-text-muted'}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Expiry-focus drill-in (only shown when an expiry is selected) */}
          {selectedExpiry && (
            <div className="card">
              <SectionHeader
                title={t('options.focusTitle', { expiry: selectedExpiry })}
                subtitle={t('options.focusSubtitle')}
                action={
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => setSelectedExpiry(null)}
                  >
                    <XIcon size={12} /> {t('options.closeFocus')}
                  </button>
                }
              />
              {focusQ.isLoading ? (
                <LoadingState rows={4} label={t('options.loadingFocus')} />
              ) : focusQ.isError ? (
                <ErrorState error={focusQ.error} onRetry={focusQ.refetch} />
              ) : !focusQ.data ? (
                <EmptyState title={t('options.focusEmpty')} />
              ) : (
                <ExpiryFocusPanel data={focusQ.data} t={t} />
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ExpiryFocusPanel({ data, t }) {
  const fmtIv = (iv) => (iv == null ? '—' : `${(iv * 100).toFixed(1)}%`);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-border-subtle">
        <FocusStat label={t('options.dte')} value={`${data.dte}d`} />
        <FocusStat label={t('options.atmIv')} value={fmtIv(data.atm_iv)} />
        <FocusStat
          label={t('options.expectedRange')}
          value={
            data.expected_low != null && data.expected_high != null
              ? `${fmtUsd(data.expected_low)} → ${fmtUsd(data.expected_high)}`
              : '—'
          }
        />
        <FocusStat
          label={t('options.putCallOi')}
          value={data.put_call_oi_ratio != null ? data.put_call_oi_ratio.toFixed(2) : '—'}
          tone={
            data.put_call_oi_ratio == null ? 'neutral' :
            data.put_call_oi_ratio > 1.2 ? 'bear' :
            data.put_call_oi_ratio < 0.8 ? 'bull' :
            'neutral'
          }
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FocusTable
          t={t}
          title={t('options.topResistance')}
          subtitle={t('options.topResistanceHint')}
          rows={data.top_call_strikes}
          tone="bear"
        />
        <FocusTable
          t={t}
          title={t('options.topSupport')}
          subtitle={t('options.topSupportHint')}
          rows={data.top_put_strikes}
          tone="bull"
        />
      </div>
    </div>
  );
}

function FocusStat({ label, value, tone = 'primary' }) {
  const toneClass =
    tone === 'bull' ? 'text-bull' :
    tone === 'bear' ? 'text-bear' :
    tone === 'neutral' ? 'text-text-secondary' :
    'text-text-primary';
  return (
    <div className="bg-surface px-4 py-3">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">{label}</div>
      <div className={classNames('font-display text-[18px] tabular leading-tight', toneClass)}>{value}</div>
    </div>
  );
}

function FocusTable({ t, title, subtitle, rows, tone }) {
  return (
    <div>
      <div className="font-mono text-[11px] text-text-muted tracking-[0.15em] uppercase mb-1">{title}</div>
      <div className="text-caption text-text-secondary mb-3">{subtitle}</div>
      {!rows || rows.length === 0 ? (
        <div className="text-caption text-text-muted py-4">{t('options.focusNoStrikes')}</div>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>{t('options.strike')}</th>
              <th className="tbl-num">{t('options.distance')}</th>
              <th className="tbl-num">{t('options.openInterest')}</th>
              <th className="tbl-num">{t('options.volume')}</th>
              <th className="tbl-num">IV</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.strike}>
                <td className={classNames('font-medium tabular', tone === 'bull' ? 'text-bull' : 'text-bear')}>
                  {fmtUsd(r.strike)}
                </td>
                <td className="tbl-num">{r.distance_pct >= 0 ? '+' : ''}{r.distance_pct.toFixed(2)}%</td>
                <td className="tbl-num">{r.open_interest.toLocaleString()}</td>
                <td className="tbl-num">{r.volume.toLocaleString()}</td>
                <td className="tbl-num">{r.iv != null ? `${(r.iv * 100).toFixed(1)}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function GexByStrikeChart({ rows, spot, callWall, putWall }) {
  // Limit to strikes within ±15% of spot to keep the chart readable.
  const lo = spot * 0.85;
  const hi = spot * 1.15;
  const trimmed = rows.filter((r) => r.strike >= lo && r.strike <= hi);
  const data = trimmed.length > 0 ? trimmed : rows;
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} stackOffset="sign">
          <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
          <XAxis dataKey="strike" stroke="#7C8A9A" fontSize={11} tickLine={false} />
          <YAxis stroke="#7C8A9A" fontSize={11} tickLine={false} tickFormatter={fmtCompact} />
          <Tooltip
            contentStyle={{ background: '#0F1923', border: '1px solid #3D7FA5', borderRadius: 4, color: '#E8ECF1', fontSize: 12 }}
            formatter={(v) => fmtCompact(v)}
            labelFormatter={(s) => `Strike ${fmtUsd(s)}`}
          />
          <ReferenceLine x={spot} stroke="#14F1D9" strokeWidth={2} label={{ value: 'spot', fill: '#14F1D9', fontSize: 10 }} />
          {callWall != null && <ReferenceLine x={callWall} stroke="#FF3366" strokeDasharray="4 4" label={{ value: 'call wall', fill: '#FF3366', fontSize: 10 }} />}
          {putWall != null && <ReferenceLine x={putWall} stroke="#00D980" strokeDasharray="4 4" label={{ value: 'put wall', fill: '#00D980', fontSize: 10 }} />}
          <Bar dataKey="call_gex" stackId="g" fill="#5BA3C6" />
          <Bar dataKey="put_gex" stackId="g" fill="#A86CD1" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Level({ label, value, tone, hint }) {
  const toneClass =
    tone === 'bull' ? 'text-bull' :
    tone === 'bear' ? 'text-bear' :
    tone === 'warn' ? 'text-warn' :
    'text-cyan';
  return (
    <div className="bg-surface px-5 py-4">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.2em] uppercase mb-2">{label}</div>
      <div className={classNames('font-display text-[28px] font-light tabular leading-none', toneClass)}>
        {value != null ? fmtUsd(value) : '—'}
      </div>
      {hint && <div className="text-caption text-text-muted mt-2">{hint}</div>}
    </div>
  );
}

function Stat({ label, value, tone }) {
  const toneClass =
    tone === 'bull' ? 'text-bull' :
    tone === 'bear' ? 'text-bear' :
    'text-text-primary';
  return (
    <div className="bg-surface px-4 py-3">
      <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">{label}</div>
      <div className={classNames('font-display text-[18px] tabular leading-tight', toneClass)}>{value}</div>
    </div>
  );
}

function fmtCompact(n) {
  if (n == null) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return Math.round(n).toString();
}
