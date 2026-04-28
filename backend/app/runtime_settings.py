from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from app.database import DATABASE_FILE

load_dotenv()


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    category: str
    required: bool = False
    sensitive: bool = True
    default: str | None = None
    description: str = ""


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition(
        key="DISPLAY_NAME",
        label="Display Name",
        category="profile",
        required=False,
        sensitive=False,
        description="用于首页主标题和桌面窗口标题显示。",
    ),
    SettingDefinition(
        key="ALPACA_API_KEY",
        label="Alpaca API Key",
        category="broker",
        required=True,
        description="用于账户、持仓、订单和股票池读取。",
    ),
    SettingDefinition(
        key="ALPACA_SECRET_KEY",
        label="Alpaca Secret Key",
        category="broker",
        required=True,
        description="与 Alpaca API Key 配套使用。",
    ),
    SettingDefinition(
        key="ALPACA_BASE_URL",
        label="Alpaca Base URL",
        category="broker",
        required=False,
        sensitive=False,
        default="https://paper-api.alpaca.markets",
        description="默认使用 Alpaca paper trading 地址。",
    ),
    SettingDefinition(
        key="POLYGON_API_KEY",
        label="Polygon API Key",
        category="market_data",
        required=True,
        description="用于策略行情流和前收盘价读取。",
    ),
    SettingDefinition(
        key="POLYGON_FEED",
        label="Polygon Feed",
        category="market_data",
        required=False,
        sensitive=False,
        default="delayed",
        description="常用值为 delayed 或 real-time。",
    ),
    SettingDefinition(
        key="POLYGON_USE_WEBSOCKET",
        label="Use Polygon WebSocket",
        category="market_data",
        required=False,
        sensitive=False,
        default="false",
        description="true 时优先使用 Polygon WebSocket。",
    ),
    SettingDefinition(
        key="TAVILY_API_KEY",
        label="Tavily API Key",
        category="research",
        required=True,
        description="用于新闻摘要和研究报告。",
    ),
    SettingDefinition(
        key="FRED_API_KEY",
        label="FRED API Key",
        category="research",
        required=False,
        description="用于宏观指标看板（CPI/PCE/收益率/HY OAS 等）。免费申请：https://fredaccount.stlouisfed.org/apikeys",
    ),
    SettingDefinition(
        key="TRADINGECONOMICS_API_KEY",
        label="TradingEconomics API Key",
        category="research",
        required=False,
        description="可选。用于实时丰富 Economic Calendar 事件；不填时使用内置精选种子事件列表。",
    ),
    SettingDefinition(
        key="PINE_SEEDS_DIR",
        label="Pine Seeds Directory",
        category="research",
        required=False,
        sensitive=False,
        default="",
        description="本地写入 TradingView pine-seeds CSV 的目录。默认：${DATA_DIR}/pine_seeds。",
    ),
    SettingDefinition(
        key="PINE_SEEDS_REPO_URL",
        label="Pine Seeds Repo URL",
        category="research",
        required=False,
        sensitive=False,
        default="",
        description="pine-seeds 公开 GitHub 仓库地址（HTTPS 或 SSH）。仅在需要自动 push 时填写。申请 TradingView 白名单：https://github.com/tradingview-pine-seeds",
    ),
    SettingDefinition(
        key="PINE_SEEDS_WATCHLIST",
        label="Pine Seeds Watchlist",
        category="research",
        required=False,
        sensitive=False,
        default="SPY,QQQ,NVDA,AAPL",
        description="要导出 options / 估值水平的标的列表（逗号分隔）。",
    ),
    SettingDefinition(
        key="BROKER_BACKEND",
        label="Broker Backend",
        category="broker",
        required=False,
        sensitive=False,
        default="alpaca",
        description="路由到哪个券商：alpaca（默认）或 ibkr。切换到 ibkr 需要本地运行的 IB Gateway。",
    ),
    SettingDefinition(
        key="IBKR_HOST",
        label="IBKR Host",
        category="broker",
        required=False,
        sensitive=False,
        default="127.0.0.1",
        description="IB Gateway / TWS 运行的主机，默认本机 127.0.0.1。",
    ),
    SettingDefinition(
        key="IBKR_PORT",
        label="IBKR Port",
        category="broker",
        required=False,
        sensitive=False,
        default="5055",
        description="5055 = paper，4001 = live。在 IB Gateway → Configuration → API 中设置。",
    ),
    SettingDefinition(
        key="IBKR_CLIENT_ID",
        label="IBKR Client ID",
        category="broker",
        required=False,
        sensitive=False,
        default="1",
        description="每个连接需要唯一整数。运行多个机器人时使用不同值（1-32）。",
    ),
    SettingDefinition(
        key="IBKR_ACCOUNT_ID",
        label="IBKR Account ID",
        category="broker",
        required=False,
        sensitive=False,
        description="IBKR 账户 ID，例如 DU1234567 (paper) 或 U1234567 (live)。仅在使用 ibkr 后端时需要。",
    ),
    SettingDefinition(
        key="OPENAI_API_KEY",
        label="OpenAI API Key",
        category="ai",
        required=False,
        description="用于候选池和社媒摘要增强。",
    ),
    SettingDefinition(
        key="OPENAI_CANDIDATE_MODEL",
        label="OpenAI Candidate Model",
        category="ai",
        required=False,
        sensitive=False,
        default="gpt-4o-2024-08-06",
        description="用于每日候选池筛选。",
    ),
    SettingDefinition(
        key="OPENAI_SOCIAL_MODEL",
        label="OpenAI Social Model",
        category="ai",
        required=False,
        sensitive=False,
        default="gpt-4o-2024-08-06",
        description="用于社媒摘要。",
    ),
    SettingDefinition(
        key="ENABLE_SOCIAL_AUTO_TRADE",
        label="Enable Social Auto Trade",
        category="safety",
        required=False,
        sensitive=False,
        default="false",
        description="true 时社媒权重达到阈值后允许自动下单。",
    ),
    SettingDefinition(
        key="ALLOW_LIVE_SOCIAL_ORDERS",
        label="Allow Live Social Orders",
        category="safety",
        required=False,
        sensitive=False,
        default="false",
        description="false 时社媒自动交易仅允许 Alpaca paper 账户。",
    ),
    SettingDefinition(
        key="X_BEARER_TOKEN",
        label="X Bearer Token",
        category="social",
        required=False,
        description="用于官方 X Recent Search。",
    ),
    SettingDefinition(
        key="SMTP_HOST",
        label="SMTP Host",
        category="notifications",
        required=False,
        sensitive=False,
        default="smtp.gmail.com",
        description="用于价格提醒邮件发送。",
    ),
    SettingDefinition(
        key="SMTP_PORT",
        label="SMTP Port",
        category="notifications",
        required=False,
        sensitive=False,
        default="587",
        description="常用值为 587。",
    ),
    SettingDefinition(
        key="SMTP_USERNAME",
        label="SMTP Username",
        category="notifications",
        required=False,
        description="SMTP 登录用户名，通常是邮箱地址。",
    ),
    SettingDefinition(
        key="SMTP_PASSWORD",
        label="SMTP Password",
        category="notifications",
        required=False,
        description="SMTP 登录密码或 App Password。",
    ),
    SettingDefinition(
        key="SMTP_FROM",
        label="SMTP From",
        category="notifications",
        required=False,
        sensitive=False,
        description="价格提醒发件人邮箱。",
    ),
    SettingDefinition(
        key="ALERT_EMAIL_TO",
        label="Alert Email To",
        category="notifications",
        required=False,
        sensitive=False,
        description="价格提醒默认收件人，留空时回退到 SMTP From。",
    ),
    SettingDefinition(
        key="NOTIFICATIONS_WEBHOOK_URL",
        label="Generic Webhook URL",
        category="notifications",
        required=False,
        sensitive=True,
        description="风控/价格提醒事件以原始 JSON 形式 POST 到该地址，留空则跳过。",
    ),
    SettingDefinition(
        key="NOTIFICATIONS_SLACK_WEBHOOK_URL",
        label="Slack Incoming Webhook",
        category="notifications",
        required=False,
        sensitive=True,
        description="Slack 通道：粘贴 Incoming Webhook URL 即可。",
    ),
    SettingDefinition(
        key="NOTIFICATIONS_DISCORD_WEBHOOK_URL",
        label="Discord Webhook",
        category="notifications",
        required=False,
        sensitive=True,
        description="Discord 通道：频道设置 → 整合 → Webhook。",
    ),
    SettingDefinition(
        key="NOTIFICATIONS_TELEGRAM_BOT_TOKEN",
        label="Telegram Bot Token",
        category="notifications",
        required=False,
        sensitive=True,
        description="Telegram 通道：BotFather 创建后给出的 token。",
    ),
    SettingDefinition(
        key="NOTIFICATIONS_TELEGRAM_CHAT_ID",
        label="Telegram Chat ID",
        category="notifications",
        required=False,
        sensitive=False,
        description="Telegram 通道：发送目标的 chat_id（与 bot token 同时填写才生效）。",
    ),
    SettingDefinition(
        key="ALLOW_LIVE_ALERT_ORDERS",
        label="Allow Live Alert Orders",
        category="safety",
        required=False,
        sensitive=False,
        default="false",
        description="false 时自动交易仅允许 Alpaca paper 账户。",
    ),
)

