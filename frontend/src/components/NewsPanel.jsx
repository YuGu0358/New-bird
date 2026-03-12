import React, { useDeferredValue, useEffect, useState } from "react";

export default function NewsPanel({ symbol, apiBaseUrl }) {
  const deferredSymbol = useDeferredValue(symbol);
  const [article, setArticle] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!deferredSymbol) {
      return undefined;
    }

    let isActive = true;

    const loadNews = async () => {
      setIsLoading(true);

      try {
        const response = await fetch(`${apiBaseUrl}/api/news/${deferredSymbol}`);
        if (!response.ok) {
          let detail = `新闻请求失败（状态码 ${response.status}）`;
          try {
            const payload = await response.json();
            if (payload?.detail) {
              detail = payload.detail;
            }
          } catch {
            // Ignore JSON parse errors and use the default message.
          }
          throw new Error(detail);
        }

        const payload = await response.json();
        if (isActive) {
          setArticle(payload);
          setError("");
        }
      } catch (loadError) {
        if (isActive) {
          setError(loadError.message);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    loadNews();
    return () => {
      isActive = false;
    };
  }, [apiBaseUrl, deferredSymbol]);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">资讯</p>
          <h2>AI 新闻摘要</h2>
        </div>
        <span className="panel-pill">{deferredSymbol || "请选择股票"}</span>
      </div>

      {isLoading ? <div className="news-state">正在加载最新新闻...</div> : null}
      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!isLoading && !error && article ? (
        <div className="news-copy">
          <div className="news-meta">
            <span>{article.source}</span>
            <span>{formatDate(article.timestamp)}</span>
          </div>
          <p>{article.summary}</p>
        </div>
      ) : null}

      {!isLoading && !error && !article ? (
        <div className="news-state">
          点击上方股票按钮，加载对应股票的最新摘要。
        </div>
      ) : null}
    </section>
  );
}

function formatDate(value) {
  if (!value) {
    return "刷新时间未知";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刷新时间未知";
  }

  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
