import React, { useEffect, useState } from "react";

export default function ResearchPanel({ symbol, apiBaseUrl }) {
  const [report, setReport] = useState(null);
  const [researchModel, setResearchModel] = useState("mini");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setReport(null);
    setError("");
  }, [symbol]);

  const loadResearch = async () => {
    if (!symbol) {
      return;
    }

    setIsLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${apiBaseUrl}/api/research/${symbol}?research_model=${researchModel}`
      );

      if (!response.ok) {
        let detail = `研究请求失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Use default text if the backend does not return JSON.
        }
        throw new Error(detail);
      }

      const payload = await response.json();
      setReport(payload);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">研究</p>
          <h2>Market Researcher 深度分析</h2>
        </div>
        <span className="panel-pill">{symbol || "请选择股票"}</span>
      </div>

      <div className="research-toolbar">
        <div className="segmented-control">
          <button
            type="button"
            className={`segment-button ${researchModel === "mini" ? "is-active" : ""}`}
            onClick={() => setResearchModel("mini")}
            disabled={isLoading}
          >
            Mini
          </button>
          <button
            type="button"
            className={`segment-button ${researchModel === "pro" ? "is-active" : ""}`}
            onClick={() => setResearchModel("pro")}
            disabled={isLoading}
          >
            Pro
          </button>
        </div>

        <button
          type="button"
          className="action-button"
          onClick={loadResearch}
          disabled={!symbol || isLoading}
        >
          {isLoading ? "研究中..." : "生成深度研究"}
        </button>
      </div>

      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!isLoading && !error && !report ? (
        <div className="news-state">
          点击按钮后，将调用 Tavily Research 生成结构化研究报告。
        </div>
      ) : null}

      {report ? (
        <div className="research-content">
          <div className="research-meta">
            <span>{report.company_name}</span>
            <span>{formatDate(report.generated_at)}</span>
          </div>

          <section className="research-block">
            <h3>摘要</h3>
            <p>{report.summary}</p>
          </section>

          <section className="research-block">
            <h3>当前表现</h3>
            <p>{report.current_performance}</p>
          </section>

          <section className="research-metric-grid">
            <div>
              <dt>建议</dt>
              <dd>{report.recommendation}</dd>
            </div>
            <div>
              <dt>风险</dt>
              <dd>{report.risk_assessment}</dd>
            </div>
            <div>
              <dt>价格展望</dt>
              <dd>{report.price_outlook}</dd>
            </div>
            <div>
              <dt>市值 / PE</dt>
              <dd>
                {formatCurrency(report.market_cap)} / {formatNumber(report.pe_ratio)}
              </dd>
            </div>
          </section>

          <section className="research-block">
            <h3>关键洞察</h3>
            {report.key_insights?.length ? (
              <ul className="insight-list">
                {report.key_insights.map((item, index) => (
                  <li key={`${report.symbol}-insight-${index}`}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>暂无关键洞察。</p>
            )}
          </section>

          <section className="research-block">
            <h3>来源</h3>
            {report.sources?.length ? (
              <ul className="source-list">
                {report.sources.slice(0, 6).map((source) => (
                  <li key={`${source.url}-${source.title}`}>
                    <a href={source.url} target="_blank" rel="noreferrer">
                      {source.title || source.url}
                    </a>
                    <span>
                      {[source.source, source.domain, source.published_date]
                        .filter(Boolean)
                        .join(" | ")}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无来源。</p>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
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

function formatCurrency(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }

  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(2)}B USD`;
  }

  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2)}M USD`;
  }

  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatNumber(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }

  return value.toFixed(2);
}
