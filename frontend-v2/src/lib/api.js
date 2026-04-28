// Thin fetch wrapper. The Vite dev server proxies /api → 127.0.0.1:8000.
// In production builds we serve from same origin, so relative URLs work too.
//
// We forward the i18next-selected UI language as `Accept-Language` on every
// call so the backend can localise LLM-generated text (news summaries,
// research reports, AI Council verdicts) into en / zh / de / fr.

import i18next from '../i18n/index.js';

export class ApiError extends Error {
  constructor(message, { status, detail } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function currentLang() {
  // i18next.language can be e.g. "zh-CN" — backend's normalize_lang() collapses
  // that to "zh", so we don't need to massage it here. Fall back to "en" if
  // i18next hasn't initialised yet (test runner / SSR).
  return (i18next && i18next.language) || 'en';
}

async function request(path, { method = 'GET', body, headers } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'Accept-Language': currentLang(),
      ...(headers || {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  let payload = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : payload;
    throw new ApiError(`API ${res.status} ${res.statusText}`, { status: res.status, detail });
  }
  return payload;
}

// ----------------------------------------------------------- account / portfolio
export const getAccount = () => request('/api/account');
export const getPositions = () => request('/api/positions');
export const getTrades = () => request('/api/trades');
export const getOrders = (status = 'all') => request(`/api/orders?status=${encodeURIComponent(status)}`);
export const cancelOrders = () => request('/api/orders/cancel', { method: 'POST' });
export const closePositions = () => request('/api/positions/close', { method: 'POST' });

// ----------------------------------------------------------- monitoring + watchlist
export const getMonitoring = () => request('/api/monitoring');
export const refreshMonitoring = () => request('/api/monitoring/refresh', { method: 'POST' });
export const searchUniverse = (q, limit = 20) =>
  request(`/api/universe?query=${encodeURIComponent(q)}&limit=${limit}`);
export const addWatchlist = (symbol) => request('/api/watchlist', { method: 'POST', body: { symbol } });
export const removeWatchlist = (symbol) =>
  request(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' });

// ----------------------------------------------------------- research
export const getNews = (symbol) => request(`/api/news/${encodeURIComponent(symbol)}`);
export const getResearch = (symbol, model = 'mini') =>
  request(`/api/research/${encodeURIComponent(symbol)}?research_model=${model}`);
export const tavilySearch = (query) => request(`/api/tavily/search?query=${encodeURIComponent(query)}`);
// Backend expects yfinance-style range strings: 1d / 5d / 1mo / 3mo / 6mo / 1y / 2y.
export const getChart = (symbol, range = '3mo') =>
  request(`/api/chart/${encodeURIComponent(symbol)}?range=${range}`);
export const getCompany = (symbol) => request(`/api/company/${encodeURIComponent(symbol)}`);

// ----------------------------------------------------------- strategies
export const listStrategies = () => request('/api/strategies');
export const listRegisteredStrategies = () => request('/api/strategies/registered');
export const analyzeStrategy = (body) => request('/api/strategies/analyze', { method: 'POST', body });
export const previewStrategy = (body) => request('/api/strategies/preview', { method: 'POST', body });
export const saveStrategy = (body) => request('/api/strategies', { method: 'POST', body });
export const updateStrategy = (id, body) =>
  request(`/api/strategies/${id}`, { method: 'PUT', body });
export const activateStrategy = (id) =>
  request(`/api/strategies/${id}/activate`, { method: 'POST' });
export const deleteStrategy = (id) =>
  request(`/api/strategies/${id}`, { method: 'DELETE' });

// ----------------------------------------------------------- backtest
export const runBacktest = (body) => request('/api/backtest/run', { method: 'POST', body });
export const listBacktestRuns = () => request('/api/backtest/runs');
export const getBacktestRun = (id) => request(`/api/backtest/${id}`);
export const getBacktestEquityCurve = (id) => request(`/api/backtest/${id}/equity-curve`);

// ----------------------------------------------------------- risk
export const getRiskPolicies = () => request('/api/risk/policies');
export const updateRiskPolicies = (body) => request('/api/risk/policies', { method: 'PUT', body });
export const listRiskEvents = () => request('/api/risk/events');

// ----------------------------------------------------------- alerts
export const listAlerts = () => request('/api/alerts');
export const createAlert = (body) => request('/api/alerts', { method: 'POST', body });
export const updateAlert = (id, body) => request(`/api/alerts/${id}`, { method: 'PATCH', body });
export const deleteAlert = (id) => request(`/api/alerts/${id}`, { method: 'DELETE' });

// ----------------------------------------------------------- social signals
export const getSocialProviders = () => request('/api/social/providers');
export const searchSocial = (query, provider = 'x') =>
  request(`/api/social/search?query=${encodeURIComponent(query)}&provider=${provider}`);
export const scoreSocialSignal = (symbol, provider = 'x') =>
  request(`/api/social/score?symbol=${encodeURIComponent(symbol)}&provider=${provider}`);
export const listSocialSignals = (limit = 50) =>
  request(`/api/social/signals?limit=${limit}`);
export const runSocialSignals = (body) => request('/api/social/run', { method: 'POST', body });

// ----------------------------------------------------------- bot
export const getBotStatus = () => request('/api/bot/status');
export const startBot = () => request('/api/bot/start', { method: 'POST' });
export const stopBot = () => request('/api/bot/stop', { method: 'POST' });

// ----------------------------------------------------------- settings
export const getSettingsStatus = () => request('/api/settings/status');
export const updateSettings = (body) => request('/api/settings', { method: 'PUT', body });

// ----------------------------------------------------------- observability
export const getHealth = () => request('/api/health');
export const getReadiness = () => request('/api/health/ready');
export const getStrategyHealth = () => request('/api/strategy/health');

// ----------------------------------------------------------- quantlib (P8)
export const optionPrice = (body) => request('/api/quantlib/option/price', { method: 'POST', body });
export const optionGreeks = (body) => request('/api/quantlib/option/greeks', { method: 'POST', body });
export const bondYield = (body) => request('/api/quantlib/bond/yield', { method: 'POST', body });
export const bondRisk = (body) => request('/api/quantlib/bond/risk', { method: 'POST', body });
export const valueAtRisk = (body) => request('/api/quantlib/var', { method: 'POST', body });

// ----------------------------------------------------------- code editor (P9)
export const listUserStrategies = () => request('/api/code/strategies');
export const uploadUserStrategy = (body) => request('/api/code/upload', { method: 'POST', body });
export const getUserStrategySource = (id) => request(`/api/code/strategies/${id}/source`);
export const reloadUserStrategy = (id) => request(`/api/code/strategies/${id}/reload`, { method: 'POST' });
export const deleteUserStrategy = (id) => request(`/api/code/strategies/${id}`, { method: 'DELETE' });

// ----------------------------------------------------------- macro (Tradewell port)
export const getMacroDashboard = () => request('/api/macro');
export const refreshMacroDashboard = () => request('/api/macro/refresh', { method: 'POST' });
export const updateIndicatorThresholds = (code, body) =>
  request(`/api/macro/indicators/${encodeURIComponent(code)}/thresholds`, { method: 'PUT', body });
export const resetIndicatorThresholds = (code) =>
  request(`/api/macro/indicators/${encodeURIComponent(code)}/thresholds`, { method: 'DELETE' });

// ----------------------------------------------------------- valuation (DCF + PE channel)
export const runDcf = (body) => request('/api/valuation/dcf', { method: 'POST', body });
export const getPeChannel = (ticker, opts = {}) => {
  const qs = new URLSearchParams();
  if (opts.lookback_years) qs.set('lookback_years', String(opts.lookback_years));
  if (opts.cagr) qs.set('cagr', String(opts.cagr));
  return request(`/api/valuation/pe-channel/${encodeURIComponent(ticker)}${qs.toString() ? `?${qs}` : ''}`);
};

// ----------------------------------------------------------- options chain (GEX / walls / max pain)
export const getOptionsChainGex = (ticker, maxExpiries = 6) =>
  request(`/api/options-chain/${encodeURIComponent(ticker)}?max_expiries=${maxExpiries}`);
export const refreshOptionsChainGex = (ticker, maxExpiries = 6) =>
  request(`/api/options-chain/${encodeURIComponent(ticker)}/refresh?max_expiries=${maxExpiries}`, { method: 'POST' });
export const getExpiryFocus = (ticker, expiry, opts = {}) => {
  const qs = new URLSearchParams();
  if (opts.max_expiries) qs.set('max_expiries', String(opts.max_expiries));
  if (opts.top_n) qs.set('top_n', String(opts.top_n));
  return request(
    `/api/options-chain/${encodeURIComponent(ticker)}/expiry/${encodeURIComponent(expiry)}${
      qs.toString() ? `?${qs}` : ''
    }`,
  );
};
export const getFridayScan = (ticker, expiry = null) => {
  const qs = new URLSearchParams();
  if (expiry) qs.set('expiry', expiry);
  return request(
    `/api/options-chain/${encodeURIComponent(ticker)}/friday-scan${qs.toString() ? `?${qs}` : ''}`,
  );
};

// ----------------------------------------------------------- journal (Task 3)
export const listJournal = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set('symbol', params.symbol);
  if (params.mood) qs.set('mood', params.mood);
  if (params.search) qs.set('search', params.search);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  return request(`/api/journal${qs.toString() ? `?${qs}` : ''}`);
};
export const getJournalEntry = (id) =>
  request(`/api/journal/${encodeURIComponent(id)}`);
export const createJournalEntry = (body) =>
  request('/api/journal', { method: 'POST', body });
export const updateJournalEntry = (id, body) =>
  request(`/api/journal/${encodeURIComponent(id)}`, { method: 'PATCH', body });
export const deleteJournalEntry = (id) =>
  request(`/api/journal/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const autocompleteJournalSymbols = (prefix, limit = 10) =>
  request(
    `/api/journal/symbols/autocomplete?prefix=${encodeURIComponent(prefix)}&limit=${limit}`,
  );

// ----------------------------------------------------------- agents (P7)
export const listPersonas = () => request('/api/agents/personas');
export const analyzeWithPersona = (body) => request('/api/agents/analyze', { method: 'POST', body });
export const councilAnalyze = (body) => request('/api/agents/council', { method: 'POST', body });
export const listAgentHistory = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set('symbol', params.symbol);
  if (params.persona_id) qs.set('persona_id', params.persona_id);
  if (params.limit) qs.set('limit', String(params.limit));
  return request(`/api/agents/history${qs.toString() ? `?${qs}` : ''}`);
};
