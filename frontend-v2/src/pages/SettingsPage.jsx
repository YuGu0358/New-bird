import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Save, Eye, EyeOff, CheckCircle2, AlertTriangle } from 'lucide-react';
import {
  getSettingsStatus,
  updateSettings,
  getReadiness,
} from '../lib/api.js';
import { SectionHeader, LoadingState, ErrorState, StatusBadge } from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtRelativeTime } from '../lib/format.js';

const REQUIRED_KEYS = [
  { key: 'ALPACA_API_KEY', label: 'Alpaca API Key', required: true },
  { key: 'ALPACA_SECRET_KEY', label: 'Alpaca Secret Key', required: true },
  { key: 'POLYGON_API_KEY', label: 'Polygon API Key', required: true },
  { key: 'TAVILY_API_KEY', label: 'Tavily API Key', required: true },
];
const OPTIONAL_KEYS = [
  { key: 'OPENAI_API_KEY', label: 'OpenAI API Key', required: false, hint: '启用候选池 AI 终选 + 中文摘要' },
  { key: 'X_BEARER_TOKEN', label: 'X (Twitter) Bearer Token', required: false, hint: '启用社媒信号' },
  { key: 'NOTIFICATIONS_WEBHOOK_URL', label: 'Notifications Webhook URL', required: false, hint: '风控事件 webhook' },
  { key: 'SETTINGS_ADMIN_TOKEN', label: 'Settings Admin Token', required: false, hint: '保护本页更新' },
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
    const payload = { values: draft };
    if (adminToken) payload.admin_token = adminToken;
    saveMut.mutate(payload);
  }

  if (statusQ.isLoading) return <LoadingState rows={6} label="Loading settings…" />;
  if (statusQ.isError) return <ErrorState error={statusQ.error} onRetry={statusQ.refetch} />;

  const status = statusQ.data || {};
  const items = status.items || [];
  const itemMap = Object.fromEntries(items.map((i) => [i.key, i]));

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">{t('settings.title')}</h1>
          <p className="text-body-sm text-steel-200 mt-1">{t('settings.subtitle')}</p>
        </div>
        <ReadinessSummary status={status} ready={readyQ.data} />
      </div>

      {saveMut.isError && <ApiErrorBanner error={saveMut.error} label="保存失败" />}
      {saveMut.isSuccess && (
        <div className="border border-bull/40 rounded-md bg-bull-tint px-4 py-2 text-body-sm text-bull flex items-center gap-2">
          <CheckCircle2 size={14} /> 已保存,已下发到运行时。
        </div>
      )}

      <form onSubmit={submit} className="space-y-6">
        <KeyGroup
          title="必填密钥"
          subtitle="缺任意一个 Dashboard 都无法返回真实数据"
          fields={REQUIRED_KEYS}
          itemMap={itemMap}
          draft={draft}
          revealed={revealed}
          onSet={setKey}
          onReveal={toggleReveal}
        />
        <KeyGroup
          title="可选密钥"
          subtitle="启用对应高级功能"
          fields={OPTIONAL_KEYS}
          itemMap={itemMap}
          draft={draft}
          revealed={revealed}
          onSet={setKey}
          onReveal={toggleReveal}
        />

        <div className="card">
          <SectionHeader title="管理员令牌" subtitle="保存任何修改时必须随附,如果你部署到了公网" />
          <input
            type="password"
            className="input max-w-md"
            placeholder="留空表示部署没启 admin token"
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
            <Save size={14} /> 保存修改
          </button>
          <span className="text-body-sm text-steel-200">
            {Object.keys(draft).length} 个字段待保存
          </span>
        </div>
      </form>
    </div>
  );
}

function KeyGroup({ title, subtitle, fields, itemMap, draft, revealed, onSet, onReveal }) {
  return (
    <div className="card">
      <SectionHeader title={title} subtitle={subtitle} />
      <div className="space-y-3">
        {fields.map(({ key, label, hint }) => {
          const item = itemMap[key] || {};
          const draftValue = draft[key] ?? '';
          const isRevealed = !!revealed[key];
          return (
            <div key={key} className="grid grid-cols-12 gap-4 items-start py-2">
              <div className="col-span-3">
                <div className="text-body font-medium text-steel-50">{label}</div>
                <div className="text-caption text-steel-200 mt-1">{key}</div>
                {hint && <div className="text-body-sm text-steel-200 mt-1">{hint}</div>}
              </div>
              <div className="col-span-7">
                <div className="relative">
                  <input
                    className="input pr-10 font-mono text-body-sm"
                    type={isRevealed ? 'text' : 'password'}
                    value={draftValue}
                    placeholder={item.has_value ? '已配置(****)— 输入新值覆盖' : '未配置'}
                    onChange={(e) => onSet(key, e.target.value)}
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-steel-200 hover:text-steel-50"
                    onClick={() => onReveal(key)}
                    tabIndex={-1}
                  >
                    {isRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
              <div className="col-span-2 flex justify-end pt-1.5">
                <SourceBadge has={item.has_value} source={item.source} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SourceBadge({ has, source }) {
  if (!has) return <span className="pill-default">未配置</span>;
  const map = { env: 'pill-default', stored: 'pill-bull', default: 'pill-default' };
  return <span className={map[source] || 'pill-default'}>{source || 'set'}</span>;
}

function ReadinessSummary({ status, ready }) {
  const isReady = !!status.is_ready && ready?.ready !== false;
  return (
    <div className="text-right">
      <div className="flex items-center gap-2 justify-end">
        {isReady ? (
          <span className="pill-bull inline-flex items-center gap-1.5"><CheckCircle2 size={12} /> Ready</span>
        ) : (
          <span className="pill-warn inline-flex items-center gap-1.5"><AlertTriangle size={12} /> 未就绪</span>
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
