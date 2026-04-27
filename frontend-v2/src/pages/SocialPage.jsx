import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Radar, Search as SearchIcon, ExternalLink, RefreshCw } from 'lucide-react';
import {
  getSocialProviders,
  searchSocial,
  scoreSocialSignal,
  listSocialSignals,
  runSocialSignals,
} from '../lib/api.js';
import {
  KpiCard,
  PageHeader,
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { fmtRelativeTime, fmtPct, classNames } from '../lib/format.js';

export default function SocialPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState('x');
  const [symbol, setSymbol] = useState('NVDA');
  const [draft, setDraft] = useState('NVDA');
  const [searchQuery, setSearchQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');

  const providersQ = useQuery({ queryKey: ['social-providers'], queryFn: getSocialProviders });
  const signalsQ = useQuery({ queryKey: ['social-signals'], queryFn: () => listSocialSignals(50), refetchInterval: 30_000 });
  const scoreQ = useQuery({
    queryKey: ['social-score', symbol, provider],
    queryFn: () => scoreSocialSignal(symbol, provider),
    enabled: !!symbol,
  });
  const searchQ = useQuery({
    queryKey: ['social-search', submittedQuery, provider],
    queryFn: () => searchSocial(submittedQuery, provider),
    enabled: submittedQuery.length > 0,
  });

  const runMut = useMutation({
    mutationFn: runSocialSignals,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['social-signals'] }),
  });

  function commitSymbol(e) {
    e.preventDefault();
    if (draft.trim()) setSymbol(draft.trim().toUpperCase());
  }

  function commitSearch(e) {
    e.preventDefault();
    if (searchQuery.trim()) setSubmittedQuery(searchQuery.trim());
  }

  const signals = signalsQ.data || [];
  const symbolHistory = signals.filter((s) => s.symbol === symbol).slice(0, 30).reverse();
  const todayCounts = countTodaySignals(signals);

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={10}
        title={t('social.title')}
        segments={[
          { label: t('social.subtitle') },
          { label: 'P5 · MULTI-SOURCE', accent: true },
        ]}
      />
      <div className="flex justify-end -mt-4">
        <button
          className="btn-secondary btn-sm"
          onClick={() => runMut.mutate({ symbols: [symbol] })}
          disabled={runMut.isPending}
        >
          <RefreshCw size={12} className={runMut.isPending ? 'animate-spin' : ''} /> {t('social.triggerScore', { symbol })}
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-6">
        <KpiCard label={t('social.kpi.totalSignals')} value={String(signals.length)} delta={null} />
        <KpiCard label={t('social.kpi.todayBuys')} value={String(todayCounts.buy || 0)} delta={null} />
        <KpiCard label={t('social.kpi.todaySells')} value={String(todayCounts.sell || 0)} delta={null} />
        <KpiCard label={t('social.kpi.providers')} value={(providersQ.data || []).map((p) => p.name).join(' / ') || '—'} delta={null} />
      </div>

      {/* Selected symbol detail */}
      <form onSubmit={commitSymbol} className="card flex items-end gap-3">
        <div>
          <label className="h-caption block mb-2">Provider</label>
          <select className="select" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {(providersQ.data || [{ name: 'x' }]).map((p) => (
              <option key={p.name || p} value={p.name || p}>{p.name || p}</option>
            ))}
          </select>
        </div>
        <div className="flex-1 max-w-sm">
          <label className="h-caption block mb-2">Symbol</label>
          <div className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-steel-200" />
            <input
              className="input pl-9 uppercase"
              value={draft}
              onChange={(e) => setDraft(e.target.value.toUpperCase())}
            />
          </div>
        </div>
        <button type="submit" className="btn-primary">{t('social.queryButton')}</button>
      </form>

      {/* Score detail */}
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-7 card">
          <SectionHeader
            title={t('social.scoreHistory', { symbol })}
            subtitle={t('social.scoreHistorySubtitle')}
          />
          {symbolHistory.length === 0 ? (
            <EmptyState icon={Radar} title={t('social.noScoreHistory')} hint={t('social.noScoreHistoryHint')} />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={symbolHistory.map((s) => ({
                  t: (s.snapshot_at || '').slice(5, 16).replace('T', ' '),
                  social: parseFloat(s.social_score),
                  market: parseFloat(s.market_score),
                  weight: parseFloat(s.final_weight),
                }))}>
                  <defs>
                    <linearGradient id="socialFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#A285E8" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#A285E8" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#2A3645" strokeDasharray="3 3" />
                  <XAxis dataKey="t" stroke="#7C8A9A" fontSize={11} tickLine={false} />
                  <YAxis stroke="#7C8A9A" fontSize={11} tickLine={false} domain={[-1, 1]} />
                  <Tooltip
                    contentStyle={{ background: '#0F1923', border: '1px solid #3D7FA5', borderRadius: 6, color: '#E8ECF1', fontSize: 12 }}
                  />
                  <Area type="monotone" dataKey="social" name="Social" stroke="#A285E8" strokeWidth={2} fill="url(#socialFill)" />
                  <Area type="monotone" dataKey="market" name="Market" stroke="#5BA3C6" strokeWidth={1.5} fillOpacity={0} />
                  <Area type="monotone" dataKey="weight" name="Final" stroke="#26D9A5" strokeWidth={1.5} fillOpacity={0} strokeDasharray="4 4" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="col-span-5 card">
          <SectionHeader title={t('social.latestSnapshot')} />
          <ScoreSnapshot q={scoreQ} />
        </div>
      </div>

      {/* Recent signals across all symbols */}
      <div className="card">
        <SectionHeader title={t('social.allSignalsTitle')} subtitle={t('social.allSignalsSubtitle')} />
        <SignalsTable q={signalsQ} onSelect={(sym) => { setDraft(sym); setSymbol(sym); }} />
      </div>

      {/* Free social search */}
      <div className="card">
        <SectionHeader title={t('social.freeSearchTitle')} subtitle={t('social.freeSearchSubtitle')} />
        <form onSubmit={commitSearch} className="flex gap-3 mb-4">
          <input
            className="input flex-1 max-w-2xl"
            placeholder="NVDA earnings beat OR NVDA AI"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={!searchQuery.trim()}>{t('common.search')}</button>
        </form>
        <SearchResults q={searchQ} />
      </div>
    </div>
  );
}

