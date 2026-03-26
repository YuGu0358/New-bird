import React, { useEffect, useState } from "react";

const TOPIC_OPTIONS = [
  { value: "news", label: "新闻" },
  { value: "general", label: "全网" },
];

export default function TavilySearchPanel({ symbol, apiBaseUrl, embedded = false }) {
  const [query, setQuery] = useState(symbol || "");
  const [topic, setTopic] = useState("news");
  const [payload, setPayload] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setQuery(symbol || "");
    setPayload(null);
    setError("");
  }, [symbol]);

  const submitSearch = async (event) => {
    event.preventDefault();
    const normalizedQuery = String(query || "").trim();
    if (!normalizedQuery) {
      setError("请输入搜索关键词。");
      return;
    }

    setIsLoading(true);
    setError("");

    try {
      const params = new URLSearchParams({
        query: normalizedQuery,
        topic,
        max_results: "6",
      });
      const response = await fetch(`${apiBaseUrl}/api/tavily/search?${params.toString()}`);

      if (!response.ok) {
        let detail = `Tavily 搜索失败（状态码 ${response.status}）`;
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

      const nextPayload = await response.json();
      setPayload(nextPayload);
    } catch (loadError) {
      setPayload(null);
      setError(loadError.message);
    } finally {
      setIsLoading(false);
    }
  };

  const applySelectedSymbol = () => {
    if (!symbol) {
      return;
    }
    setQuery(symbol);
  };

  return (
    <section className={embedded ? "embedded-panel" : "panel"}>
      <div className={embedded ? "embedded-panel-header" : "panel-header"}>
        <div>
          <p className="panel-kicker">{embedded ? "搜索" : "搜索"}</p>
          <h2>{embedded ? "Tavily 独立搜索" : "Tavily 独立搜索面板"}</h2>
        </div>
        <span className="panel-pill">{symbol || "可自定义关键词"}</span>
      </div>

      <form className="search-toolbar" onSubmit={submitSearch}>
        <input
          type="text"
          className="symbol-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={symbol ? `例如 ${symbol} earnings` : "输入关键词，例如 AI 芯片 / NVDA earnings"}
        />

        <div className="segmented-control">
          {TOPIC_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`segment-button ${topic === option.value ? "is-active" : ""}`}
              onClick={() => setTopic(option.value)}
              disabled={isLoading}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="search-toolbar-actions">
          <button
            type="button"
            className="action-button action-button--neutral"
            onClick={applySelectedSymbol}
            disabled={!symbol || isLoading}
          >
            用当前股票
          </button>
          <button type="submit" className="action-button" disabled={isLoading}>
            {isLoading ? "搜索中..." : "开始搜索"}
          </button>
        </div>
      </form>

      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!error && !payload && !isLoading ? (
        <div className="news-state">
          输入任意关键词后即可直接调用 Tavily 搜索。你可以搜当前股票、行业主题、财报、政策或宏观事件。
        </div>
      ) : null}

      {payload ? (
        <div className="search-results">
          <div className="search-summary-card">
            <div className="search-summary-meta">
              <span>关键词 {payload.query}</span>
              <span>{payload.topic === "news" ? "新闻模式" : "全网模式"}</span>
              <span>{formatDate(payload.generated_at)}</span>
            </div>
            <p>{payload.answer}</p>
          </div>

          <div className="search-source-list">
            {payload.results?.length ? (
              payload.results.map((item) => (
                <article className="search-source-card" key={`${item.url}-${item.title}`}>
                  <div className="search-source-header">
                    <div>
                      <h3>{item.title}</h3>
                      <div className="search-source-meta">
                        {[item.source, item.domain, item.published_date]
                          .filter(Boolean)
                          .map((value) => (
                            <span key={`${item.url}-${value}`}>{value}</span>
                          ))}
                      </div>
                    </div>
                    <a href={item.url} target="_blank" rel="noreferrer">
                      打开来源
                    </a>
                  </div>
                  <p>{item.content || "当前来源未返回摘要片段。点击链接可查看原文。"}</p>
                </article>
              ))
            ) : (
              <div className="empty-state">这次搜索没有返回可展示的来源链接。</div>
            )}
          </div>
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
