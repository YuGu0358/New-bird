import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Save, Eye, EyeOff, CheckCircle2, AlertTriangle } from 'lucide-react';
import {
  getSettingsStatus,
  updateSettings,
  getReadiness,
} from '../lib/api.js';
import { SectionHeader, PageHeader, LoadingState, ErrorState, StatusBadge } from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtRelativeTime } from '../lib/format.js';

const REQUIRED_KEYS = [
  { key: 'ALPACA_API_KEY', labelKey: 'settings.labels.alpacaApiKey', required: true },
  { key: 'ALPACA_SECRET_KEY', labelKey: 'settings.labels.alpacaSecretKey', required: true },
  { key: 'POLYGON_API_KEY', labelKey: 'settings.labels.polygonApiKey', required: true },
  { key: 'TAVILY_API_KEY', labelKey: 'settings.labels.tavilyApiKey', required: true },
];
const OPTIONAL_KEYS = [
  // Optional keys — labels & hints come from i18n via translateKey/hintKey
  { key: 'OPENAI_API_KEY', labelKey: 'settings.labels.openaiApiKey', hintKey: 'settings.labels.openaiHint', required: false },
  { key: 'X_BEARER_TOKEN', labelKey: 'settings.labels.xBearerToken', hintKey: 'settings.labels.xBearerHint', required: false },
  { key: 'NOTIFICATIONS_WEBHOOK_URL', labelKey: 'settings.labels.notificationsWebhook', hintKey: 'settings.labels.notificationsHint', required: false },
  { key: 'SETTINGS_ADMIN_TOKEN', labelKey: 'settings.labels.settingsAdminToken', hintKey: 'settings.labels.settingsAdminTokenHint', required: false },
];

export default function SettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const statusQ = useQuery({ queryKey: ['settings-status'], queryFn: getSettingsStatus, refetchInterval: 30_000 });
  const readyQ = useQuery({ queryKey: ['readiness'], queryFn: getReadiness, refetchInterval: 30_000 });

  const [draft, setDraft] = useState({});
  const [revealed, setRevealed] = useState({});
  const [adminToken, setAdminToken] = useState('');

  const saveMut = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      setDraft({});
      queryClient.invalidateQueries({ queryKey: ['settings-status'] });
      queryClient.invalidateQueries({ queryKey: ['readiness'] });
    },
  });

  function setKey(k, v) {
    setDraft((prev) => ({ ...prev, [k]: v }));
  }
  function toggleReveal(k) {
    setRevealed((prev) => ({ ...prev, [k]: !prev[k] }));
  }
  function submit(e) {
    e.preventDefault();
    // Backend expects { settings: dict[str, Any], admin_token: str | None }.
    const payload = { settings: draft };
    if (adminToken) payload.admin_token = adminToken;
    saveMut.mutate(payload);
  }

  if (statusQ.isLoading) return <LoadingState rows={6} />;
  if (statusQ.isError) return <ErrorState error={statusQ.error} onRetry={statusQ.refetch} />;

  const status = statusQ.data || {};
  const items = status.items || [];
  const itemMap = Object.fromEntries(items.map((i) => [i.key, i]));

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <PageHeader
            moduleId={99}
            title={t('settings.title')}
            segments={[{ label: t('settings.subtitle') }]}
            live={false}
          />
        </div>
        <ReadinessSummary status={status} ready={readyQ.data} />
      </div>

      {saveMut.isError && <ApiErrorBanner error={saveMut.error} label={t('common.saveFailed')} />}
      {saveMut.isSuccess && (
        <div className="border border-profit/40 bg-profit-tint px-4 py-2 text-body-sm text-profit flex items-center gap-2">
          <CheckCircle2 size={14} /> {t('settings.savedOk')}
        </div>
      )}

      <form onSubmit={submit} className="space-y-6">
        <KeyGroup
          t={t}
          title={t('settings.requiredKeys')}
          subtitle={t('settings.requiredHint')}
          fields={REQUIRED_KEYS}
          itemMap={itemMap}
          draft={draft}
          revealed={revealed}
          onSet={setKey}
          onReveal={toggleReveal}
        />
        <KeyGroup
          t={t}
          title={t('settings.optionalKeys')}
          subtitle={t('settings.optionalHint')}
          fields={OPTIONAL_KEYS}
          itemMap={itemMap}
          draft={draft}
          revealed={revealed}
          onSet={setKey}
          onReveal={toggleReveal}
        />

        <div className="card">
          <SectionHeader title={t('settings.adminToken')} subtitle={t('settings.adminTokenHint')} />
          <input
            type="password"
            className="input max-w-md"
            placeholder={t('settings.adminTokenPlaceholder')}
            value={adminToken}
            onChange={(e) => setAdminToken(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            className="btn-primary"
            disabled={saveMut.isPending || Object.keys(draft).length === 0}
          >
            <Save size={14} /> {t('settings.saveButton')}
          </button>
          <span className="text-body-sm text-text-secondary">
            {t('settings.fieldsPending', { count: Object.keys(draft).length })}
          </span>
        </div>
      </form>
    </div>
  );
}

