import React, { useDeferredValue, useEffect, useState } from "react";

export default function UniverseExplorer({
  apiBaseUrl,
  selectedSymbols,
  universeAssetCount,
  onAddWatchlistSymbol,
  actionBusy,
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let isActive = true;

    const loadUniverse = async () => {
      setIsLoading(true);
      setError("");

      try {
        const params = new URLSearchParams({
          query: deferredQuery,
          limit: deferredQuery ? "12" : "8",
        });
        const response = await fetch(`${apiBaseUrl}/api/universe?${params.toString()}`);
        if (!response.ok) {
          let detail = `股票池请求失败（状态码 ${response.status}）`;
          try {
            const payload = await response.json();
            if (payload?.detail) {
              detail = payload.detail;
            }
          } catch {
            // Keep the default error message.
          }
          throw new Error(detail);
        }

        const payload = await response.json();
        if (isActive) {
          setResults(payload ?? []);
        }
      } catch (loadError) {
        if (isActive) {
          setError(loadError.message);
          setResults([]);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    loadUniverse();
    return () => {
      isActive = false;
    };
  }, [apiBaseUrl, deferredQuery]);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Universe</p>
          <h2>Alpaca 股票池</h2>
        </div>
        <span className="panel-pill">可搜索 {universeAssetCount || 0} 只</span>
      </div>

      <div className="universe-toolbar">
        <input
          type="text"
          className="symbol-search"
          value={query}
          onChange={(event) => setQuery(event.target.value.toUpperCase())}
          placeholder="搜索代码或公司名，例如 NVDA / MICROSOFT"
        />
      </div>

      {isLoading ? <div className="news-state">正在加载 Alpaca 股票池...</div> : null}
      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!isLoading && !error ? (
        <div className="universe-results">
          {results.map((item) => {
            const isTracked = selectedSymbols.includes(item.symbol);
            return (
              <article key={item.symbol} className="universe-row">
                <div>
                  <strong>{item.symbol}</strong>
                  <p>{item.name || "未提供公司名"}</p>
                </div>
                <button
                  type="button"
                  className="action-button"
                  onClick={() => onAddWatchlistSymbol(item.symbol)}
                  disabled={isTracked || actionBusy !== ""}
                >
                  {isTracked ? "已在自选" : "加入"}
                </button>
              </article>
            );
          })}

          {!results.length ? (
            <div className="empty-state">当前搜索没有匹配到 Alpaca 可交易股票。</div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
