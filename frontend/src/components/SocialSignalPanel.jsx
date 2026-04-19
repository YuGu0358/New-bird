import React, { useEffect, useMemo, useState } from "react";

export default function SocialSignalPanel({ symbol, apiBaseUrl, embedded = false }) {
  const [keywordInput, setKeywordInput] = useState("");
  const [hours, setHours] = useState(6);
  const [payload, setPayload] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [error, setError] = useState("");

  const keywords = useMemo(
    () =>
      String(keywordInput || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    [keywordInput]
  );

  useEffect(() => {
    setPayload(null);
    setError("");
    setKeywordInput("");
    setHours(6);
  }, [symbol]);

  useEffect(() => {
    if (!symbol) {
      return;
    }
    void loadSignal(false, true);
  }, [symbol]);

  const loadSignal = async (execute = false, silent = false) => {
    if (!symbol) {
      return;
    }

    if (execute) {
      setIsExecuting(true);
    } else {
      setIsLoading(true);
    }
    if (!silent) {
      setError("");
    }

    try {
      const params = new URLSearchParams({
        symbol,
        hours: String(hours),
        lang: "en",
        execute: execute ? "true" : "false",
        force_refresh: "true",
      });
      keywords.forEach((item) => params.append("keyword", item));

      const response = await fetch(`${apiBaseUrl}/api/social/score?${params.toString()}`);
      if (!response.ok) {
        let detail = `社媒信号请求失败（状态码 ${response.status}）`;
        try {
          const errorPayload = await response.json();
          if (errorPayload?.detail) {
            detail = errorPayload.detail;
          }
        } catch {
          // Keep the default error text.
        }
        throw new Error(detail);
      }

      const nextPayload = await response.json();
      setPayload(nextPayload);
      setError("");
    } catch (loadError) {
      if (!silent) {
        setError(loadError.message);
      }
    } finally {
      setIsLoading(false);
      setIsExecuting(false);
    }
  };

  return (
    <section className={embedded ? "embedded-panel" : "panel"}>
      <div className={embedded ? "embedded-panel-header" : "panel-header"}>
        <div>
          <p className="panel-kicker">社媒信号</p>
          <h2>{embedded ? "社媒权重与触发" : "社媒权重与交易触发"}</h2>
        </div>
        <span className="panel-pill">{symbol || "请选择股票"}</span>
      </div>

      <div className="social-signal-toolbar">
        <div className="strategy-field">
          <span>附加关键词</span>
          <input
            type="text"
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            placeholder="例如 AI, earnings, demand"
          />
        </div>

        <div className="social-signal-toolbar__controls">
          <div className="segmented-control">
            {[6, 12, 24].map((value) => (
              <button
                key={value}
                type="button"
                className={`segment-button ${hours === value ? "is-active" : ""}`}
                onClick={() => setHours(value)}
                disabled={isLoading || isExecuting}
              >
                {value}h
              </button>
            ))}
          </div>

          <div className="social-signal-actions">
            <button
              type="button"
              className="action-button action-button--neutral"
              onClick={() => loadSignal(false)}
              disabled={!symbol || isLoading || isExecuting}
            >
              {isLoading ? "刷新中..." : "刷新社媒信号"}
            </button>
            <button
              type="button"
              className="action-button"
              onClick={() => loadSignal(true)}
              disabled={!symbol || isLoading || isExecuting}
            >
              {isExecuting ? "执行中..." : "按社媒信号执行"}
            </button>
          </div>
        </div>
      </div>

      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!error && !payload && !isLoading ? (
        <div className="news-state">
          这里会显示当前股票的社媒评分、行情评分、最终权重、触发动作和顶部评论来源。
        </div>
      ) : null}

      {payload ? (
        <div className="social-signal-content">
          <div className="social-signal-metric-grid">
            <MetricCard label="社媒评分" value={formatSignedNumber(payload.social_score)} tone={scoreTone(payload.social_score)} />
            <MetricCard label="行情评分" value={formatSignedNumber(payload.market_score)} tone={scoreTone(payload.market_score)} />
            <MetricCard label="最终权重" value={formatSignedNumber(payload.final_weight)} tone={scoreTone(payload.final_weight)} />
            <MetricCard label="动作" value={formatAction(payload.action)} tone={actionTone(payload.action)} />
            <MetricCard
              label="置信度"
              value={`${payload.confidence_label || "low"} / ${Number(payload.confidence || 0).toFixed(2)}`}
              tone={confidenceTone(payload.confidence_label)}
            />
            <MetricCard
              label="执行结果"
              value={payload.executed ? "已执行" : "未执行"}
              tone={payload.executed ? "profit" : "neutral"}
            />
          </div>

          <div className="social-signal-query-card">
            <div className="social-signal-query-meta">
              <span>{payload.query_profile?.company_name || symbol}</span>
              <span>窗口 {payload.query_profile?.hours || hours}h</span>
              <span>{formatDate(payload.generated_at)}</span>
            </div>
            <div className="tag-list">
              {(payload.query_profile?.keywords || []).length ? (
                payload.query_profile.keywords.map((item) => (
                  <span key={`${symbol}-keyword-${item}`} className="mini-tag">
                    {item}
                  </span>
                ))
              ) : (
                <span className="mini-tag">仅默认上下文词</span>
              )}
            </div>
            <dl className="social-signal-query-grid">
              <div>
                <dt>X 查询</dt>
                <dd>{payload.query_profile?.x_query || "暂无"}</dd>
              </div>
              <div>
                <dt>Tavily 查询</dt>
                <dd>{payload.query_profile?.tavily_query || "暂无"}</dd>
              </div>
            </dl>
          </div>

          {payload.reasons?.length ? (
            <section className="research-block social-signal-block">
              <h3>判断理由</h3>
              <ul className="insight-list">
                {payload.reasons.map((item, index) => (
                  <li key={`${symbol}-reason-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <div className="social-signal-columns">
            <section className="research-block social-signal-block">
              <h3>顶部评论</h3>
              {payload.top_posts?.length ? (
                <div className="social-signal-list">
                  {payload.top_posts.map((item) => (
                    <article key={`${item.post_id}-${item.url}`} className="social-signal-card">
                      <div className="social-signal-card__header">
                        <div>
                          <strong>@{item.author?.username || "unknown"}</strong>
                          <div className="social-signal-card__meta">
                            <span>{item.classification?.label || "n/a"}</span>
                            <span>权重 {Number(item.weight || 0).toFixed(3)}</span>
                            <span>赞 {item.metrics?.like_count || 0}</span>
                          </div>
                        </div>
                        <a href={item.url} target="_blank" rel="noreferrer">
                          打开
                        </a>
                      </div>
                      <p>{item.text}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <p>当前没有可展示的高相关评论。</p>
              )}
            </section>

            <section className="research-block social-signal-block">
              <h3>顶部来源</h3>
              {payload.top_sources?.length ? (
                <div className="social-signal-list">
                  {payload.top_sources.map((item) => (
                    <article key={`${item.url}-${item.title}`} className="social-signal-card">
                      <div className="social-signal-card__header">
                        <div>
                          <strong>{item.title || item.url}</strong>
                          <div className="social-signal-card__meta">
                            <span>{item.domain || item.source || "web"}</span>
                            <span>分数 {Number(item.score || 0).toFixed(2)}</span>
                          </div>
                        </div>
                        <a href={item.url} target="_blank" rel="noreferrer">
                          打开
                        </a>
                      </div>
                      <p>{item.content || "当前来源未返回摘要片段。点击链接查看原文。"}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <p>当前没有可展示的新闻来源。</p>
              )}
            </section>
          </div>

          {payload.execution_message ? (
            <div className="alerts-inline-note social-signal-note">{payload.execution_message}</div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value, tone = "neutral" }) {
  return (
    <article className={`social-signal-metric social-signal-metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function formatSignedNumber(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function formatAction(value) {
  const mapping = {
    buy: "买入",
    bullish_watch: "偏多观察",
    hold: "持有",
    reduce_or_sell: "减仓/卖出",
    sell: "卖出",
    avoid: "回避",
  };
  return mapping[String(value || "").toLowerCase()] || "持有";
}

function scoreTone(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "neutral";
  }
  return value > 0 ? "profit" : "loss";
}

function actionTone(value) {
  const action = String(value || "").toLowerCase();
  if (action === "buy" || action === "bullish_watch") {
    return "profit";
  }
  if (action === "sell" || action === "reduce_or_sell" || action === "avoid") {
    return "loss";
  }
  return "neutral";
}

function confidenceTone(value) {
  if (value === "high") {
    return "profit";
  }
  if (value === "medium") {
    return "warning";
  }
  return "neutral";
}

function formatDate(value) {
  if (!value) {
    return "时间未知";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未知";
  }

  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
