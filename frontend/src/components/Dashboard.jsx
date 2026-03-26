import React, { useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import CandidatePoolPanel from "./CandidatePoolPanel";
import MarketWorkbench from "./MarketWorkbench";
import PanelCollapseButton from "./PanelCollapseButton";
import PortfolioTable from "./PortfolioTable";
import StrategyStudioPanel from "./StrategyStudioPanel";
import TrendMonitorPanel from "./TrendMonitorPanel";
import UniverseExplorer from "./UniverseExplorer";

export default function Dashboard({
  account,
  positions,
  trades,
  orders,
  botStatus,
  monitoringReady,
  selectedSymbol,
  onSelectSymbol,
  apiBaseUrl,
  watchlist,
  monitoring,
  onStartBot,
  onStopBot,
  onCancelOrders,
  onClosePositions,
  onRefresh,
  onRefreshMonitoring,
  onAddWatchlistSymbol,
  onRemoveWatchlistSymbol,
  actionBusy,
}) {
  const [portfolioCollapsed, setPortfolioCollapsed] = useState(false);
  const [ordersCollapsed, setOrdersCollapsed] = useState(false);

  const chartData = trades
    .slice(0, 6)
    .reverse()
    .map((trade) => ({
      symbol: trade.symbol,
      pnl: Number(trade.net_profit ?? 0),
    }));

  const investedCapital = positions.reduce(
    (total, position) => total + Number(position.market_value ?? 0),
    0
  );
  const summaryItems = [
    {
      label: "监控股票",
      value: `${watchlist.length}`,
      caption: "自选池规模",
    },
    {
      label: "候选池",
      value: `${monitoring?.candidate_pool?.length ?? 0}`,
      caption: "今日 AI 备选",
    },
    {
      label: "订单追踪",
      value: `${orders.length}`,
      caption: "最近订单数",
    },
    {
      label: "机器人",
      value: botStatus?.is_running ? "运行中" : "待机",
      caption: formatUptime(botStatus?.uptime_seconds),
    },
  ];

  return (
    <main className="dashboard-grid">
      <section className="dashboard-main">
        <section className="panel session-summary-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">会话概览</p>
              <h2>交易终端总览</h2>
            </div>
            <span className="panel-pill">
              净值 {formatCurrency(account?.equity)}
            </span>
          </div>

          <div className="session-summary-grid">
            {summaryItems.map((item) => (
              <article key={item.label} className="session-summary-item">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.caption}</small>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">持仓</p>
              <h2>当前持仓与历史成交</h2>
            </div>
            <div className="panel-header-actions">
              <span className="panel-pill">
                持仓 {positions.length} / 历史 {trades.length}
              </span>
              <PanelCollapseButton
                collapsed={portfolioCollapsed}
                onToggle={() => setPortfolioCollapsed((current) => !current)}
              />
            </div>
          </div>

          {!portfolioCollapsed ? (
            <PortfolioTable
              positions={positions}
              trades={trades}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={onSelectSymbol}
            />
          ) : null}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">表现</p>
              <h2>最近平仓盈亏</h2>
            </div>
            <span className="panel-pill">
              净值 {formatCurrency(account?.equity)}
            </span>
          </div>

          {chartData.length ? (
            <div className="performance-chart">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={chartData}>
                  <XAxis
                    dataKey="symbol"
                    tickLine={false}
                    axisLine={false}
                    stroke="#8b9bb8"
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    stroke="#8b9bb8"
                    tickFormatter={(value) => `${value}`}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(29, 66, 122, 0.08)" }}
                    contentStyle={{
                      backgroundColor: "#ffffff",
                      border: "1px solid rgba(184, 198, 214, 0.96)",
                      borderRadius: "12px",
                      boxShadow: "0 18px 34px rgba(21, 42, 73, 0.14)",
                    }}
                    formatter={(value) => formatCurrency(Number(value))}
                  />
                  <Bar dataKey="pnl" radius={[12, 12, 2, 2]}>
                    {chartData.map((entry) => (
                      <Cell
                        key={`${entry.symbol}-${entry.pnl}`}
                        fill={entry.pnl >= 0 ? "#e44d4d" : "#1f9d6b"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="empty-state">暂时还没有平仓记录。</div>
          )}
        </section>

        <CandidatePoolPanel
          candidatePool={monitoring?.candidate_pool ?? []}
          selectedSymbols={watchlist}
          onSelectSymbol={onSelectSymbol}
          onAddWatchlistSymbol={onAddWatchlistSymbol}
          onRefreshMonitoring={onRefreshMonitoring}
          actionBusy={actionBusy}
        />

        <TrendMonitorPanel
          trackedSymbols={monitoring?.tracked_symbols ?? []}
          selectedSymbol={selectedSymbol}
          onSelectSymbol={onSelectSymbol}
        />

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">订单</p>
              <h2>最近订单状态</h2>
            </div>
            <div className="panel-header-actions">
              <span className="panel-pill">共 {orders.length} 笔</span>
              <PanelCollapseButton
                collapsed={ordersCollapsed}
                onToggle={() => setOrdersCollapsed((current) => !current)}
              />
            </div>
          </div>

          {!ordersCollapsed ? (
            <div className="table-shell">
              <table className="positions-table">
                <thead>
                  <tr>
                    <th>股票</th>
                    <th>方向</th>
                    <th>类型</th>
                    <th>状态</th>
                    <th>数量/金额</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.length ? (
                    orders.slice(0, 8).map((order) => (
                      <tr key={order.order_id}>
                        <td>{order.symbol}</td>
                        <td>{formatSide(order.side)}</td>
                        <td>{formatOrderType(order.order_type)}</td>
                        <td>
                          <span
                            className={`order-status order-status--${String(
                              order.status || "unknown"
                            ).toLowerCase()}`}
                          >
                            {formatOrderStatus(order.status)}
                          </span>
                        </td>
                        <td>{formatOrderSize(order)}</td>
                        <td>{formatDate(order.created_at)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="empty-row" colSpan="6">
                        暂时还没有订单记录。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </section>

      <aside className="dashboard-side">
        <MarketWorkbench
          selectedSymbol={selectedSymbol}
          watchlist={watchlist}
          monitoring={monitoring}
          monitoringReady={monitoringReady}
          apiBaseUrl={apiBaseUrl}
          onSelectSymbol={onSelectSymbol}
          onRemoveWatchlistSymbol={onRemoveWatchlistSymbol}
          actionBusy={actionBusy}
        />

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">机器人</p>
              <h2>策略控制</h2>
            </div>
            <span
              className={`status-chip ${
                botStatus?.is_running ? "status-chip--running" : "status-chip--stopped"
              }`}
            >
              {botStatus?.is_running ? "运行中" : "已停止"}
            </span>
          </div>

          <div className="strategy-live-card">
            <div>
              <p className="panel-kicker">当前策略</p>
              <h3>{botStatus?.active_strategy_name || "系统默认 Strategy B"}</h3>
            </div>
            <p>
              新策略保存或切换后，不会立刻改动运行中的机器人。
              {botStatus?.is_running ? "请停止后重新启动机器人以应用新策略。" : "下次启动机器人时会自动应用。"}
            </p>
          </div>

          <div className="action-grid">
            <button
              type="button"
              className="action-button"
              onClick={onStartBot}
              disabled={botStatus?.is_running || actionBusy !== ""}
            >
              {actionBusy === "start" ? "启动中..." : "启动机器人"}
            </button>
            <button
              type="button"
              className="action-button action-button--neutral"
              onClick={onStopBot}
              disabled={!botStatus?.is_running || actionBusy !== ""}
            >
              {actionBusy === "stop" ? "停止中..." : "停止机器人"}
            </button>
            <button
              type="button"
              className="action-button action-button--neutral"
              onClick={onCancelOrders}
              disabled={actionBusy !== ""}
            >
              {actionBusy === "cancel" ? "处理中..." : "撤销全部挂单"}
            </button>
            <button
              type="button"
              className="action-button action-button--danger"
              onClick={onClosePositions}
              disabled={actionBusy !== ""}
            >
              {actionBusy === "close" ? "处理中..." : "全部平仓"}
            </button>
            <button
              type="button"
              className="action-button action-button--ghost"
              onClick={onRefresh}
              disabled={actionBusy !== ""}
            >
              立即刷新
            </button>
          </div>

          <dl className="control-meta">
            <div>
              <dt>当前策略</dt>
              <dd>{botStatus?.active_strategy_name || "系统默认 Strategy B"}</dd>
            </div>
            <div>
              <dt>运行时长</dt>
              <dd>{formatUptime(botStatus?.uptime_seconds)}</dd>
            </div>
            <div>
              <dt>最近错误</dt>
              <dd>{botStatus?.last_error || "暂无"}</dd>
            </div>
          </dl>
        </section>

        <StrategyStudioPanel apiBaseUrl={apiBaseUrl} botStatus={botStatus} />
        <UniverseExplorer
          apiBaseUrl={apiBaseUrl}
          selectedSymbols={watchlist}
          universeAssetCount={monitoring?.universe_asset_count ?? 0}
          onAddWatchlistSymbol={onAddWatchlistSymbol}
          actionBusy={actionBusy}
        />

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">风险</p>
              <h2>账户概览</h2>
            </div>
          </div>

          <dl className="risk-grid">
            <div>
              <dt>当前关注</dt>
              <dd>{selectedSymbol || "未选择"}</dd>
            </div>
            <div>
              <dt>持仓市值</dt>
              <dd>{formatCurrency(investedCapital)}</dd>
            </div>
            <div>
              <dt>策略基准</dt>
              <dd>昨收价对比当前价</dd>
            </div>
            <div>
              <dt>执行模式</dt>
              <dd>Alpaca 模拟账户</dd>
            </div>
          </dl>
        </section>
      </aside>
    </main>
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

function formatDate(value) {
  if (!value) {
    return "暂无";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无";
  }

  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatSide(value) {
  return value === "buy" ? "买入" : value === "sell" ? "卖出" : value || "未知";
}

function formatOrderType(value) {
  return value === "market" ? "市价" : value || "未知";
}

function formatOrderStatus(value) {
  const statusMap = {
    accepted: "已接受",
    new: "新建",
    partially_filled: "部分成交",
    filled: "已成交",
    canceled: "已撤销",
    pending_cancel: "撤销中",
    rejected: "已拒绝",
    done_for_day: "当日结束",
  };

  return statusMap[value] || value || "未知";
}

function formatOrderSize(order) {
  if (typeof order.notional === "number") {
    return formatCurrency(order.notional);
  }
  if (typeof order.qty === "number") {
    return order.qty.toFixed(4);
  }
  return "暂无";
}

function formatUptime(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }

  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;

  if (hours > 0) {
    return `${hours} 小时 ${minutes} 分`;
  }

  if (minutes > 0) {
    return `${minutes} 分 ${seconds} 秒`;
  }

  return `${seconds} 秒`;
}