function KeyGroup({ t, title, subtitle, fields, itemMap, draft, revealed, onSet, onReveal }) {
  return (
    <div className="card">
      <SectionHeader title={title} subtitle={subtitle} />
      <div className="space-y-3">
        {fields.map(({ key, labelKey, hintKey }) => {
          const item = itemMap[key] || {};
          const draftValue = draft[key] ?? '';
          const isRevealed = !!revealed[key];
          const label = labelKey ? t(labelKey) : key;
          const hint = hintKey ? t(hintKey) : '';
          return (
            <div key={key} className="grid grid-cols-12 gap-4 items-start py-2">
              <div className="col-span-3">
                <div className="text-body font-medium text-text-primary">{label}</div>
                <div className="text-caption text-text-secondary mt-1 font-mono">{key}</div>
                {hint && <div className="text-body-sm text-text-secondary mt-1">{hint}</div>}
              </div>
              <div className="col-span-7">
                <div className="relative">
                  <input
                    className="input pr-10 font-mono text-body-sm"
                    type={isRevealed ? 'text' : 'password'}
                    value={draftValue}
                    placeholder={item.configured ? '••••••••' : t('settings.sourceLabel.missing')}
                    onChange={(e) => onSet(key, e.target.value)}
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary"
                    onClick={() => onReveal(key)}
                    tabIndex={-1}
                  >
                    {isRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
              <div className="col-span-2 flex justify-end pt-1.5">
                <SourceBadge has={item.configured} source={item.source} t={t} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SourceBadge({ has, source, t }) {
  if (!has) return <span className="pill-default">{t('settings.sourceLabel.missing')}</span>;
  const map = { env: 'pill-default', stored: 'pill-bull', default: 'pill-default' };
  const label = t(`settings.sourceLabel.${source}`, source || 'set');
  return <span className={map[source] || 'pill-default'}>{label}</span>;
}

function ReadinessSummary({ status, ready }) {
  const { t } = useTranslation();
  const isReady = !!status.is_ready && ready?.ready !== false;
  return (
    <div className="text-right">
      <div className="flex items-center gap-2 justify-end">
        {isReady ? (
          <span className="pill-bull inline-flex items-center gap-1.5"><CheckCircle2 size={12} /> {t('settings.ready')}</span>
        ) : (
          <span className="pill-warn inline-flex items-center gap-1.5"><AlertTriangle size={12} /> {t('settings.notReady')}</span>
        )}
      </div>
      {ready?.checks?.length > 0 && (
        <div className="text-caption text-steel-200 mt-2 space-y-0.5">
          {ready.checks.map((c) => (
            <div key={c.name} className="flex items-center gap-1.5 justify-end">
              <span className={c.ok ? 'text-bull' : 'text-bear'}>●</span>
              <span>{c.name}</span>
              {!c.ok && c.detail && <span className="text-bear">{c.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
