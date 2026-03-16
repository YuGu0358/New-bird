import React, { useDeferredValue, useEffect, useState } from "react";
import PanelCollapseButton from "./PanelCollapseButton";

const CONDITION_OPTIONS = [
  { value: "price_above", label: "价格涨到", unit: "USD" },
  { value: "price_below", label: "价格跌到", unit: "USD" },
  { value: "day_change_up", label: "相对昨收涨幅达到", unit: "%" },
  { value: "day_change_down", label: "相对昨收跌幅达到", unit: "%" },
];

const ACTION_OPTIONS = [
  { value: "email", label: "只发邮件提醒" },
  { value: "buy_notional", label: "自动买入固定金额" },
  { value: "close_position", label: "自动平掉当前持仓" },
];

export default function PriceAlertsPanel({ symbol, apiBaseUrl, embedded = false }) {
  const deferredSymbol = useDeferredValue(symbol);
  const [collapsed, setCollapsed] = useState(false);
  const [rules, setRules] = useState([]);
  const [conditionType, setConditionType] = useState("price_above");
  const [targetValue, setTargetValue] = useState("");
  const [actionType, setActionType] = useState("email");
  const [orderNotionalUsd, setOrderNotionalUsd] = useState("");
  const [note, setNote] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");

  const loadRules = async (activeSymbol) => {
    if (!activeSymbol) {
      setRules([]);
      return;
    }

    setIsLoading(true);
    setError("");

    try {
      const params = new URLSearchParams({ symbol: activeSymbol });
      const response = await fetch(`${apiBaseUrl}/api/alerts?${params.toString()}`);
      if (!response.ok) {
        let detail = `提醒规则请求失败（状态码 ${response.status}）`;
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
      setRules(payload ?? []);
    } catch (loadError) {
      setError(loadError.message);
      setRules([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setTargetValue("");
    setOrderNotionalUsd("");
    setNote("");
    setError("");
    if (!deferredSymbol) {
      setRules([]);
      return;
    }
    loadRules(deferredSymbol);
  }, [apiBaseUrl, deferredSymbol]);

  const submitRule = async (event) => {
    event.preventDefault();
    if (!deferredSymbol) {
      return;
    }

    setIsSaving(true);
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/alerts`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          symbol: deferredSymbol,
          condition_type: conditionType,
          target_value: Number(targetValue),
          action_type: actionType,
          order_notional_usd:
            actionType === "buy_notional" ? Number(orderNotionalUsd) : null,
          note,
        }),
      });

      if (!response.ok) {
        let detail = `创建提醒规则失败（状态码 ${response.status}）`;
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

      setTargetValue("");
      setOrderNotionalUsd("");
      setNote("");
      await loadRules(deferredSymbol);
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setIsSaving(false);
    }
  };

  const toggleRule = async (ruleId, enabled) => {
    setIsSaving(true);
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/alerts/${ruleId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ enabled }),
      });

      if (!response.ok) {
        let detail = `更新提醒规则失败（状态码 ${response.status}）`;
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

      await loadRules(deferredSymbol);
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setIsSaving(false);
    }
  };

  const deleteRule = async (ruleId) => {
    setIsSaving(true);
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/alerts/${ruleId}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        let detail = `删除提醒规则失败（状态码 ${response.status}）`;
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

      await loadRules(deferredSymbol);
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setIsSaving(false);
    }
  };

  const selectedCondition = CONDITION_OPTIONS.find((item) => item.value === conditionType);

  return (
    <section className={embedded ? "embedded-panel" : "panel"}>
      <div className={embedded ? "embedded-panel-header" : "panel-header"}>
        <div>
          <p className="panel-kicker">{embedded ? "提醒" : "提醒"}</p>
          <h2>{embedded ? "条件提醒与动作" : "价格条件与自动动作"}</h2>
        </div>
        <div className="panel-header-actions">
          <span className="panel-pill">{deferredSymbol || "请选择股票"}</span>
          {!embedded ? (
            <PanelCollapseButton
              collapsed={collapsed}
              onToggle={() => setCollapsed((current) => !current)}
            />
          ) : null}
        </div>
      </div>

      {(!embedded ? !collapsed : true) && !deferredSymbol ? (
        <div className="news-state">先选择一只股票，再为它设置价格提醒或自动动作。</div>
      ) : null}

      {(!embedded ? !collapsed : true) && deferredSymbol ? (
        <>
          <form className="alerts-form" onSubmit={submitRule}>
            <div className="alerts-grid">
              <label className="settings-field">
                <span>触发条件</span>
                <select
                  value={conditionType}
                  onChange={(event) => setConditionType(event.target.value)}
                  disabled={isSaving}
                >
                  {CONDITION_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="settings-field">
                <span>目标值</span>
                <input
                  type="number"
                  step="0.01"
                  value={targetValue}
                  onChange={(event) => setTargetValue(event.target.value)}
                  placeholder={selectedCondition?.unit === "%" ? "例如 5" : "例如 200"}
                  disabled={isSaving}
                />
                <small>
                  {selectedCondition?.unit === "%"
                    ? "涨跌幅按相对昨收计算。"
                    : "价格单位为美元。"}
                </small>
              </label>

              <label className="settings-field">
                <span>触发动作</span>
                <select
                  value={actionType}
                  onChange={(event) => setActionType(event.target.value)}
                  disabled={isSaving}
                >
                  {ACTION_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              {actionType === "buy_notional" ? (
                <label className="settings-field">
                  <span>自动买入金额</span>
                  <input
                    type="number"
                    step="0.01"
                    value={orderNotionalUsd}
                    onChange={(event) => setOrderNotionalUsd(event.target.value)}
                    placeholder="例如 1000"
                    disabled={isSaving}
                  />
                  <small>当前版本只支持固定美元金额买入。</small>
                </label>
              ) : null}

              <label className="settings-field settings-field--wide">
                <span>备注</span>
                <input
                  type="text"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="例如：突破后提醒我，或触发后执行 paper 账户买入"
                  disabled={isSaving}
                />
                <small>
                  自动交易默认只允许 Alpaca paper 账户，除非你在设置里显式放开。
                </small>
              </label>
            </div>

            <div className="settings-actions">
              <button
                type="submit"
                className="action-button"
                disabled={!targetValue || isSaving}
              >
                {isSaving ? "保存中..." : "新增规则"}
              </button>
            </div>
          </form>

          {isLoading ? <div className="news-state">正在加载当前股票的提醒规则...</div> : null}
          {error ? <div className="news-state news-state--error">{error}</div> : null}

          {!isLoading && !error ? (
            <div className="alerts-rule-list">
              {rules.length ? (
                rules.map((rule) => (
                  <article className="alerts-rule-card" key={rule.id}>
                    <div className="alerts-rule-header">
                      <div>
                        <h3>{rule.symbol}</h3>
                        <p>{rule.condition_summary}</p>
                      </div>
                      <span className={`order-status ${rule.enabled ? "order-status--filled" : ""}`}>
                        {rule.enabled ? "监控中" : "已停用"}
                      </span>
                    </div>

                    <div className="alerts-rule-meta">
                      <span>{rule.action_summary}</span>
                      {rule.note ? <span>备注：{rule.note}</span> : null}
                      {rule.triggered_at ? <span>最近触发：{formatDate(rule.triggered_at)}</span> : null}
                      {typeof rule.trigger_price === "number" ? (
                        <span>触发价格：{formatUsd(rule.trigger_price)}</span>
                      ) : null}
                      {typeof rule.trigger_change_percent === "number" ? (
                        <span>触发涨跌：{formatPercent(rule.trigger_change_percent)}</span>
                      ) : null}
                    </div>

                    {rule.action_result ? (
                      <div className="alerts-inline-note">{rule.action_result}</div>
                    ) : null}
                    {rule.last_error ? (
                      <div className="news-state news-state--error">{rule.last_error}</div>
                    ) : null}

                    <div className="candidate-actions">
                      <button
                        type="button"
                        className="action-button action-button--neutral"
                        onClick={() => toggleRule(rule.id, !rule.enabled)}
                        disabled={isSaving}
                      >
                        {rule.enabled ? "停用" : "重新启用"}
                      </button>
                      <button
                        type="button"
                        className="action-button action-button--danger"
                        onClick={() => deleteRule(rule.id)}
                        disabled={isSaving}
                      >
                        删除规则
                      </button>
                    </div>
                  </article>
                ))
              ) : (
                <div className="empty-state">当前股票还没有设置价格提醒规则。</div>
              )}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function formatDate(value) {
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

function formatUsd(value) {
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
