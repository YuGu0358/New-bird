import React, { useDeferredValue, useEffect, useState } from "react";

export default function CompanyProfilePanel({ symbol, apiBaseUrl, embedded = false }) {
  const deferredSymbol = useDeferredValue(symbol);
  const [profile, setProfile] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!deferredSymbol) {
      setProfile(null);
      setError("");
      return undefined;
    }

    let isActive = true;

    const loadProfile = async () => {
      setIsLoading(true);
      setError("");

      try {
        const response = await fetch(`${apiBaseUrl}/api/company/${deferredSymbol}`);
        if (!response.ok) {
          let detail = `公司资料请求失败（状态码 ${response.status}）`;
          try {
            const payload = await response.json();
            if (payload?.detail) {
              detail = payload.detail;
            }
          } catch {
            // Keep the default message when the backend response is not JSON.
          }
          throw new Error(detail);
        }

        const payload = await response.json();
        if (isActive) {
          setProfile(payload);
        }
      } catch (loadError) {
        if (isActive) {
          setProfile(null);
          setError(loadError.message);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    loadProfile();
    return () => {
      isActive = false;
    };
  }, [apiBaseUrl, deferredSymbol]);

  return (
    <section className={embedded ? "embedded-panel" : "panel"}>
      <div className={embedded ? "embedded-panel-header" : "panel-header"}>
        <div>
          <p className="panel-kicker">{embedded ? "资料" : "资料"}</p>
          <h2>{embedded ? "公司资料" : "公司资料与主营业务"}</h2>
        </div>
        <span className="panel-pill">{deferredSymbol || "请选择股票"}</span>
      </div>

      {isLoading ? <div className="news-state">正在加载公司资料...</div> : null}
      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!deferredSymbol && !isLoading && !error ? (
        <div className="news-state">先在右侧或列表里选择一只股票，再查看该公司的资料。</div>
      ) : null}

      {profile ? (
        <div className="company-profile-card">
          <div className="company-profile-header">
            <div>
              <h3>{profile.company_name || deferredSymbol}</h3>
              <p>{buildIdentityLine(profile)}</p>
            </div>
            {profile.website ? (
              <a
                className="action-button action-button--neutral company-profile-link"
                href={profile.website}
                target="_blank"
                rel="noreferrer"
              >
                访问官网
              </a>
            ) : null}
          </div>

          <div className="company-profile-grid">
            <ProfileFact label="股票代码" value={profile.symbol} />
            <ProfileFact label="交易所" value={profile.exchange} />
            <ProfileFact label="资产类型" value={formatQuoteType(profile.quote_type)} />
            <ProfileFact label="板块" value={profile.sector || profile.category} />
            <ProfileFact label="行业" value={profile.industry || profile.fund_family} />
            <ProfileFact label="市值" value={formatMarketCap(profile.market_cap)} />
            <ProfileFact
              label="员工数"
              value={formatEmployeeCount(profile.full_time_employees)}
            />
            <ProfileFact label="地区" value={profile.location} />
          </div>

          <section className="company-profile-section">
            <h3>主营业务 / 公司简介</h3>
            <p>{profile.business_summary}</p>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function ProfileFact({ label, value }) {
  return (
    <article className="company-profile-fact">
      <span>{label}</span>
      <strong>{value || "暂无"}</strong>
    </article>
  );
}

function buildIdentityLine(profile) {
  return [
    formatQuoteType(profile.quote_type),
    profile.exchange,
    profile.currency,
    formatMetaDate(profile.generated_at),
  ]
    .filter(Boolean)
    .join(" · ");
}

function formatQuoteType(value) {
  const normalized = String(value || "").trim().toUpperCase();
  if (!normalized) {
    return "";
  }

  const labelMap = {
    EQUITY: "股票",
    ETF: "ETF",
    MUTUALFUND: "基金",
    CRYPTOCURRENCY: "加密货币",
    INDEX: "指数",
  };
  return labelMap[normalized] || normalized;
}

function formatMarketCap(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "暂无";
  }

  if (value >= 1_000_000_000_000) {
    return `${(value / 1_000_000_000_000).toFixed(2)}T USD`;
  }
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(2)}B USD`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2)}M USD`;
  }
  return `${value.toFixed(0)} USD`;
}

function formatEmployeeCount(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "暂无";
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatMetaDate(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
