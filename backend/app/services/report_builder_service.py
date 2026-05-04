"""HTML report rendering — jinja2-backed.

Composes context dicts from the existing tearsheet / portfolio services
and renders a stand-alone HTML page. The page includes inline CSS with
an `@media print` block tuned for A4 — users can browser-print to PDF
without needing weasyprint or any system libraries.

Design:
- Templates live in `app/templates/reports/`. The shared `_base.html.j2`
  defines the doc skeleton + print CSS; specific reports extend it.
- Autoescape is ON so user-typed override notes can't XSS the page.
- Numeric formatters live as jinja filters (`fmt_pct`, `fmt_num`) so
  the templates stay readable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import position_sync_service, tearsheet_service
from app.services import broker_accounts_service, position_overrides_service

logger = logging.getLogger(__name__)


_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "reports"


def _fmt_num(value: Any, decimals: int = 4) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:,.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def _build_env() -> Environment:
    # We name templates `*.html.j2` (extends `_base.html.j2`), so explicitly
    # match that suffix in addition to the bare html/xml — `select_autoescape`'s
    # default suffix list misses `.j2` and would silently leave content
    # unescaped, defeating XSS protection on user-typed override notes.
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "xml", "html.j2", "j2"),
            default_for_string=True,
            default=True,
        ),
    )
    env.filters["fmt_num"] = _fmt_num
    env.filters["fmt_pct"] = _fmt_pct
    env.filters["fmt_dt"] = _fmt_dt
    return env


# Module-level env so we don't reload templates from disk every request.
_env = _build_env()


async def render_backtest_tearsheet(
    session: AsyncSession, run_id: int
) -> str:
    """Render the backtest tearsheet as HTML.

    Raises LookupError when the run_id has no equity curve.
    """
    payload = await tearsheet_service.get_tearsheet(session, run_id)
    if payload is None:
        raise LookupError(f"Backtest run {run_id} not found")
    template = _env.get_template("backtest_tearsheet.html.j2")
    return template.render(
        title=f"Backtest #{run_id} Tearsheet",
        generated_at=datetime.now(timezone.utc),
        metrics=payload,
    )


async def render_portfolio_overview(
    session: AsyncSession, broker_account_id: int
) -> str:
    """Render a per-account portfolio overview HTML.

    Raises LookupError when the broker_account_id has no row.
    """
    account = await broker_accounts_service.get_account(session, broker_account_id)
    if account is None:
        raise LookupError(f"Broker account {broker_account_id} not found")

    snapshots = await position_sync_service.list_snapshots(
        session,
        broker_account_id=broker_account_id,
        limit=50,
    )
    overrides = await position_overrides_service.list_overrides(
        session,
        broker_account_id=broker_account_id,
    )
    overrides_by_ticker = {o["ticker"]: o for o in overrides}

    template = _env.get_template("portfolio_overview.html.j2")
    return template.render(
        title=f"Portfolio · {account['alias'] or account['account_id']}",
        generated_at=datetime.now(timezone.utc),
        account=account,
        snapshots=snapshots,
        overrides_by_ticker=overrides_by_ticker,
    )
