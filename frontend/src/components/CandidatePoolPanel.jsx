import React, { useState } from "react";
import PanelCollapseButton from "./PanelCollapseButton";

export default function CandidatePoolPanel({
  candidatePool,
  selectedSymbols,
  onSelectSymbol,
  onAddWatchlistSymbol,
  onRefreshMonitoring,
  actionBusy,
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">候选池</p>
          <h2>AI 每日备选 5 只</h2>
        </div>
        <div className="panel-header-actions">
          <PanelCollapseButton
            collapsed={collapsed}
            onToggle={() => setCollapsed((current) => !current)}
          />
          <button
            type="button"
            className="action-button action-button--ghost action-button--compact"
            onClick={onRefreshMonitoring}
            disabled={actionBusy !== ""}
          >
            {actionBusy === "monitoring" ? "刷新中..." : "刷新候选池"}
          </button>
        </div>
      </div>

      {!collapsed && candidatePool?.length ? (
        <div className="candidate-grid">
          {candidatePool.map((item) => {
            const isTracked = selectedSymbols.includes(item.symbol);
            return (
              <article key={item.symbol} className="candidate-card">
                <div className="candidate-card__header">
                  <div>
                    <span className="candidate-rank">#{item.rank}</span>
                    <h3>{item.symbol}</h3>
                  </div>
                  <span className="panel-pill">{item.category}</span>
                </div>

                <dl className="candidate-metrics">
                  <div>
                    <dt>综合分</dt>
                    <dd>{Number(item.score ?? 0).toFixed(2)}</dd>
                  </div>
                  <div>
                    <dt>日</dt>
                    <dd className={toneClass(item.trend?.day_change_percent)}>
                      {formatPercent(item.trend?.day_change_percent)}
                    </dd>
                  </div>
                  <div>
                    <dt>周</dt>
                    <dd className={toneClass(item.trend?.week_change_percent)}>
                      {formatPercent(item.trend?.week_change_percent)}
                    </dd>
                  </div>
                  <div>
                    <dt>月</dt>
                    <dd className={toneClass(item.trend?.month_change_percent)}>
                      {formatPercent(item.trend?.month_change_percent)}
                    </dd>
                  </div>
                </dl>

                <p className="candidate-copy">{item.reason}</p>

                <div className="candidate-actions">
                  <button
                    type="button"
                    className="action-button action-button--neutral"
                    onClick={() => onSelectSymbol(item.symbol)}
                  >
                    查看
                  </button>
                  <button
                    type="button"
                    className="action-button"
                    onClick={() => onAddWatchlistSymbol(item.symbol)}
                    disabled={isTracked || actionBusy !== ""}
                  >
                    {isTracked ? "已在自选" : "加入自选"}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      ) : null}

      {!collapsed && !candidatePool?.length ? (
        <div className="empty-state">候选池暂时不可用，稍后再试。</div>
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

function toneClass(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "";
  }
  return value > 0 ? "profit" : "loss";
}
