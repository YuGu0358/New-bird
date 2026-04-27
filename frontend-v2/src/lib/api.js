// Thin fetch wrapper. The Vite dev server proxies /api → 127.0.0.1:8000.
// In production builds we serve from same origin, so relative URLs work too.

export class ApiError extends Error {
  constructor(message, { status, detail } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = 'GET', body, headers } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
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
export const getChart = (symbol, range = '1m') =>
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
