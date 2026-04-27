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

  if (policiesQ.isLoading) return <LoadingState rows={6} label="Loading risk policies…" />;
  if (policiesQ.isError) return <ErrorState error={policiesQ.error} onRetry={policiesQ.refetch} />;
  if (!draft) return null;

  const events = eventsQ.data?.items || [];
  const todayDenies = countTodayDenies(events);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">{t('risk.title')}</h1>
          <p className="text-body-sm text-steel-200 mt-1">{t('risk.subtitle')}</p>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-6">
        <KpiCard label="Risk enabled" value={draft.enabled ? 'ON' : 'OFF'} delta={null} />
        <KpiCard label="今日拒单数" value={String(todayDenies)} delta={null} />
        <KpiCard label="活跃政策数" value={String(countActivePolicies(draft))} delta={null} />
        <KpiCard
          label="历史事件总数"
          value={String(events.length)}
          delta={null}
        />
      </div>

      {/* Policy form */}
      <form onSubmit={submit} className="card space-y-5">
        <SectionHeader title="政策配置" subtitle="保存后自动下发到运行时(下次 _build_active_strategy 生效)" />

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 accent-steel-500"
            checked={!!draft.enabled}
            onChange={(e) => set('enabled', e.target.checked)}
          />
          <span className="text-body font-medium text-steel-50">全局启用 RiskGuard</span>
        </label>

        <div className="grid grid-cols-2 gap-5">
          <PolicyField
            label="单 symbol 最大持仓 (USD)"
            hint="MaxPositionSizePolicy · 该 symbol 已有持仓 + 新订单超过此值则拒"
            value={draft.max_position_size_usd ?? ''}
            onChange={(v) => set('max_position_size_usd', v)}
            placeholder="例如 5000"
            type="number"
          />
          <PolicyField
            label="总敞口比例上限 (0–1)"
            hint="MaxTotalExposurePolicy · 所有持仓 / equity"
            value={draft.max_total_exposure_pct ?? ''}
            onChange={(v) => set('max_total_exposure_pct', v)}
            placeholder="例如 0.5 = 50%"
            type="number"
            step="0.05"
          />
          <PolicyField
            label="并发持仓 symbol 数上限"
            hint="MaxOpenPositionsPolicy · 加仓不计入"
            value={draft.max_open_positions ?? ''}
            onChange={(v) => set('max_open_positions', v)}
            placeholder="例如 5"
            type="number"
          />
          <PolicyField
            label="单日亏损熔断 (USD,正数)"
            hint="MaxDailyLossPolicy · 当日 realized PnL ≤ -值 时禁止 buy"
            value={draft.max_daily_loss_usd ?? ''}
            onChange={(v) => set('max_daily_loss_usd', v)}
            placeholder="例如 500"
            type="number"
          />
        </div>

        <div>
          <label className="h-caption block mb-2">符号黑名单 (逗号 / 空格分隔)</label>
          <input
            className="input font-mono"
            placeholder="GME, AMC, BBBYQ"
            value={blocklistDraft}
            onChange={(e) => setBlocklistDraft(e.target.value)}
          />
          <p className="text-caption text-steel-300 mt-1">SymbolBlocklistPolicy · 任何方向(buy / sell)都拒</p>
        </div>

        {saveMut.isError && <ApiErrorBanner error={saveMut.error} label="保存失败" />}
        {saveMut.isSuccess && (
          <div className="border border-bull/40 rounded-md bg-bull-tint px-3 py-2 text-body-sm text-bull">
            ✓ 已保存,新 buy 订单将受新规则约束
          </div>
        )}

        <button type="submit" className="btn-primary" disabled={saveMut.isPending}>
          <Save size={14} /> 保存政策
        </button>
      </form>

      {/* Events */}
      <div className="card">
        <SectionHeader title="事件流" subtitle={`最近 ${events.length} 条拒单 / 警告`} />
        <EventsList q={eventsQ} />
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

function EventsList({ q }) {
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={ShieldAlert} title="暂无事件" hint="所有提交的订单都通过了风控。" />;

  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Time</th>
          <th>Policy</th>
          <th>Decision</th>
          <th>Symbol / Side</th>
          <th className="tbl-num">Notional / Qty</th>
          <th>Reason</th>
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
