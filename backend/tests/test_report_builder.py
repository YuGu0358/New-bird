"""Tests for the HTML report builder service + router (Phase 7.4 lite)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import report_builder_service
from app.services.report_builder_service import _fmt_num, _fmt_pct


# ---------- Numeric formatters ----------


def test_fmt_pct_basic() -> None:
    assert _fmt_pct(0.05) == "5.00%"


def test_fmt_pct_none_returns_dash() -> None:
    assert _fmt_pct(None) == "—"


def test_fmt_pct_garbage_returns_dash() -> None:
    assert _fmt_pct("not a number") == "—"


def test_fmt_num_two_decimals() -> None:
    assert _fmt_num(3.14159, 2) == "3.14"


def test_fmt_num_default_four_decimals() -> None:
    assert _fmt_num(1.23456789) == "1.2346"


def test_fmt_num_none_returns_dash() -> None:
    assert _fmt_num(None) == "—"


# ---------- render_backtest_tearsheet ----------


@pytest.mark.asyncio
async def test_render_backtest_tearsheet_present() -> None:
    payload = {
        "run_id": 42,
        "periods_per_year": 252,
        "risk_free_rate": 0.04,
        "cagr": 0.18,
        "volatility": 0.21,
        "sharpe": 1.345,
        "sortino": 1.789,
        "max_drawdown": -0.12,
        "calmar": 1.5,
        "total_return": 0.36,
        "periods": 1000,
        "generated_at": datetime.now(timezone.utc),
    }
    with patch.object(
        report_builder_service.tearsheet_service,
        "get_tearsheet",
        new=AsyncMock(return_value=payload),
    ):
        html = await report_builder_service.render_backtest_tearsheet(
            session=None, run_id=42  # type: ignore[arg-type]
        )

    assert "Sharpe" in html
    assert "CAGR" in html
    assert "42" in html
    assert "<!DOCTYPE html>" in html
    assert "@media print" in html


@pytest.mark.asyncio
async def test_render_backtest_tearsheet_missing_raises_lookup() -> None:
    with patch.object(
        report_builder_service.tearsheet_service,
        "get_tearsheet",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(LookupError):
            await report_builder_service.render_backtest_tearsheet(
                session=None, run_id=999  # type: ignore[arg-type]
            )


# ---------- render_portfolio_overview ----------


def _account(broker_account_id: int = 7, alias: str = "Main") -> dict:
    return {
        "id": broker_account_id,
        "broker": "ibkr",
        "account_id": "DU1234567",
        "alias": alias,
        "tier": "tier_2",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _snapshot(symbol: str, unrealized_pl: float | None) -> dict:
    return {
        "id": 1,
        "broker_account_id": 7,
        "symbol": symbol,
        "snapshot_at": datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        "qty": 100.0,
        "avg_cost": 50.0,
        "market_value": 5500.0,
        "current_price": 55.0,
        "unrealized_pl": unrealized_pl,
        "side": "long",
    }


@pytest.mark.asyncio
async def test_render_portfolio_overview_present() -> None:
    with patch.object(
        report_builder_service.broker_accounts_service,
        "get_account",
        new=AsyncMock(return_value=_account()),
    ), patch.object(
        report_builder_service.position_sync_service,
        "list_snapshots",
        new=AsyncMock(return_value=[_snapshot("AAPL", 500.0)]),
    ), patch.object(
        report_builder_service.position_overrides_service,
        "list_overrides",
        new=AsyncMock(return_value=[]),
    ):
        html = await report_builder_service.render_portfolio_overview(
            session=None, broker_account_id=7  # type: ignore[arg-type]
        )

    assert "ibkr" in html
    assert "DU1234567" in html
    assert "tier_2" in html
    assert "AAPL" in html


@pytest.mark.asyncio
async def test_render_portfolio_overview_missing_raises_lookup() -> None:
    with patch.object(
        report_builder_service.broker_accounts_service,
        "get_account",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(LookupError):
            await report_builder_service.render_portfolio_overview(
                session=None, broker_account_id=999  # type: ignore[arg-type]
            )


@pytest.mark.asyncio
async def test_render_portfolio_overview_pnl_sign_classes() -> None:
    """Positive PnL gets `pos` class; negative gets `neg`."""
    with patch.object(
        report_builder_service.broker_accounts_service,
        "get_account",
        new=AsyncMock(return_value=_account()),
    ), patch.object(
        report_builder_service.position_sync_service,
        "list_snapshots",
        new=AsyncMock(
            return_value=[
                _snapshot("AAPL", 500.0),
                _snapshot("TSLA", -250.0),
            ]
        ),
    ), patch.object(
        report_builder_service.position_overrides_service,
        "list_overrides",
        new=AsyncMock(return_value=[]),
    ):
        html = await report_builder_service.render_portfolio_overview(
            session=None, broker_account_id=7  # type: ignore[arg-type]
        )

    assert "pos" in html
    assert "neg" in html


@pytest.mark.asyncio
async def test_render_portfolio_overview_escapes_override_notes() -> None:
    """User-typed override notes are HTML-escaped to prevent XSS."""
    override = {
        "id": 1,
        "broker_account_id": 7,
        "ticker": "AAPL",
        "stop_price": None,
        "take_profit_price": None,
        "notes": "<script>alert(1)</script>",
        "tier_override": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    with patch.object(
        report_builder_service.broker_accounts_service,
        "get_account",
        new=AsyncMock(return_value=_account()),
    ), patch.object(
        report_builder_service.position_sync_service,
        "list_snapshots",
        new=AsyncMock(return_value=[_snapshot("AAPL", 100.0)]),
    ), patch.object(
        report_builder_service.position_overrides_service,
        "list_overrides",
        new=AsyncMock(return_value=[override]),
    ):
        html = await report_builder_service.render_portfolio_overview(
            session=None, broker_account_id=7  # type: ignore[arg-type]
        )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.asyncio
async def test_render_portfolio_overview_empty_snapshots() -> None:
    with patch.object(
        report_builder_service.broker_accounts_service,
        "get_account",
        new=AsyncMock(return_value=_account()),
    ), patch.object(
        report_builder_service.position_sync_service,
        "list_snapshots",
        new=AsyncMock(return_value=[]),
    ), patch.object(
        report_builder_service.position_overrides_service,
        "list_overrides",
        new=AsyncMock(return_value=[]),
    ):
        html = await report_builder_service.render_portfolio_overview(
            session=None, broker_account_id=7  # type: ignore[arg-type]
        )

    assert "No snapshots recorded" in html


# ---------- Router smoke ----------


def test_backtest_html_endpoint_returns_html(client) -> None:
    payload = {
        "run_id": 1,
        "periods_per_year": 252,
        "risk_free_rate": 0.04,
        "cagr": 0.10,
        "volatility": 0.15,
        "sharpe": 1.0,
        "sortino": 1.2,
        "max_drawdown": -0.08,
        "calmar": 1.25,
        "total_return": 0.20,
        "periods": 252,
        "generated_at": datetime.now(timezone.utc),
    }
    with patch.object(
        report_builder_service.tearsheet_service,
        "get_tearsheet",
        new=AsyncMock(return_value=payload),
    ):
        resp = client.get("/api/reports/backtest/1.html")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Sharpe" in resp.text


def test_backtest_html_endpoint_404_when_missing(client) -> None:
    with patch.object(
        report_builder_service.tearsheet_service,
        "get_tearsheet",
        new=AsyncMock(return_value=None),
    ):
        resp = client.get("/api/reports/backtest/9999.html")
    assert resp.status_code == 404


def test_portfolio_html_endpoint_404_when_missing(client) -> None:
    with patch.object(
        report_builder_service.broker_accounts_service,
        "get_account",
        new=AsyncMock(return_value=None),
    ):
        resp = client.get("/api/reports/portfolio/9999.html")
    assert resp.status_code == 404
