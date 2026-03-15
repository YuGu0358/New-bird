import React, { useState } from "react";
import PanelCollapseButton from "./PanelCollapseButton";

export default function TrendMonitorPanel({
  trackedSymbols,
  selectedSymbol,
  onSelectSymbol,
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">趋势</p>
          <h2>自选 / 候选走势对比</h2>
        </div>
        <div className="panel-header-actions">
          <span className="panel-pill">日 / 周 / 月</span>
          <PanelCollapseButton
            collapsed={collapsed}
            onToggle={() => setCollapsed((current) => !current)}
          />
        </div>
      </div>

      {!collapsed ? (
        <div className="table-shell">
          <table className="positions-table">
            <thead>
              <tr>
                <th>股票</th>
                <th>标签</th>
                <th>现价</th>
                <th>上一天</th>
                <th>上一周</th>
                <th>上一月</th>
              </tr>
            </thead>
            <tbody>
              {trackedSymbols?.length ? (
                trackedSymbols.map((item) => (
                  <tr key={item.symbol}>
                    <td>
                      <button
                        type="button"
                        className={`symbol-button ${selectedSymbol === item.symbol ? "is-active" : ""}`}
                        onClick={() => onSelectSymbol(item.symbol)}
                      >
                        {item.symbol}
                      </button>
                    </td>
                    <td>
                      <div className="tag-list">
                        {item.tags?.map((tag) => (
                          <span key={`${item.symbol}-${tag}`} className="mini-tag">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>{formatCurrency(item.trend?.current_price)}</td>
                    <td className={toneClass(item.trend?.day_change_percent)}>
                      {formatPercent(item.trend?.day_change_percent)}
                    </td>
                    <td className={toneClass(item.trend?.week_change_percent)}>
                      {formatPercent(item.trend?.week_change_percent)}
                    </td>
                    <td className={toneClass(item.trend?.month_change_percent)}>
                      {formatPercent(item.trend?.month_change_percent)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty-row" colSpan="6">
                    暂时还没有趋势数据。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
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

function toneClass(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "";
  }
  return value > 0 ? "profit" : "loss";
}
