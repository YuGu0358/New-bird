import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Plus, X, RefreshCw, Search as SearchIcon, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import {
  getMonitoring,
  refreshMonitoring,
  searchUniverse,
  addWatchlist,
  removeWatchlist,
} from '../lib/api.js';
import {
  SectionHeader,
  PageHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { fmtUsd, fmtPct, fmtSignedUsd, classNames } from '../lib/format.js';

export default function MarketsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const monitoringQ = useQuery({ queryKey: ['monitoring'], queryFn: getMonitoring, refetchInterval: 30_000 });

  const refreshMut = useMutation({
    mutationFn: refreshMonitoring,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitoring'] }),
  });
  const addMut = useMutation({
    mutationFn: addWatchlist,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monitoring'] });
      setSearchTerm('');
    },
  });
  const removeMut = useMutation({
    mutationFn: removeWatchlist,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitoring'] }),
  });

  const universeQ = useQuery({
    queryKey: ['universe', searchTerm],
    queryFn: () => searchUniverse(searchTerm),
    enabled: searchTerm.length >= 1,
  });

  const watchlist = monitoringQ.data?.watchlist || [];
  const positions = monitoringQ.data?.positions || [];
  const candidates = monitoringQ.data?.candidates || [];
  const tracked = monitoringQ.data?.tracked || monitoringQ.data?.items || [];

  return (
    <div className="space-y-8">
      <PageHeader
        moduleId={2}
        title={t('markets.title')}
        segments={[{ label: t('markets.subtitle') }]}
      />
      <div className="flex justify-end -mt-4">
        <button
          className="btn-secondary btn-sm"
          onClick={() => refreshMut.mutate()}
          disabled={refreshMut.isPending}
        >
          <RefreshCw size={12} className={refreshMut.isPending ? 'animate-spin' : ''} /> {t('markets.forceRefresh')}
        </button>
      </div>

      {/* Search universe + add watchlist */}
      <div className="card">
        <SectionHeader
          title={t('markets.universeSearch')}
          subtitle={`Watchlist: ${watchlist.length} symbol${watchlist.length === 1 ? '' : 's'}`}
        />
        <div className="relative max-w-md">
          <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-steel-200" />
          <input
            className="input pl-9"
            placeholder={t('markets.searchPlaceholder')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value.toUpperCase())}
          />
        </div>
        {searchTerm.length >= 1 && (
          <div className="mt-3">
            {universeQ.isLoading ? (
              <div className="text-caption text-text-secondary">{t('markets.searching')}</div>
            ) : universeQ.isError ? (
              <ErrorState error={universeQ.error} />
            ) : (universeQ.data || []).length === 0 ? (
              <div className="text-caption text-text-secondary">{t('markets.noResults')}</div>
            ) : (
              <ul className="space-y-1 max-h-60 overflow-auto border border-steel-400 rounded-md divide-y divide-steel-400">
                {(universeQ.data || []).map((row) => (
                  <li key={row.symbol} className="px-3 py-2 flex items-center justify-between hover:bg-ink-700">
                    <div>
                      <div className="text-body font-medium text-steel-50">{row.symbol}</div>
                      <div className="text-caption text-steel-200">{row.name || row.exchange || ''}</div>
                    </div>
                    <button
                      className="btn-secondary btn-sm"
                      onClick={() => addMut.mutate(row.symbol)}
                      disabled={watchlist.includes(row.symbol) || addMut.isPending}
                    >
                      <Plus size={14} /> {watchlist.includes(row.symbol) ? t('markets.alreadyAdded') : t('markets.addToWatchlist')}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {watchlist.length === 0 ? (
            <span className="text-caption text-text-secondary">{t('markets.watchlistEmpty')}</span>
          ) : (
            watchlist.map((s) => (
              <span key={s} className="pill-active inline-flex items-center gap-1.5">
                {s}
                <button onClick={() => removeMut.mutate(s)} className="hover:text-bear">
                  <X size={11} strokeWidth={2.5} />
                </button>
              </span>
            ))
          )}
        </div>
      </div>

      {/* Tracked symbols (positions + watchlist + candidate pool merged) */}
      <div className="card">
        <SectionHeader title={t('markets.trackedTitle')} subtitle={t('markets.trackedSubtitle')} />
        {monitoringQ.isLoading ? (
          <LoadingState rows={6} />
        ) : monitoringQ.isError ? (
          <ErrorState error={monitoringQ.error} onRetry={monitoringQ.refetch} />
        ) : tracked.length === 0 ? (
          <EmptyState title={t('markets.noTracked')} hint={t('markets.noTrackedHint')} />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>{t('common.symbol')}</th>
                <th>{t('markets.columns.source')}</th>
                <th className="tbl-num">{t('markets.columns.last')}</th>
                <th className="tbl-num">D %</th>
                <th className="tbl-num">W %</th>
                <th className="tbl-num">M %</th>
                <th className="tbl-num">{t('markets.columns.position')}</th>
              </tr>
            </thead>
            <tbody>
              {tracked.map((row, i) => (
                <TrackedRow key={`${row.symbol}-${i}`} row={row} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Two-col bottom: positions + candidate pool */}
      <div className="grid grid-cols-2 gap-6">
        <div className="card">
          <SectionHeader title={t('markets.activePositions')} subtitle={`${positions.length}`} />
          {positions.length === 0 ? (
            <EmptyState title={t('dashboard.noPositions')} />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>{t('common.symbol')}</th>
                  <th className="tbl-num">{t('common.qty')}</th>
                  <th className="tbl-num">{t('markets.columns.marketValue')}</th>
                  <th className="tbl-num">{t('markets.columns.unrealizedPnl')}</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const upl = parseFloat(p.unrealized_pl ?? 0);
                  return (
                    <tr key={p.symbol}>
                      <td className="font-medium text-steel-50">{p.symbol}</td>
                      <td className="tbl-num">{parseFloat(p.qty || 0).toFixed(4)}</td>
                      <td className="tbl-num">{fmtUsd(parseFloat(p.market_value || 0))}</td>
                      <td className={classNames('tbl-num font-medium', upl > 0 ? 'text-bull' : upl < 0 ? 'text-bear' : '')}>
                        {fmtSignedUsd(upl)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <SectionHeader title={t('markets.candidatePoolToday')} subtitle={t('markets.candidatePoolSubtitle')} />
          {candidates.length === 0 ? (
            <EmptyState title={t('dashboard.candidatesEmpty')} hint={t('markets.candidatesEmptyHint')} />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>{t('common.symbol')}</th>
                  <th>{t('markets.columns.category')}</th>
                  <th className="tbl-num">{t('markets.columns.score')}</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c, i) => (
                  <tr key={`${c.symbol}-${i}`}>
                    <td className="font-medium text-steel-50">{c.symbol}</td>
                    <td><span className="pill-default">{c.category}</span></td>
                    <td className="tbl-num text-steel-50">{Number(c.score ?? 0).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function TrackedRow({ row }) {
  const symbol = row.symbol;
  const last = parseFloat(row.last_price ?? row.current_price ?? 0);
  const d = parseFloat(row.day_change_percent ?? row.day_change ?? 0);
  const w = parseFloat(row.week_change_percent ?? 0);
  const m = parseFloat(row.month_change_percent ?? 0);
  const positionQty = parseFloat(row.position_qty ?? row.qty ?? 0);
  const source = row.source || (positionQty > 0 ? 'position' : 'watchlist');

  return (
    <tr>
      <td className="font-medium text-steel-50">{symbol}</td>
      <td><span className={source === 'position' ? 'pill-bull' : source === 'candidate' ? 'pill-warn' : 'pill-default'}>{source}</span></td>
      <td className="tbl-num">{last > 0 ? fmtUsd(last) : '—'}</td>
      <PercentCell value={d} />
      <PercentCell value={w} />
      <PercentCell value={m} />
      <td className="tbl-num">{positionQty > 0 ? positionQty.toFixed(4) : '—'}</td>
    </tr>
  );
}

function PercentCell({ value }) {
  const v = Number.isFinite(value) ? value : 0;
  const Icon = v > 0 ? ArrowUpRight : v < 0 ? ArrowDownRight : null;
  return (
    <td className={classNames('tbl-num font-medium tabular', v > 0 ? 'text-bull' : v < 0 ? 'text-bear' : 'text-steel-200')}>
      <span className="inline-flex items-center justify-end gap-0.5">
        {Icon && <Icon size={12} />}
        {Number.isFinite(value) ? fmtPct(value) : '—'}
      </span>
    </td>
  );
}
