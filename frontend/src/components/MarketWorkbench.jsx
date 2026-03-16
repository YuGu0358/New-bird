import React, { useState } from "react";
import NewsPanel from "./NewsPanel";
import PanelCollapseButton from "./PanelCollapseButton";
import PriceAlertsPanel from "./PriceAlertsPanel";
import PriceChartPanel from "./PriceChartPanel";
import ResearchPanel from "./ResearchPanel";

const TAB_OPTIONS = [
  { value: "chart", label: "走势" },
  { value: "alerts", label: "提醒 / 交易" },
  { value: "news", label: "新闻" },
  { value: "research", label: "研究" },
];

export default function MarketWorkbench({
  selectedSymbol,
  watchlist,
  monitoring,
  monitoringReady,
  apiBaseUrl,
  onSelectSymbol,
  onRemoveWatchlistSymbol,
  actionBusy,
}) {
  const [activeTab, setActiveTab] = useState("chart");
  const [watchlistCollapsed, setWatchlistCollapsed] = useState(false);

  const selectedTracked =
    monitoring?.tracked_symbols?.find((item) => item.symbol === selectedSymbol) ?? null;

  const selectedTags = selectedTracked?.tags ?? [];
  const trend = selectedTracked?.trend ?? null;
  const loadingTrend = !monitoringReady;
  const loadingMessage = selectedSymbol
    ? `正在同步 ${selectedSymbol} 的日/周/月趋势数据...`
    : "正在同步单股工作台数据...";

  return (
    <section className="panel market-workbench">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">聚焦</p>
          <h2>单股工作台</h2>
        </div>
        <div className="panel-header-actions">
          <span className="panel-pill">{selectedSymbol || "未选择"}</span>
        </div>
      </div>

      <div className="market-workbench-hero">
        <div className="market-workbench-symbol">
          <div className="market-symbol-mark">{selectedSymbol || "--"}</div>
          <div className="market-symbol-copy">
            <h3>{selectedSymbol ? `${selectedSymbol} 观察台` : "请选择一只股票"}</h3>
            <p>
              {loadingTrend
                ? loadingMessage
                : "把图表、提醒、新闻和研究集中在一个地方，减少来回切换和纵向堆叠。"}
            </p>
            <div className="tag-list">
              {loadingTrend ? (
                <span className="mini-tag">同步中</span>
              ) : selectedTags.length ? (
                selectedTags.map((tag) => (
                  <span key={`${selectedSymbol}-${tag}`} className="mini-tag">
                    {tag}
                  </span>
                ))
              ) : (
                <span className="mini-tag">待观察</span>
              )}
            </div>
          </div>
        </div>

        <div className="market-trend-grid">
          <MetricTile
            label="现价"
            value={loadingTrend ? "加载中" : formatCurrency(trend?.current_price)}
            tone="neutral"
          />
          <MetricTile
            label="日变化"
            value={loadingTrend ? "加载中" : formatPercent(trend?.day_change_percent)}
            tone={toneClass(trend?.day_change_percent)}
          />
          <MetricTile
            label="周变化"
            value={loadingTrend ? "加载中" : formatPercent(trend?.week_change_percent)}
            tone={toneClass(trend?.week_change_percent)}
          />
          <MetricTile
            label="月变化"
            value={loadingTrend ? "加载中" : formatPercent(trend?.month_change_percent)}
            tone={toneClass(trend?.month_change_percent)}
          />
        </div>
      </div>

      <section className="workbench-priority-card">
        <div className="workbench-priority-copy">
          <p className="panel-kicker">自动动作</p>
          <h3>条件提醒 / 自动交易</h3>
          <p>
            直接为当前股票设置目标价、预期涨跌幅，以及触发后的邮件提醒或自动下单金额。
          </p>
          <div className="tag-list">
            <span className="mini-tag">目标价格</span>
            <span className="mini-tag">涨跌幅触发</span>
            <span className="mini-tag">自动买入金额</span>
          </div>
        </div>

        <div className="workbench-priority-actions">
          <button
            type="button"
            className="action-button"
            onClick={() => setActiveTab("alerts")}
          >
            {activeTab === "alerts" ? "正在查看提醒 / 交易" : "设置提醒 / 自动交易"}
          </button>
          <span className="panel-pill">Paper 账户默认可自动执行</span>
        </div>
      </section>

      <div className="market-workbench-toolbar">
        <div className="segmented-control market-tabs">
          {TAB_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`segment-button ${activeTab === option.value ? "is-active" : ""}`}
              onClick={() => setActiveTab(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="panel-header-actions">
          <span className="panel-pill">
            {loadingTrend ? "自选同步中" : `自选 ${watchlist.length}`}
          </span>
          <PanelCollapseButton
            collapsed={watchlistCollapsed}
            onToggle={() => setWatchlistCollapsed((current) => !current)}
          />
        </div>
      </div>

      {!watchlistCollapsed ? (
        loadingTrend ? (
          <div className="empty-state">正在同步自选列表...</div>
        ) : watchlist.length ? (
          <div className="workbench-watchlist">
            {watchlist.map((symbol) => (
              <div
                key={symbol}
                className={`watchlist-chip ${selectedSymbol === symbol ? "is-active" : ""}`}
              >
                <button
                  type="button"
                  className={`symbol-button ${selectedSymbol === symbol ? "is-active" : ""}`}
                  onClick={() => onSelectSymbol(symbol)}
                >
                  {symbol}
                </button>
                <button
                  type="button"
                  className="watchlist-remove-button"
                  onClick={() => onRemoveWatchlistSymbol(symbol)}
                  disabled={actionBusy !== ""}
                  aria-label={`删除 ${symbol}`}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">当前还没有自选股票。</div>
        )
      ) : null}

      <div className="workbench-surface">
        {activeTab === "chart" ? (
          <PriceChartPanel symbol={selectedSymbol} apiBaseUrl={apiBaseUrl} embedded />
        ) : null}
        {activeTab === "alerts" ? (
          <PriceAlertsPanel symbol={selectedSymbol} apiBaseUrl={apiBaseUrl} embedded />
        ) : null}
        {activeTab === "news" ? (
          <NewsPanel symbol={selectedSymbol} apiBaseUrl={apiBaseUrl} embedded />
        ) : null}
        {activeTab === "research" ? (
          <ResearchPanel symbol={selectedSymbol} apiBaseUrl={apiBaseUrl} embedded />
        ) : null}
      </div>
    </section>
  );
}

function MetricTile({ label, value, tone }) {
  return (
    <article className={`market-trend-tile market-trend-tile--${tone || "neutral"}`}>
      <span>{label}</span>
      <strong>{value}</strong>
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
    return "暂无";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toneClass(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "neutral";
  }
  return value > 0 ? "profit" : "loss";
}
