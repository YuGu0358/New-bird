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

// ----------------------------------------------------------- broker accounts (Phase 2.1)
/** @returns {Promise<{ items: Array<{ id: number, broker: string, account_id: string, alias: string, tier: string, is_active: boolean, created_at: string, updated_at: string }> }>} */
export const listBrokerAccounts = (onlyActive = false) =>
  request(`/api/broker-accounts${onlyActive ? '?only_active=true' : ''}`);
/** @param {number} accountPk */
export const getBrokerAccount = (accountPk) =>
  request(`/api/broker-accounts/${accountPk}`);
/** @param {number} accountPk @param {string} alias */
export const updateBrokerAccountAlias = (accountPk, alias) =>
  request(`/api/broker-accounts/${accountPk}/alias`, { method: 'PATCH', body: { alias } });
/** @param {number} accountPk @param {'TIER_1'|'TIER_2'|'TIER_3'} tier */
export const updateBrokerAccountTier = (accountPk, tier) =>
  request(`/api/broker-accounts/${accountPk}/tier`, { method: 'PATCH', body: { tier } });

// ----------------------------------------------------------- position overrides (Phase 2.2)
/** @param {number} accountPk */
export const listOverridesForAccount = (accountPk) =>
  request(`/api/portfolio/overrides?broker_account_id=${accountPk}`);
/** @param {number} accountPk @param {string} ticker */
export const getOverride = (accountPk, ticker) =>
  request(`/api/portfolio/overrides/${accountPk}/${encodeURIComponent(ticker)}`);
/** @param {{ broker_account_id: number, ticker: string, stop_price?: number|null, take_profit_price?: number|null, notes?: string|null, tier_override?: string|null }} payload */
export const upsertOverride = (payload) =>
  request('/api/portfolio/overrides', { method: 'PUT', body: payload });
/** @param {number} accountPk @param {string} ticker */
export const deleteOverride = (accountPk, ticker) =>
  request(`/api/portfolio/overrides/${accountPk}/${encodeURIComponent(ticker)}`, { method: 'DELETE' });

// ----------------------------------------------------------- position costs (cost basis + custom stops)
/** @param {number} accountPk */
export const listPositionCosts = (accountPk) =>
  request(`/api/position-costs?broker_account_id=${accountPk}`);

/** @param {number} accountPk @param {string} ticker */
export const getPositionCost = (accountPk, ticker) =>
  request(`/api/position-costs/${accountPk}/${encodeURIComponent(ticker)}`);

/**
 * @param {{ broker_account_id: number, ticker: string, avg_cost_basis: number,
 *           total_shares: number, custom_stop_loss?: number|null,
 *           custom_take_profit?: number|null, notes?: string }} payload
 */
export const upsertPositionCost = (payload) =>
  request('/api/position-costs', { method: 'PUT', body: payload });

/** @param {{ broker_account_id: number, ticker: string, fill_price: number, fill_qty: number }} payload */
export const recordPositionBuy = (payload) =>
  request('/api/position-costs/buy', { method: 'POST', body: payload });

/** @param {number} accountPk @param {string} ticker */
export const deletePositionCost = (accountPk, ticker) =>
  request(`/api/position-costs/${accountPk}/${encodeURIComponent(ticker)}`, { method: 'DELETE' });

// ----------------------------------------------------------- position snapshots (Phase 2.4)
/** @param {number} accountPk @param {number} [limit=200] */
export const listAccountSnapshots = (accountPk, limit = 200) =>
  request(`/api/portfolio/snapshots?broker_account_id=${accountPk}&limit=${limit}`);

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

/**
 * Compute a single technical indicator series for a symbol.
 * @param {string} symbol
 * @param {{ name?: string, range?: string, period?: number, fast?: number, slow?: number, signal?: number, k?: number }} [opts]
 * @returns {Promise<{ symbol: string, range: string, interval: string, indicator: string, params: object, timestamps: string[], series: Record<string, Array<number|null>>, generated_at: string }>}
 */
export const getIndicator = (symbol, opts = {}) => {
  const qs = new URLSearchParams();
  qs.set('name', opts.name || 'rsi');
  qs.set('range', opts.range || '3mo');
  if (opts.period != null) qs.set('period', String(opts.period));
  if (opts.fast != null) qs.set('fast', String(opts.fast));
  if (opts.slow != null) qs.set('slow', String(opts.slow));
  if (opts.signal != null) qs.set('signal', String(opts.signal));
  if (opts.k != null) qs.set('k', String(opts.k));
  return request(`/api/indicators/${encodeURIComponent(symbol)}?${qs.toString()}`);
};

// ----------------------------------------------------------- strategies
// `request` always sets Content-Type: application/json and JSON-stringifies
// the body, which conflicts with FormData (browser must set the multipart
// boundary itself). Keep a small parallel helper for file uploads instead of
// overloading `request` with a branchy path.
async function requestMultipart(path, formData) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Accept-Language': currentLang() },
    body: formData,
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

export const listStrategies = () => request('/api/strategies');
export const listRegisteredStrategies = () => request('/api/strategies/registered');

/** @param {{ description: string }} body */
export const analyzeStrategy = (body) =>
  request('/api/strategies/analyze', { method: 'POST', body });

