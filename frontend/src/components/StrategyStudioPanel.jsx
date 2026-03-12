import React, { useEffect, useState } from "react";

export default function StrategyStudioPanel({ apiBaseUrl, botStatus }) {
  const [library, setLibrary] = useState({ items: [], max_slots: 5, active_strategy_id: null });
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState(null);
  const [draftName, setDraftName] = useState("");
  const [actionBusy, setActionBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    loadLibrary();
  }, [apiBaseUrl]);

  const loadLibrary = async () => {
    setActionBusy("load");
    try {
      const response = await fetch(`${apiBaseUrl}/api/strategies`);
      if (!response.ok) {
        throw new Error(`策略列表加载失败（状态码 ${response.status}）`);
      }
      const payload = await response.json();
      setLibrary(payload);
      setError("");
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setActionBusy("");
    }
  };

  const analyzeStrategy = async () => {
    if (!description.trim()) {
      setError("请先输入你的交易策略描述。");
      return;
    }

    setActionBusy("analyze");
    setMessage("");
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/strategies/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ description }),
      });

      if (!response.ok) {
        let detail = `策略规范化失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Keep the default message.
        }
        throw new Error(detail);
      }

      const payload = await response.json();
      setDraft(payload);
      setDraftName(payload.suggested_name || "");
      setMessage(
        payload.used_openai
          ? "GPT 已完成策略规范化，请确认后再保存。"
          : "已生成本地回退版本，请确认后再保存。"
      );
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const saveStrategy = async () => {
    if (!draft) {
      setError("请先生成策略预览。");
      return;
    }

    setActionBusy("save");
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/strategies`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: draftName || draft.suggested_name,
          original_description: draft.original_description,
          normalized_strategy: draft.normalized_strategy,
          improvement_points: draft.improvement_points,
          risk_warnings: draft.risk_warnings,
          execution_notes: draft.execution_notes,
          parameters: draft.parameters,
          activate: true,
        }),
      });

      if (!response.ok) {
        let detail = `策略保存失败（状态码 ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Keep default error.
        }
        throw new Error(detail);
      }

      const payload = await response.json();
      setLibrary(payload);
      setDraft(null);
      setDraftName("");
      setDescription("");
      setMessage("策略已保存并设为当前策略。新的策略会在机器人下次启动时生效。");
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const activateStrategy = async (strategyId) => {
    setActionBusy(`activate-${strategyId}`);
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/strategies/${strategyId}/activate`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(`策略激活失败（状态码 ${response.status}）`);
      }
      const payload = await response.json();
      setLibrary(payload);
      setMessage("已切换当前策略。新的策略会在机器人下次启动时生效。");
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const deleteStrategy = async (strategyId) => {
    setActionBusy(`delete-${strategyId}`);
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/strategies/${strategyId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(`策略删除失败（状态码 ${response.status}）`);
      }
      const payload = await response.json();
      setLibrary(payload);
      setMessage("策略已删除。");
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setActionBusy("");
    }
  };

  const activeStrategy = library.items.find((item) => item.is_active);
  const remainingSlots = Math.max(0, (library.max_slots ?? 5) - library.items.length);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">策略</p>
          <h2>GPT 策略工作台</h2>
        </div>
        <span className="panel-pill">
          {activeStrategy?.name || botStatus?.active_strategy_name || "系统默认 Strategy B"}
        </span>
      </div>

      <div className="strategy-summary-grid">
        <div>
          <span className="stat-label">已保存</span>
          <strong className="stat-value">{library.items.length}</strong>
        </div>
        <div>
          <span className="stat-label">剩余槽位</span>
          <strong className="stat-value">{remainingSlots}</strong>
        </div>
        <div>
          <span className="stat-label">生效时机</span>
          <strong className="stat-value">下次启动机器人</strong>
        </div>
      </div>

      <div className="strategy-notice-card">
        <strong>策略切换规则</strong>
        <p>
          GPT 只负责整理和改进你的想法。只有在你确认保存后，策略才会进入库中；只有设为当前策略后，
          机器人下次启动才会按这套参数执行。
        </p>
      </div>

      <div className="strategy-builder">
        <label className="strategy-field">
          <span>描述你的交易策略</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="例如：我想交易 NVDA、MSFT 和 AAPL，当日跌超 3% 分批买入，最多加仓 2 次，单笔初始仓位 1500 美元，止盈 120 美元，止损 10%，最长持有 20 天。"
            rows={6}
          />
        </label>

        <div className="strategy-actions">
          <button
            type="button"
            className="action-button"
            onClick={analyzeStrategy}
            disabled={actionBusy !== ""}
          >
            {actionBusy === "analyze" ? "规范化中..." : "GPT 规范与改进"}
          </button>
        </div>
      </div>

      {message ? <div className="banner success-banner">{message}</div> : null}
      {error ? <div className="banner error-banner">{error}</div> : null}

      {draft ? (
        <div className="strategy-draft">
          <div className="strategy-draft-header">
            <h3>待确认策略</h3>
            <span className={`status-chip ${draft.used_openai ? "status-chip--running" : "status-chip--stopped"}`}>
              {draft.used_openai ? "GPT 输出" : "本地回退"}
            </span>
          </div>

          <label className="strategy-field">
            <span>策略名称</span>
            <input
              type="text"
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              placeholder="输入你要保存的策略名称"
            />
          </label>

          <p className="strategy-copy">{draft.normalized_strategy}</p>

          <div className="strategy-parameter-grid">
            <ParameterCard label="股票池" value={draft.parameters.universe_symbols.join(", ")} />
            <ParameterCard
              label="偏好板块"
              value={formatList(draft.parameters.preferred_sectors)}
            />
            <ParameterCard
              label="排除股票"
              value={formatList(draft.parameters.excluded_symbols)}
            />
            <ParameterCard
              label="入场回撤"
              value={`${draft.parameters.entry_drop_percent.toFixed(1)}%`}
            />
            <ParameterCard
              label="加仓回撤"
              value={`${draft.parameters.add_on_drop_percent.toFixed(1)}%`}
            />
            <ParameterCard
              label="初始仓位"
              value={formatUsd(draft.parameters.initial_buy_notional)}
            />
            <ParameterCard
              label="加仓金额"
              value={formatUsd(draft.parameters.add_on_buy_notional)}
            />
            <ParameterCard
              label="每日新开仓"
              value={`${draft.parameters.max_daily_entries} 只`}
            />
            <ParameterCard label="最多加仓" value={`${draft.parameters.max_add_ons} 次`} />
            <ParameterCard
              label="止盈"
              value={formatUsd(draft.parameters.take_profit_target)}
            />
            <ParameterCard
              label="止损"
              value={`${draft.parameters.stop_loss_percent.toFixed(1)}%`}
            />
            <ParameterCard label="最长持有" value={`${draft.parameters.max_hold_days} 天`} />
          </div>

          <StrategyBulletGroup title="优化建议" items={draft.improvement_points} />
          <StrategyBulletGroup title="风险提醒" items={draft.risk_warnings} />
          <StrategyBulletGroup title="执行说明" items={draft.execution_notes} />

          <div className="strategy-actions">
            <button
              type="button"
              className="action-button"
              onClick={saveStrategy}
              disabled={actionBusy !== "" || library.items.length >= (library.max_slots ?? 5)}
            >
              {actionBusy === "save" ? "保存中..." : "确认保存并设为当前策略"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="strategy-library">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">库</p>
            <h2>已保存策略</h2>
          </div>
          <span className="panel-pill">
            {actionBusy === "load" ? "加载中..." : `${library.items.length}/${library.max_slots}`}
          </span>
        </div>

        {library.items.length ? (
          <div className="strategy-library-list">
            {library.items.map((item) => (
              <article className="strategy-card" key={item.id}>
                <div className="strategy-card-header">
                  <div>
                    <h3>{item.name}</h3>
                    <p>{item.is_active ? "当前生效策略" : "已保存，未激活"}</p>
                  </div>
                  {item.is_active ? (
                    <span className="status-chip status-chip--running">ACTIVE</span>
                  ) : null}
                </div>

                <p className="strategy-copy strategy-copy--compact">{item.normalized_strategy}</p>

                <div className="strategy-mini-grid">
                  <span>股票池 {item.parameters.universe_symbols.length} 只</span>
                  <span>板块 {item.parameters.preferred_sectors?.length || 0} 个</span>
                  <span>排除 {item.parameters.excluded_symbols?.length || 0} 只</span>
                  <span>每日新开仓 {item.parameters.max_daily_entries} 只</span>
                  <span>入场 {item.parameters.entry_drop_percent.toFixed(1)}%</span>
                  <span>止损 {item.parameters.stop_loss_percent.toFixed(1)}%</span>
                  <span>最长持有 {item.parameters.max_hold_days} 天</span>
                </div>

                <div className="strategy-actions">
                  <button
                    type="button"
                    className="action-button action-button--neutral"
                    onClick={() => activateStrategy(item.id)}
                    disabled={item.is_active || actionBusy !== ""}
                  >
                    {actionBusy === `activate-${item.id}` ? "切换中..." : "设为当前策略"}
                  </button>
                  <button
                    type="button"
                    className="action-button action-button--danger"
                    onClick={() => deleteStrategy(item.id)}
                    disabled={actionBusy !== ""}
                  >
                    {actionBusy === `delete-${item.id}` ? "删除中..." : "删除"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            还没有保存策略。先在上方输入你的想法，让 GPT 帮你整理成可确认的执行版本。
          </div>
        )}
      </div>
    </section>
  );
}

function StrategyBulletGroup({ title, items }) {
  if (!items?.length) {
    return null;
  }

  return (
    <section className="strategy-bullet-group">
      <h3>{title}</h3>
      <ul className="insight-list">
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function ParameterCard({ label, value }) {
  return (
    <article className="strategy-parameter-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
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

function formatList(items) {
  if (!items?.length) {
    return "无";
  }
  return items.map((item) => SECTOR_LABELS[item] || item).join(", ");
}

const SECTOR_LABELS = {
  technology: "科技",
  semiconductors: "半导体",
  software: "软件",
  cloud: "云计算",
  cybersecurity: "网络安全",
  fintech: "金融科技",
  mega_cap: "大盘科技",
  etf: "ETF",
};