_SETTING_MAP = {item.key: item for item in SETTING_DEFINITIONS}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_stored_values() -> dict[str, str]:
    connection = _connect()
    try:
        rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
        return {
            str(row["key"]).strip(): str(row["value"]).strip()
            for row in rows
            if str(row["key"]).strip()
        }
    finally:
        connection.close()


def get_setting(key: str, default: str | None = None) -> str | None:
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return default

    stored = _read_stored_values().get(normalized_key)
    if stored:
        return stored

    env_value = os.getenv(normalized_key, "").strip()
    if env_value:
        return env_value

    definition = _SETTING_MAP.get(normalized_key)
    if definition and definition.default is not None:
        return definition.default

    return default


def get_required_setting(key: str, error_message: str) -> str:
    value = get_setting(key, "")
    if not value:
        raise RuntimeError(error_message)
    return value


def get_bool_setting(key: str, default: bool = False) -> bool:
    return _parse_bool(get_setting(key), default=default)


def is_admin_token_required() -> bool:
    return bool(os.getenv("SETTINGS_ADMIN_TOKEN", "").strip())


def validate_admin_token(token: str | None) -> None:
    expected = os.getenv("SETTINGS_ADMIN_TOKEN", "").strip()
    if expected and str(token or "").strip() != expected:
        raise PermissionError("管理员口令不正确。")


