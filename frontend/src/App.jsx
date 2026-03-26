import React, { startTransition, useEffect, useState } from "react";
import Dashboard from "./components/Dashboard";
import SettingsPanel from "./components/SettingsPanel";

const DEFAULT_API_BASE_URL =
  typeof window === "undefined"
    ? "http://127.0.0.1:8000"
    : import.meta.env.DEV
      ? `${window.location.protocol}//${window.location.hostname}:8000`
      : window.location.origin;

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL;
const DEFAULT_WATCHLIST = [
  "AAPL",
  "MSFT",
  "AMZN",
  "GOOGL",
  "META",
  "NVDA",
  "TSLA",
  "JPM",
  "V",
  "MA",
  "UNH",
  "HD",
  "PG",
  "XOM",
  "KO",
  "PEP",
  "DIS",
  "CRM",
  "NFLX",
  "COST",
];

async function fetchJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    let detail = `请求失败（状态码 ${response.status}）`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        detail = payload.detail;
      }
    } catch {
      // Keep the default message if the backend did not return JSON.
    }
    throw new Error(detail);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  return response.json();
}

export default function App() {
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);
  const [orders, setOrders] = useState([]);
  const [monitoring, setMonitoring] = useState(null);
  const [botStatus, setBotStatus] = useState({ is_running: false });
  const [settingsStatus, setSettingsStatus] = useState(null);
  const [selectedSymbol, setSelectedSymbol] = useState(DEFAULT_WATCHLIST[0]);
  const [activeView, setActiveView] = useState("dashboard");
  const [isLoading, setIsLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [error, setError] = useState("");
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    let isActive = true;

    const loadDashboard = async () => {
      try {
        const settingsResult = await fetchJson("/api/settings/status");

        if (!isActive) {
          return;
        }

        setSettingsStatus(settingsResult);

        if (!settingsResult?.is_ready) {
          setActiveView("settings");
          setAccount(null);
          setPositions([]);
          setTrades([]);
          setOrders([]);
          setMonitoring({
            selected_symbols: DEFAULT_WATCHLIST,
            candidate_pool: [],
            tracked_symbols: [],
            universe_asset_count: 0,
          });
          setBotStatus({ is_running: false });
          setError("");
          setIsLoading(false);
          return;
        }

        const [
          accountResult,
          positionsResult,
          tradesResult,
          ordersResult,
          botStatusResult,
          monitoringResult,
        ] = await Promise.allSettled([
          fetchJson("/api/account"),
          fetchJson("/api/positions"),
          fetchJson("/api/trades"),
          fetchJson("/api/orders?status=all"),
          fetchJson("/api/bot/status"),
          fetchJson("/api/monitoring"),
        ]);

        if (!isActive) {
          return;
        }

        const nextErrors = [];

        if (accountResult.status === "fulfilled") {
          setAccount(accountResult.value);
        } else {
          setAccount(null);
          nextErrors.push(accountResult.reason?.message ?? "账户数据当前不可用。");
        }

        if (positionsResult.status === "fulfilled") {
          setPositions(positionsResult.value);
        } else {
          setPositions([]);
          nextErrors.push(positionsResult.reason?.message ?? "持仓数据当前不可用。");
        }

        if (tradesResult.status === "fulfilled") {
          setTrades(tradesResult.value);
        } else {
          setTrades([]);
          nextErrors.push(tradesResult.reason?.message ?? "成交历史当前不可用。");
        }

        if (ordersResult.status === "fulfilled") {
          setOrders(ordersResult.value ?? []);
        } else {
          setOrders([]);
          nextErrors.push(ordersResult.reason?.message ?? "订单列表当前不可用。");
        }

        if (botStatusResult.status === "fulfilled") {
          setBotStatus(botStatusResult.value ?? { is_running: false });
        } else {
          setBotStatus({ is_running: false });
          nextErrors.push(botStatusResult.reason?.message ?? "机器人状态当前不可用。");
        }

        if (monitoringResult.status === "fulfilled") {
          setMonitoring(monitoringResult.value);
        } else {
          setMonitoring({
            selected_symbols: DEFAULT_WATCHLIST,
            candidate_pool: [],
            tracked_symbols: [],
            universe_asset_count: 0,
          });
          nextErrors.push(
            monitoringResult.reason?.message ?? "候选池和趋势面板当前不可用。"
          );
        }

        setSelectedSymbol((currentSymbol) => {
          if (currentSymbol) {
            return currentSymbol;
          }

          if (positionsResult.status === "fulfilled" && positionsResult.value[0]?.symbol) {
            return positionsResult.value[0].symbol;
          }

          if (tradesResult.status === "fulfilled" && tradesResult.value[0]?.symbol) {
            return tradesResult.value[0].symbol;
          }

          if (
            monitoringResult.status === "fulfilled" &&
            monitoringResult.value?.selected_symbols?.[0]
          ) {
            return monitoringResult.value.selected_symbols[0];
          }

          return DEFAULT_WATCHLIST[0];
        });

        setError(nextErrors.join(" "));
      } catch (loadError) {
        if (!isActive) {
          return;
        }
        setError(loadError.message || "设置状态当前不可用。");
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    loadDashboard();
    const intervalId = window.setInterval(loadDashboard, 30000);

    return () => {
      isActive = false;
      window.clearInterval(intervalId);
    };
  }, [refreshNonce]);

  const selectSymbol = (symbol) => {
    if (!symbol) {
      return;
    }

    startTransition(() => {
      setSelectedSymbol(symbol.toUpperCase());
    });
  };

  const refreshDashboard = () => {
    setRefreshNonce((currentValue) => currentValue + 1);
  };

  const saveSettings = async (payload) => {
    setActionBusy("settings");

    try {
      const response = await fetch(`${API_BASE_URL}/api/settings`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let detail = `请求失败（状态码 ${response.status}）`;
        try {
          const errorPayload = await response.json();
          if (errorPayload?.detail) {
            detail = errorPayload.detail;
          }
        } catch {
          // Keep the default error message.
        }
        throw new Error(detail);
      }

      const nextStatus = await response.json();
      setSettingsStatus(nextStatus);
      setActionMessage(
        nextStatus.updated_keys?.length
          ? `已保存 ${nextStatus.updated_keys.length} 项设置。`
          : "设置已提交。"
      );
      setError("");

      if (nextStatus.is_ready) {
        setActiveView("dashboard");
        refreshDashboard();
      }

      return { ok: true, status: nextStatus };
    } catch (actionError) {
      setActionMessage("");
      setError(actionError.message);
      return { ok: false };
    } finally {
      setActionBusy("");
    }
  };

  const addWatchlistSymbol = async (symbol) => {
    const normalizedSymbol = String(symbol || "").trim().toUpperCase();
    if (!normalizedSymbol) {
      return;
    }

    setActionBusy("watchlist");

    try {
      const response = await fetch(`${API_BASE_URL}/api/watchlist`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ symbol: normalizedSymbol }),
      });

      if (!response.ok) {
        let detail = `请求失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Keep the default error text.
        }
        throw new Error(detail);
      }

      setActionMessage(`${normalizedSymbol} 已加入自选列表。`);
      setError("");
      refreshDashboard();
    } catch (actionError) {
      setActionMessage("");
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const removeWatchlistSymbol = async (symbol) => {
    const normalizedSymbol = String(symbol || "").trim().toUpperCase();
    if (!normalizedSymbol) {
      return;
    }

    setActionBusy("watchlist");

    try {
      const response = await fetch(`${API_BASE_URL}/api/watchlist/${normalizedSymbol}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        let detail = `请求失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Keep the default error text.
        }
        throw new Error(detail);
      }

      const nextWatchlist = await response.json();
      setMonitoring((current) =>
        current ? { ...current, selected_symbols: nextWatchlist } : current
      );
      setSelectedSymbol((currentSymbol) => {
        if (currentSymbol !== normalizedSymbol) {
          return currentSymbol;
        }
        return nextWatchlist[0] || DEFAULT_WATCHLIST[0];
      });
      setActionMessage(`${normalizedSymbol} 已从自选列表移除。`);
      setError("");
      refreshDashboard();
    } catch (actionError) {
      setActionMessage("");
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const refreshMonitoring = async () => {
    setActionBusy("monitoring");

    try {
      const response = await fetch(`${API_BASE_URL}/api/monitoring/refresh`, {
        method: "POST",
      });

      if (!response.ok) {
        let detail = `请求失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Keep the default error text.
        }
        throw new Error(detail);
      }

      const payload = await response.json();
      setMonitoring(payload);
      setActionMessage("已刷新 AI 候选池与趋势快照。");
      setError("");
    } catch (actionError) {
      setActionMessage("");
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const runControlAction = async (path, busyKey) => {
    setActionBusy(busyKey);

    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "POST",
      });

      if (!response.ok) {
        let detail = `请求失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Use the default error text when the response is not JSON.
        }
        throw new Error(detail);
      }

      const payload = await response.json();
      setActionMessage(payload?.message ?? "操作已提交。");
      setError("");
      refreshDashboard();
    } catch (actionError) {
      setActionMessage("");
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const watchlist = Array.isArray(monitoring?.selected_symbols)
    ? monitoring.selected_symbols
    : isLoading
      ? []
      : DEFAULT_WATCHLIST;

  const monitoringReady = Array.isArray(monitoring?.tracked_symbols);
  const marketTapeItems = monitoringReady
    ? (monitoring?.tracked_symbols ?? []).slice(0, 8)
    : [];
  const missingKeyCount = settingsStatus?.missing_required_keys?.length ?? 0;
  const displayName = getSettingValue(settingsStatus, "DISPLAY_NAME");

  useEffect(() => {
    document.title = displayName || "Trading Raven Platform";
  }, [displayName]);

  return (
    <div className="app-shell">
      <section className="market-tape">
        <div className="market-tape-label">行情带</div>
        <div className="market-tape-list">
          {marketTapeItems.length ? (
            marketTapeItems.map((item) => (
              <button
                key={item.symbol}
                type="button"
                className={`tape-chip ${selectedSymbol === item.symbol ? "is-active" : ""}`}
                onClick={() => selectSymbol(item.symbol)}
              >
                <span className="tape-symbol">{item.symbol}</span>
                <span className="tape-price">
                  {formatTapePrice(item.trend?.current_price)}
                </span>
                <span
                  className={`tape-change ${
                    Number(item.trend?.day_change_percent ?? 0) > 0
                      ? "profit"
                      : Number(item.trend?.day_change_percent ?? 0) < 0
                        ? "loss"
                        : ""
                  }`}
                >
                  {formatPercent(item.trend?.day_change_percent)}
                </span>
              </button>
            ))
          ) : (
            <span className="market-tape-empty">等待行情与自选数据同步...</span>
          )}
        </div>
        <div className="market-tape-meta">
          {botStatus?.is_running ? "策略引擎在线" : "策略引擎待命"}
        </div>
      </section>

      <header className="hero">
        <div className="hero-copy">
          <div className="hero-brand">
            <div className="hero-logo-shell">
              <img className="hero-logo" src="/brand-logo.svg" alt="交易乌鸦 logo" />
            </div>
            <div className="hero-brand-copy">
              <p className="eyebrow">策略 B 执行台</p>
              <h1>{displayName || "个人自动交易平台"}</h1>
            </div>
          </div>
          <div className="hero-command-bar">
            <span className="hero-badge hero-badge--accent">
              {botStatus?.is_running ? "运行中" : "待启动"}
            </span>
            <span className="hero-badge">自选 {watchlist.length}</span>
            <span className="hero-badge">聚焦 {selectedSymbol || "未选择"}</span>
            <span className={`hero-badge ${missingKeyCount ? "hero-badge--warning" : ""}`}>
              {missingKeyCount ? `待配置 ${missingKeyCount} 项` : "环境已就绪"}
            </span>
          </div>
          <p className="hero-text">
            用更接近行情终端的方式查看账户、仓位、策略和单股研究，把决策信息集中在一个桌面里。
          </p>
          <div className="segmented-control hero-segmented">
            <button
              type="button"
              className={`segment-button ${activeView === "dashboard" ? "is-active" : ""}`}
              onClick={() => setActiveView("dashboard")}
              disabled={!settingsStatus?.is_ready}
            >
              仪表盘
            </button>
            <button
              type="button"
              className={`segment-button ${activeView === "settings" ? "is-active" : ""}`}
              onClick={() => setActiveView("settings")}
            >
              设置
            </button>
          </div>
        </div>

        <div className="stat-grid">
          <MetricCard
            label="净值"
            value={formatCurrency(account?.equity)}
            tone="primary"
          />
          <MetricCard
            label="现金"
            value={formatCurrency(account?.cash)}
            tone="neutral"
          />
          <MetricCard
            label="购买力"
            value={formatCurrency(account?.buying_power)}
            tone="neutral"
          />
          <MetricCard
            label="状态"
            value={account?.status ?? "不可用"}
            tone="success"
          />
        </div>
      </header>

      {error ? <div className="banner error-banner">{error}</div> : null}
      {actionMessage ? <div className="banner success-banner">{actionMessage}</div> : null}
      {isLoading ? <div className="banner">正在加载交易面板...</div> : null}

      {activeView === "settings" ? (
        <SettingsPanel
          settingsStatus={settingsStatus}
          onSave={saveSettings}
          onBack={() => setActiveView("dashboard")}
          actionBusy={actionBusy}
        />
      ) : (
        <Dashboard
          account={account}
          positions={positions}
          trades={trades}
          orders={orders}
          monitoring={monitoring}
          monitoringReady={monitoringReady}
          botStatus={botStatus}
          selectedSymbol={selectedSymbol}
          onSelectSymbol={selectSymbol}
          apiBaseUrl={API_BASE_URL}
          watchlist={watchlist}
          onStartBot={() => runControlAction("/api/bot/start", "start")}
          onStopBot={() => runControlAction("/api/bot/stop", "stop")}
          onCancelOrders={() => runControlAction("/api/orders/cancel", "cancel")}
          onClosePositions={() => runControlAction("/api/positions/close", "close")}
          onRefresh={refreshDashboard}
          onRefreshMonitoring={refreshMonitoring}
          onAddWatchlistSymbol={addWatchlistSymbol}
          onRemoveWatchlistSymbol={removeWatchlistSymbol}
          actionBusy={actionBusy}
        />
      )}
    </div>
  );
}

function MetricCard({ label, value, tone }) {
  return (
    <article className={`stat-card stat-card--${tone}`}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
    </article>
  );
}

function formatCurrency(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }

  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatTapePrice(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 100 ? 2 : 3,
  }).format(value);
}

function getSettingValue(settingsStatus, key) {
  const matchedItem = settingsStatus?.items?.find((item) => item.key === key);
  return String(matchedItem?.value ?? "").trim();
}
