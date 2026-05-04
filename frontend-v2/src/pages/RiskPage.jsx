import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Save, ShieldAlert, X } from 'lucide-react';
import {
  getRiskPolicies,
  updateRiskPolicies,
  listRiskEvents,
} from '../lib/api.js';
import {
  KpiCard,
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtUsd, fmtRelativeTime, classNames } from '../lib/format.js';

export default function RiskPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const policiesQ = useQuery({ queryKey: ['risk-policies'], queryFn: getRiskPolicies, refetchInterval: 30_000 });
  const eventsQ = useQuery({ queryKey: ['risk-events'], queryFn: listRiskEvents, refetchInterval: 15_000 });

  const [draft, setDraft] = useState(null);
  const [blocklistDraft, setBlocklistDraft] = useState('');

  useEffect(() => {
    if (policiesQ.data && draft === null) {
      setDraft(policiesQ.data);
      setBlocklistDraft((policiesQ.data.blocklist || []).join(', '));
    }
  }, [policiesQ.data, draft]);

  const saveMut = useMutation({
    mutationFn: updateRiskPolicies,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['risk-policies'] });
    },
  });

  function set(field, value) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  function submit(e) {
    e.preventDefault();
    saveMut.mutate({
      enabled: !!draft.enabled,
      max_position_size_usd: draft.max_position_size_usd ? parseFloat(draft.max_position_size_usd) : null,
      max_total_exposure_pct: draft.max_total_exposure_pct ? parseFloat(draft.max_total_exposure_pct) : null,
      max_open_positions: draft.max_open_positions ? parseInt(draft.max_open_positions, 10) : null,
      max_daily_loss_usd: draft.max_daily_loss_usd ? parseFloat(draft.max_daily_loss_usd) : null,
      blocklist: blocklistDraft
        .split(/[,\s]+/)
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean),
    });
  }

  if (policiesQ.isLoading) return <LoadingState rows={6} />;
  if (policiesQ.isError) return <ErrorState error={policiesQ.error} onRetry={policiesQ.refetch} />;
  if (!draft) return null;

  const events = eventsQ.data?.items || [];
  const todayDenies = countTodayDenies(events);

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={8}
        title={t('risk.title')}
        segments={[
          { label: t('risk.subtitle') },
          { label: 'P4 · RISKGUARD', accent: true },
        ]}
      />

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-6">
        <KpiCard label={t('risk.kpi.enabled')} value={draft.enabled ? 'ON' : 'OFF'} delta={null} />
        <KpiCard label={t('risk.kpi.deniesToday')} value={String(todayDenies)} delta={null} />
        <KpiCard label={t('risk.kpi.activePolicies')} value={String(countActivePolicies(draft))} delta={null} />
        <KpiCard label={t('risk.kpi.totalEvents')} value={String(events.length)} delta={null} />
      </div>

      {/* Policy form */}
      <form onSubmit={submit} className="card space-y-5">
        <SectionHeader title={t('risk.policyConfig')} subtitle={t('risk.policyConfigSubtitle')} />

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 accent-cyan"
            checked={!!draft.enabled}
            onChange={(e) => set('enabled', e.target.checked)}
          />
          <span className="text-body font-medium text-text-primary">{t('risk.enableGlobal')}</span>
        </label>

        <div className="grid grid-cols-2 gap-5">
          <PolicyField
            label={t('risk.fields.maxPositionSize')}
            hint={t('risk.fields.maxPositionSizeHint')}
            value={draft.max_position_size_usd ?? ''}
            onChange={(v) => set('max_position_size_usd', v)}
            placeholder="5000"
            type="number"
          />
          <PolicyField
            label={t('risk.fields.maxTotalExposure')}
            hint={t('risk.fields.maxTotalExposureHint')}
            value={draft.max_total_exposure_pct ?? ''}
            onChange={(v) => set('max_total_exposure_pct', v)}
            placeholder="0.5"
            type="number"
            step="0.05"
          />
          <PolicyField
            label={t('risk.fields.maxOpenPositions')}
            hint={t('risk.fields.maxOpenPositionsHint')}
            value={draft.max_open_positions ?? ''}
            onChange={(v) => set('max_open_positions', v)}
            placeholder="5"
            type="number"
          />
          <PolicyField
            label={t('risk.fields.maxDailyLoss')}
            hint={t('risk.fields.maxDailyLossHint')}
            value={draft.max_daily_loss_usd ?? ''}
            onChange={(v) => set('max_daily_loss_usd', v)}
            placeholder="500"
            type="number"
          />
        </div>

        <div>
          <label className="h-caption block mb-2">{t('risk.fields.blocklist')}</label>
          <input
            className="input font-mono"
            placeholder="GME, AMC, BBBYQ"
            value={blocklistDraft}
            onChange={(e) => setBlocklistDraft(e.target.value)}
          />
          <p className="text-caption text-text-muted mt-1">{t('risk.fields.blocklistHint')}</p>
        </div>

        {saveMut.isError && <ApiErrorBanner error={saveMut.error} label={t('risk.saveFailed')} />}
        {saveMut.isSuccess && (
          <div className="border border-profit/40 bg-profit-tint px-3 py-2 text-body-sm text-profit">
            ✓ {t('risk.saveSuccess')}
          </div>
        )}

        <button type="submit" className="btn-primary" disabled={saveMut.isPending}>
          <Save size={14} /> {t('risk.savePolicy')}
        </button>
      </form>

      {/* Events */}
      <div className="card">
        <SectionHeader title={t('risk.events')} subtitle={t('risk.eventsSubtitle', { count: events.length })} />
        <EventsList q={eventsQ} t={t} />
      </div>
    </div>
  );
}