/** @param {string[]} symbols 1-8 tickers; LLM observes their current state and proposes a strategy. */
export const observeMarket = (symbols) =>
  request('/api/strategies/observe-market', { method: 'POST', body: { symbols } });

/** Pull the same enriched context the AI Council sees for one symbol. */
export const getSymbolContext = (symbol) =>
  request(`/api/symbols/${encodeURIComponent(symbol)}/context`);

/** @param {string} symbol @param {string} [range] */
export const getSignals = (symbol, range = '3mo') =>
  request(`/api/signals/${encodeURIComponent(symbol)}?range=${encodeURIComponent(range)}`);

/** @param {File[]} files */
export const analyzeStrategyUpload = (files) => {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  return requestMultipart('/api/strategies/analyze-upload', fd);
};

/** @param {{ code: string, description?: string, source_name?: string }} body */
export const analyzeFactorCode = (body) =>
  request('/api/strategies/analyze-factor-code', { method: 'POST', body });

/** @param {File[]} files @param {string} [description] */
export const analyzeFactorUpload = (files, description = '') => {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  if (description) fd.append('description', description);
  return requestMultipart('/api/strategies/analyze-factor-upload', fd);
};

export const previewStrategy = (body) =>
  request('/api/strategies/preview', { method: 'POST', body });

export const saveStrategy = (body) =>
  request('/api/strategies', { method: 'POST', body });

export const updateStrategy = (id, body) =>
  request(`/api/strategies/${id}`, { method: 'PUT', body });

/** @param {number} id */
export const activateStrategy = (id) =>
  request(`/api/strategies/${id}/activate`, { method: 'POST' });

/** @param {number} id */
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
export const getEconomicCalendar = ({ daysAhead = 30, impact = null } = {}) => {
  const qs = new URLSearchParams();
  qs.set('days_ahead', String(daysAhead));
  if (impact) qs.set('impact', impact);
  return request(`/api/macro/calendar?${qs.toString()}`);
};

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
export const getOptionsChainSqueeze = (ticker, maxExpiries = 6) =>
  request(`/api/options-chain/${encodeURIComponent(ticker)}/squeeze?max_expiries=${maxExpiries}`);

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

// ----------------------------------------------------------- workflows (Phase 5.6)
/**
 * @typedef {Object} WorkflowNode
 * @property {string} id
 * @property {string} type
 * @property {{x: number, y: number}} position
 * @property {Record<string, unknown>} data
 */
/**
 * @typedef {Object} WorkflowEdge
 * @property {string} id
 * @property {string} source
 * @property {string} target
 */
/**
 * @typedef {Object} WorkflowDefinition
 * @property {WorkflowNode[]} nodes
 * @property {WorkflowEdge[]} edges
 */
/**
 * @typedef {Object} WorkflowView
 * @property {number} id
 * @property {string} name
 * @property {WorkflowDefinition} definition
 * @property {number|null} schedule_seconds
 * @property {boolean} is_active
 * @property {string} created_at
 * @property {string} updated_at
 */
/**
 * @typedef {Object} WorkflowRunNode
 * @property {string} node_id
 * @property {string} node_type
 * @property {unknown} output
 * @property {string} [error]
 */
/**
 * @typedef {Object} WorkflowRunView
 * @property {boolean} succeeded
 * @property {number} duration_ms
 * @property {WorkflowRunNode[]} nodes
 * @property {unknown} final_output
 */

/** @returns {Promise<{ workflows: WorkflowView[] }>} */
export const listWorkflows = () => request('/api/workflows');

/** @param {string} name @returns {Promise<WorkflowView>} */
export const getWorkflow = (name) =>
  request(`/api/workflows/${encodeURIComponent(name)}`);

/**
 * @param {{ name: string, definition: WorkflowDefinition, schedule_seconds: number|null, is_active: boolean }} payload
 * @returns {Promise<WorkflowView>}
 */
export const upsertWorkflow = (payload) =>
  request('/api/workflows', { method: 'PUT', body: payload });

/** @param {string} name */
export const deleteWorkflow = (name) =>
  request(`/api/workflows/${encodeURIComponent(name)}`, { method: 'DELETE' });

/** @param {string} name @returns {Promise<WorkflowRunView>} */
export const runWorkflow = (name) =>
  request(`/api/workflows/${encodeURIComponent(name)}/run`, { method: 'POST' });

/** @param {string} name @returns {Promise<WorkflowView>} */
export const enableWorkflow = (name) =>
  request(`/api/workflows/${encodeURIComponent(name)}/enable`, { method: 'POST' });

/** @param {string} name @returns {Promise<WorkflowView>} */
export const disableWorkflow = (name) =>
  request(`/api/workflows/${encodeURIComponent(name)}/disable`, { method: 'POST' });

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

// ----------------------------------------------------------- alpha arena
/** @param {{ symbols: string[], persona_ids?: string[] | null }} body */
export const runArena = (body) => request('/api/arena/run', { method: 'POST', body });
/** @param {number} [lookbackDays] */
export const getArenaScoreboard = (lookbackDays = 90) =>
  request(`/api/arena/scoreboard?lookback_days=${encodeURIComponent(lookbackDays)}`);