def get_settings_status() -> dict[str, Any]:
    stored_values = _read_stored_values()
    items: list[dict[str, Any]] = []
    missing_required: list[str] = []

    for definition in SETTING_DEFINITIONS:
        stored_value = stored_values.get(definition.key, "")
        env_value = os.getenv(definition.key, "").strip()

        source = "missing"
        configured = False
        value: str | None = None

        if stored_value:
            configured = True
            source = "stored"
            value = stored_value if not definition.sensitive else None
        elif env_value:
            configured = True
            source = "env"
            value = env_value if not definition.sensitive else None
        elif definition.default is not None:
            configured = True
            source = "default"
            value = definition.default

        if definition.required and not configured:
            missing_required.append(definition.key)

        items.append(
            {
                "key": definition.key,
                "label": definition.label,
                "category": definition.category,
                "required": definition.required,
                "sensitive": definition.sensitive,
                "configured": configured,
                "source": source,
                "value": value,
                "description": definition.description,
            }
        )

    return {
        "is_ready": not missing_required,
        "admin_token_required": is_admin_token_required(),
        "missing_required_keys": missing_required,
        "items": items,
    }


def save_settings(values: dict[str, Any], admin_token: str | None = None) -> dict[str, Any]:
    validate_admin_token(admin_token)
    connection = _connect()
    updated_keys: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    try:
        for key, raw_value in values.items():
            definition = _SETTING_MAP.get(str(key).strip())
            if definition is None:
                continue

            normalized_value = str(raw_value).strip() if raw_value is not None else ""
            if not normalized_value:
                continue

            connection.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (definition.key, normalized_value, now),
            )
            updated_keys.append(definition.key)

        connection.commit()
    finally:
        connection.close()

    status = get_settings_status()
    status["updated_keys"] = updated_keys
    return status