function PolicyField({ label, hint, value, onChange, type = 'text', step, placeholder }) {
  return (
    <div>
      <label className="h-caption block mb-2">{label}</label>
      <input
        className="input tabular"
        type={type}
        step={step}
        placeholder={placeholder}
        value={value === null || value === undefined ? '' : value}
        onChange={(e) => onChange(e.target.value || null)}
      />
      <p className="text-caption text-steel-300 mt-1">{hint}</p>
    </div>
  );
}

function EventsList({ q, t }) {
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={ShieldAlert} title={t('risk.noEvents')} hint={t('risk.noEventsHint')} />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{t('common.time')}</th>
          <th>{t('common.policy')}</th>
          <th>{t('common.decision')}</th>
          <th>{t('common.symbol')} / {t('common.side')}</th>
          <th className="tbl-num">{t('quantlab.fields.notional')} / {t('common.qty')}</th>
          <th>{t('common.reason')}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((e) => (
          <tr key={e.id}>
            <td className="text-steel-200">{fmtRelativeTime(e.occurred_at)}</td>
            <td><span className="pill-warn">{e.policy_name}</span></td>
            <td>
              <span className={classNames(e.decision === 'deny' ? 'text-bear' : 'text-bull', 'uppercase font-semibold text-caption')}>
                {e.decision}
              </span>
            </td>
            <td>
              <span className={classNames('uppercase font-semibold mr-2', e.side === 'buy' ? 'text-bull' : 'text-bear')}>
                {e.side}
              </span>
              <span className="font-medium text-steel-50">{e.symbol}</span>
            </td>
            <td className="tbl-num">
              {e.notional ? fmtUsd(e.notional) : e.qty ? `${e.qty} sh` : '—'}
            </td>
            <td className="text-steel-200 max-w-md truncate">{e.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function countActivePolicies(draft) {
  return ['max_position_size_usd', 'max_total_exposure_pct', 'max_open_positions', 'max_daily_loss_usd']
    .filter((k) => draft[k] !== null && draft[k] !== undefined && draft[k] !== '')
    .length + ((draft.blocklist || []).length > 0 ? 1 : 0);
}

function countTodayDenies(events) {
  const today = new Date().toISOString().slice(0, 10);
  return events.filter((e) => e.decision === 'deny' && (e.occurred_at || '').startsWith(today)).length;
}