function ScoreSnapshot({ q }) {
  const { t } = useTranslation();
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data;
  if (!d) return <EmptyState title={t('social.noScore')} />;
  const action = (d.action || '').toLowerCase();
  const actionPill =
    action === 'buy' ? 'pill-bull' :
    action === 'sell' ? 'pill-bear' :
    action === 'avoid' ? 'pill-bear' :
    'pill-default';

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className={actionPill}>{d.action || 'hold'}</span>
        <span className="pill-default">confidence: {d.confidence_label || d.confidence?.toFixed?.(2) || '—'}</span>
      </div>
      <Stat label="Social score" value={Number(d.social_score).toFixed(3)} />
      <Stat label="Market score" value={Number(d.market_score).toFixed(3)} />
      <Stat label="Final weight" value={Number(d.final_weight).toFixed(3)} valueClass="text-steel-50 font-semibold" />
      <Stat label="Snapshot at" value={fmtRelativeTime(d.snapshot_at)} />
      {d.reasons?.length > 0 && (
        <div>
          <div className="h-caption mb-1">Reasons</div>
          <ul className="space-y-1 text-body-sm text-steel-100 list-disc list-inside">
            {d.reasons.slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, valueClass = 'text-steel-100' }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-body-sm text-steel-200">{label}</span>
      <span className={classNames('text-body-sm tabular', valueClass)}>{value}</span>
    </div>
  );
}

function SignalsTable({ q, onSelect }) {
  const { t } = useTranslation();
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data || [];
  if (items.length === 0) return <EmptyState icon={Radar} title={t('social.noSignalsYet')} />;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Action</th>
          <th>Confidence</th>
          <th className="tbl-num">Social</th>
          <th className="tbl-num">Market</th>
          <th className="tbl-num">Final</th>
          <th>Executed</th>
        </tr>
      </thead>
      <tbody>
        {items.slice(0, 30).map((s) => (
          <tr key={s.id} className="cursor-pointer" onClick={() => onSelect(s.symbol)}>
            <td className="text-steel-200">{fmtRelativeTime(s.snapshot_at)}</td>
            <td className="font-medium text-steel-50">{s.symbol}</td>
            <td>
              <span
                className={classNames(
                  'uppercase font-semibold text-caption',
                  s.action === 'buy' ? 'text-bull' : s.action === 'sell' || s.action === 'avoid' ? 'text-bear' : 'text-steel-200'
                )}
              >
                {s.action}
              </span>
            </td>
            <td><span className="pill-default">{s.confidence_label}</span></td>
            <td className="tbl-num">{Number(s.social_score).toFixed(3)}</td>
            <td className="tbl-num">{Number(s.market_score).toFixed(3)}</td>
            <td className="tbl-num font-medium">{Number(s.final_weight).toFixed(3)}</td>
            <td>
              {s.executed ? <span className="pill-bull">yes</span> : <span className="pill-default">no</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SearchResults({ q }) {
  const { t } = useTranslation();
  if (!q.data && !q.isLoading) return <div className="text-body-sm text-text-secondary">{t('news.searchContent')}</div>;
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const posts = q.data?.posts || q.data?.items || [];
  if (posts.length === 0) return <EmptyState title={t('social.noPosts')} />;

  return (
    <div className="space-y-3">
      {posts.slice(0, 20).map((p, i) => (
        <a
          key={p.id || i}
          href={p.url}
          target={p.url ? '_blank' : undefined}
          rel="noreferrer"
          className="block card-dense card-hover"
        >
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 text-caption text-steel-200">
                <span className="font-medium text-steel-100">{p.author || '?'}</span>
                <span>·</span>
                <span>{fmtRelativeTime(p.created_at || p.timestamp)}</span>
                {typeof p.likes === 'number' && <><span>·</span><span>{p.likes} likes</span></>}
              </div>
              <p className="text-body-sm text-steel-100 mt-1 leading-relaxed">{p.text || p.content}</p>
            </div>
            {p.url && <ExternalLink size={12} className="text-steel-200 ml-2 shrink-0 mt-1" />}
          </div>
        </a>
      ))}
    </div>
  );
}

function countTodaySignals(signals) {
  const today = new Date().toISOString().slice(0, 10);
  const counts = { buy: 0, sell: 0, hold: 0, avoid: 0 };
  for (const s of signals) {
    if ((s.snapshot_at || '').startsWith(today)) {
      counts[(s.action || 'hold').toLowerCase()] = (counts[(s.action || 'hold').toLowerCase()] || 0) + 1;
    }
  }
  return counts;
}
