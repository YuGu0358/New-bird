import React, { useEffect, useState } from "react";

const CATEGORY_LABELS = {
  broker: "券商",
  market_data: "行情",
  research: "研究",
  ai: "AI",
  social: "社媒",
  notifications: "通知",
  safety: "风控",
};

export default function SettingsPanel({
  settingsStatus,
  onSave,
  onBack,
  actionBusy,
}) {
  const [adminToken, setAdminToken] = useState("");
  const [formValues, setFormValues] = useState({});

  useEffect(() => {
    const nextValues = {};
    for (const item of settingsStatus?.items ?? []) {
      nextValues[item.key] = item.sensitive ? "" : item.value ?? "";
    }
    setFormValues(nextValues);
  }, [settingsStatus]);

  const groupedItems = (settingsStatus?.items ?? []).reduce((groups, item) => {
    const category = item.category || "other";
    if (!groups[category]) {
      groups[category] = [];
    }
    groups[category].push(item);
    return groups;
  }, {});

  const updateField = (key, value) => {
    setFormValues((current) => ({
      ...current,
      [key]: value,
    }));
  };

  const submitForm = async (event) => {
    event.preventDefault();
    const settings = {};

    for (const item of settingsStatus?.items ?? []) {
      const nextValue = formValues[item.key];
      if (item.sensitive) {
        if (String(nextValue || "").trim()) {
          settings[item.key] = nextValue;
        }
        continue;
      }

      if (nextValue !== undefined && nextValue !== null) {
        settings[item.key] = String(nextValue);
      }
    }

    await onSave({
      admin_token: adminToken,
      settings,
    });
    setAdminToken("");
  };

  return (
    <section className="panel settings-panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">部署设置</p>
          <h2>API Key 与运行参数</h2>
        </div>
        <span
          className={`status-chip ${
            settingsStatus?.is_ready ? "status-chip--running" : "status-chip--stopped"
          }`}
        >
          {settingsStatus?.is_ready ? "已就绪" : "待配置"}
        </span>
      </div>

      <p className="settings-intro">
        把部署实例需要的 API key 填在这里即可，无需修改服务器上的 `.env`。
      </p>

      <div className="settings-summary-grid">
        <div>
          <span className="stat-label">缺少的必填项</span>
          <strong className="stat-value">
            {settingsStatus?.missing_required_keys?.length ?? 0}
          </strong>
        </div>
        <div>
          <span className="stat-label">保存模式</span>
          <strong className="stat-value">
            {settingsStatus?.admin_token_required ? "管理员口令保护" : "开放保存"}
          </strong>
        </div>
      </div>

      <form className="settings-form" onSubmit={submitForm}>
        {settingsStatus?.admin_token_required ? (
          <label className="settings-field settings-field--wide">
            <span>管理员口令</span>
            <input
              type="password"
              value={adminToken}
              onChange={(event) => setAdminToken(event.target.value)}
              placeholder="部署时设置的 SETTINGS_ADMIN_TOKEN"
            />
          </label>
        ) : null}

        {Object.entries(groupedItems).map(([category, items]) => (
          <section className="settings-group" key={category}>
            <div className="settings-group-header">
              <h3>{CATEGORY_LABELS[category] ?? category}</h3>
              <span>{items.length} 项</span>
            </div>

            <div className="settings-grid">
              {items.map((item) => (
                <label
                  className={`settings-field ${item.required ? "settings-field--required" : ""}`}
                  key={item.key}
                >
                  <span>
                    {item.label}
                    {item.required ? " *" : ""}
                  </span>
                  <input
                    type={item.sensitive ? "password" : "text"}
                    value={formValues[item.key] ?? ""}
                    onChange={(event) => updateField(item.key, event.target.value)}
                    placeholder={
                      item.sensitive
                        ? item.configured
                          ? "已保存，如需替换请重新输入"
                          : `输入 ${item.label}`
                        : item.value || item.label
                    }
                  />
                  <small>
                    {item.description} 当前状态：
                    {item.configured ? `已配置（${formatSource(item.source)}）` : "未配置"}
                  </small>
                </label>
              ))}
            </div>
          </section>
        ))}

        <div className="settings-actions">
          <button
            type="submit"
            className="action-button"
            disabled={actionBusy === "settings"}
          >
            {actionBusy === "settings" ? "保存中..." : "保存设置"}
          </button>
          <button
            type="button"
            className="action-button action-button--neutral"
            onClick={onBack}
            disabled={!settingsStatus?.is_ready}
          >
            返回仪表盘
          </button>
        </div>
      </form>
    </section>
  );
}

function formatSource(source) {
  switch (source) {
    case "stored":
      return "页面保存";
    case "env":
      return "环境变量";
    case "default":
      return "默认值";
    default:
      return "未设置";
  }
}
