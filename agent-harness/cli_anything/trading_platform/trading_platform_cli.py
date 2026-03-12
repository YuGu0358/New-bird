from __future__ import annotations

import json
import os
import shlex
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import click
import httpx

from cli_anything.trading_platform.utils.repl_skin import ReplSkin

VERSION = "1.0.0"
DEFAULT_PROJECT_ROOT = "/Users/yugu/Desktop/trading_platform"
PROJECT_ROOT = Path(os.getenv("TRADING_PLATFORM_ROOT", DEFAULT_PROJECT_ROOT))
APP_URL = os.getenv("TRADING_PLATFORM_URL", "http://127.0.0.1:8000")


def _json_mode() -> bool:
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return False
    return bool((ctx.obj or {}).get("json", False))


def _emit(data: Any, *, human: Callable[[], None] | None = None) -> None:
    if _json_mode() or human is None:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    human()


def _print_table(headers: list[str], rows: list[list[Any]]) -> None:
    if not rows:
        click.echo("No data.")
        return

    widths = [len(header) for header in headers]
    normalized_rows: list[list[str]] = []
    for row in rows:
        normalized = ["" if value is None else str(value) for value in row]
        normalized_rows.append(normalized)
        for index, value in enumerate(normalized):
            widths[index] = max(widths[index], len(value))

    click.echo("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    click.echo("  ".join("-" * width for width in widths))
    for row in normalized_rows:
        click.echo("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _format_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _format_percent(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{numeric:+.2f}%"


def _truncate_text(value: Any, *, length: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= length:
        return text
    return f"{text[: length - 3]}..."


def _run_launcher(script_name: str) -> str:
    script_path = PROJECT_ROOT / "launcher" / script_name
    completed = subprocess.run(
        [str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return (completed.stdout or completed.stderr).strip()


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    return response.text.strip() or f"Request failed with status {response.status_code}."


def _api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    auto_start: bool = True,
) -> Any:
    url = f"{APP_URL}{path}"

    try:
        response = httpx.request(method, url, json=payload, timeout=90.0)
    except httpx.HTTPError:
        if not auto_start:
            raise
        _run_launcher("start_trading_platform.sh")
        try:
            response = httpx.request(method, url, json=payload, timeout=90.0)
        except httpx.HTTPError as exc:
            raise click.ClickException(str(exc)) from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(_extract_error_detail(response)) from exc
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response.text
    return response.json()


@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output JSON.")
@click.pass_context
def main(ctx: click.Context, use_json: bool) -> None:
    """CLI-Anything style harness for the trading platform."""

    ctx.ensure_object(dict)
    ctx.obj["json"] = use_json

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@main.group()
def account() -> None:
    """Account commands."""


@account.command("show")
def account_show() -> None:
    payload = _api_request("GET", "/api/account")
    _emit(
        payload,
        human=lambda: click.echo(
            "\n".join(
                [
                    f"Account ID: {payload['account_id']}",
                    f"Status: {payload['status']}",
                    f"Equity: {_format_money(payload['equity'])}",
                    f"Cash: {_format_money(payload['cash'])}",
                    f"Buying Power: {_format_money(payload['buying_power'])}",
                ]
            )
        ),
    )


@main.group()
def positions() -> None:
    """Position commands."""


@positions.command("list")
def positions_list() -> None:
    payload = _api_request("GET", "/api/positions")
    _emit(
        payload,
        human=lambda: _print_table(
            ["Symbol", "Qty", "Entry", "Current", "Value", "P/L"],
            [
                [
                    item["symbol"],
                    f"{float(item['qty']):.4f}",
                    _format_money(item["entry_price"]),
                    _format_money(item["current_price"]),
                    _format_money(item["market_value"]),
                    _format_money(item["unrealized_pl"]),
                ]
                for item in payload
            ],
        ),
    )


@main.group()
def orders() -> None:
    """Order commands."""


@orders.command("list")
@click.option("--status", default="all", show_default=True)
def orders_list(status: str) -> None:
    payload = _api_request("GET", f"/api/orders?status={status}")
    _emit(
        payload,
        human=lambda: _print_table(
            ["Symbol", "Side", "Type", "Status", "Qty", "Created"],
            [
                [
                    item["symbol"],
                    item["side"],
                    item["order_type"],
                    item["status"],
                    item.get("qty") or item.get("notional") or "",
                    item.get("created_at", ""),
                ]
                for item in payload
            ],
        ),
    )


@main.group()
def trades() -> None:
    """Closed-trade commands."""


@trades.command("list")
def trades_list() -> None:
    payload = _api_request("GET", "/api/trades")
    _emit(
        payload,
        human=lambda: _print_table(
            ["Symbol", "Qty", "Entry", "Exit", "P/L", "Reason"],
            [
                [
                    item["symbol"],
                    f"{float(item['qty']):.4f}",
                    _format_money(item["entry_price"]),
                    _format_money(item["exit_price"]),
                    _format_money(item["net_profit"]),
                    item["exit_reason"],
                ]
                for item in payload
            ],
        ),
    )


@main.group()
def monitoring() -> None:
    """Monitoring and candidate-pool commands."""


def _monitoring_payload(refresh: bool) -> dict[str, Any]:
    path = "/api/monitoring?force_refresh=true" if refresh else "/api/monitoring"
    return _api_request("GET", path)


@monitoring.command("overview")
@click.option("--refresh", is_flag=True, help="Force refresh today's monitoring snapshot.")
def monitoring_overview(refresh: bool) -> None:
    payload = _monitoring_payload(refresh)
    _emit(
        payload,
        human=lambda: click.echo(
            "\n".join(
                [
                    f"Selected symbols: {len(payload.get('selected_symbols', []))}",
                    f"Candidate pool: {len(payload.get('candidate_pool', []))}",
                    f"Tracked symbols: {len(payload.get('tracked_symbols', []))}",
                    "Top candidates: "
                    + ", ".join(item["symbol"] for item in payload.get("candidate_pool", [])),
                ]
            )
        ),
    )


@monitoring.command("candidates")
@click.option("--refresh", is_flag=True, help="Force refresh today's candidate pool.")
def monitoring_candidates(refresh: bool) -> None:
    payload = _monitoring_payload(refresh).get("candidate_pool", [])
    _emit(
        payload,
        human=lambda: _print_table(
            ["Rank", "Symbol", "Category", "Score", "Day", "Week", "Month"],
            [
                [
                    item["rank"],
                    item["symbol"],
                    item["category"],
                    f"{float(item['score']):.2f}",
                    _format_percent(item["trend"].get("day_change_percent")),
                    _format_percent(item["trend"].get("week_change_percent")),
                    _format_percent(item["trend"].get("month_change_percent")),
                ]
                for item in payload
            ],
        ),
    )


@monitoring.command("tracked")
@click.option("--refresh", is_flag=True, help="Force refresh trend snapshots.")
def monitoring_tracked(refresh: bool) -> None:
    payload = _monitoring_payload(refresh).get("tracked_symbols", [])
    _emit(
        payload,
        human=lambda: _print_table(
            ["Symbol", "Tags", "Current", "Day", "Week", "Month"],
            [
                [
                    item["symbol"],
                    ",".join(item.get("tags", [])),
                    _format_money(item["trend"].get("current_price")),
                    _format_percent(item["trend"].get("day_change_percent")),
                    _format_percent(item["trend"].get("week_change_percent")),
                    _format_percent(item["trend"].get("month_change_percent")),
                ]
                for item in payload
            ],
        ),
    )


@main.group()
def universe() -> None:
    """Alpaca universe commands."""


@universe.command("search")
@click.argument("query")
@click.option("--limit", default=10, show_default=True, type=int)
def universe_search(query: str, limit: int) -> None:
    payload = _api_request("GET", f"/api/universe?query={query}&limit={limit}")
    _emit(
        payload,
        human=lambda: _print_table(
            ["Symbol", "Name", "Exchange", "Fractionable"],
            [
                [
                    item["symbol"],
                    item.get("name", ""),
                    item.get("exchange", ""),
                    item.get("fractionable", False),
                ]
                for item in payload
            ],
        ),
    )


@main.group()
def watchlist() -> None:
    """Watchlist commands."""


@watchlist.command("list")
def watchlist_list() -> None:
    payload = _monitoring_payload(False).get("selected_symbols", [])
    _emit(payload, human=lambda: click.echo("\n".join(payload)))


@watchlist.command("add")
@click.argument("symbol")
def watchlist_add(symbol: str) -> None:
    payload = _api_request("POST", "/api/watchlist", payload={"symbol": symbol})
    _emit(payload, human=lambda: click.echo(f"Added {symbol.upper()}. Total: {len(payload)}"))


@watchlist.command("remove")
@click.argument("symbol")
def watchlist_remove(symbol: str) -> None:
    payload = _api_request("DELETE", f"/api/watchlist/{symbol}")
    _emit(payload, human=lambda: click.echo(f"Removed {symbol.upper()}. Total: {len(payload)}"))


@main.group()
def news() -> None:
    """News commands."""


@news.command("get")
@click.argument("symbol")
def news_get(symbol: str) -> None:
    payload = _api_request("GET", f"/api/news/{symbol.upper()}")
    _emit(
        payload,
        human=lambda: click.echo(f"{payload['symbol']}\n{payload['summary']}"),
    )


@main.group()
def research() -> None:
    """Research commands."""


@research.command("get")
@click.argument("symbol")
@click.option("--model", "research_model", default="mini", show_default=True)
def research_get(symbol: str, research_model: str) -> None:
    payload = _api_request("GET", f"/api/research/{symbol.upper()}?research_model={research_model}")
    _emit(
        payload,
        human=lambda: click.echo(
            "\n".join(
                [
                    f"{payload['symbol']} · {payload['company_name']}",
                    f"Recommendation: {payload['recommendation']}",
                    f"Outlook: {payload['price_outlook']}",
                    f"Risk: {payload['risk_assessment']}",
                    "",
                    payload["summary"],
                ]
            )
        ),
    )


@main.group()
def social() -> None:
    """Social-search commands."""


@social.command("providers")
def social_providers() -> None:
    payload = _api_request("GET", "/api/social/providers")
    _emit(
        payload,
        human=lambda: _print_table(
            ["Provider", "Supported", "Configured", "Note"],
            [
                [
                    item["name"],
                    item["supported"],
                    item["configured"],
                    item.get("note", ""),
                ]
                for item in payload
            ],
        ),
    )


def _social_query_path(
    *,
    query: str,
    provider: str,
    limit: int,
    lang: str,
    min_likes: int,
    min_reposts: int,
    exclude_terms: tuple[str, ...],
    include_reposts: bool,
    include_replies: bool,
    summarize: bool,
    refresh: bool,
) -> str:
    params: list[tuple[str, Any]] = [
        ("query", query),
        ("provider", provider),
        ("limit", limit),
        ("min_like_count", min_likes),
        ("min_repost_count", min_reposts),
        ("exclude_reposts", not include_reposts),
        ("exclude_replies", not include_replies),
        ("summarize", summarize),
        ("force_refresh", refresh),
    ]
    if lang:
        params.append(("lang", lang))
    for term in exclude_terms:
        params.append(("exclude_terms", term))
    return f"/api/social/search?{urlencode(params, doseq=True)}"


def _render_social_payload(payload: dict[str, Any]) -> None:
    click.echo(
        "\n".join(
            [
                f"Provider: {payload['provider']}",
                f"Query: {payload['normalized_query']}",
                f"Results: {payload['returned_results']} / {payload['total_results']}",
                f"Rate limit remaining: {payload.get('rate_limit_remaining')}",
            ]
        )
    )
    if payload.get("summary"):
        click.echo("")
        click.echo(payload["summary"])
    if payload.get("counts"):
        total_count = sum(int(item.get("post_count", 0) or 0) for item in payload["counts"])
        click.echo("")
        click.echo(f"Recent mention count: {total_count}")
    if payload.get("posts"):
        click.echo("")
        _print_table(
            ["Author", "Likes", "Reposts", "Score", "Text"],
            [
                [
                    f"@{(item.get('author', {}) or {}).get('username') or 'unknown'}",
                    (item.get("metrics", {}) or {}).get("like_count", 0),
                    (item.get("metrics", {}) or {}).get("repost_count", 0),
                    f"{float(item.get('score', 0.0)):.2f}",
                    _truncate_text(item.get("text", "")),
                ]
                for item in payload["posts"]
            ],
        )


@social.command("search")
@click.argument("query")
@click.option("--provider", default="x", show_default=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--lang", default="", show_default=False)
@click.option("--min-likes", default=0, show_default=True, type=int)
@click.option("--min-reposts", default=0, show_default=True, type=int)
@click.option("--exclude-term", "exclude_terms", multiple=True)
@click.option("--include-reposts", is_flag=True, help="Include reposts/retweets.")
@click.option("--include-replies", is_flag=True, help="Include replies.")
@click.option("--summarize", is_flag=True, help="Generate a Chinese digest.")
@click.option("--refresh", is_flag=True, help="Bypass cache.")
def social_search(
    query: str,
    provider: str,
    limit: int,
    lang: str,
    min_likes: int,
    min_reposts: int,
    exclude_terms: tuple[str, ...],
    include_reposts: bool,
    include_replies: bool,
    summarize: bool,
    refresh: bool,
) -> None:
    payload = _api_request(
        "GET",
        _social_query_path(
            query=query,
            provider=provider,
            limit=limit,
            lang=lang,
            min_likes=min_likes,
            min_reposts=min_reposts,
            exclude_terms=exclude_terms,
            include_reposts=include_reposts,
            include_replies=include_replies,
            summarize=summarize,
            refresh=refresh,
        ),
    )
    _emit(payload, human=lambda: _render_social_payload(payload))


@social.command("digest")
@click.argument("query")
@click.option("--provider", default="x", show_default=True)
@click.option("--limit", default=8, show_default=True, type=int)
@click.option("--lang", default="", show_default=False)
@click.option("--min-likes", default=10, show_default=True, type=int)
@click.option("--min-reposts", default=2, show_default=True, type=int)
@click.option("--exclude-term", "exclude_terms", multiple=True)
@click.option("--include-reposts", is_flag=True, help="Include reposts/retweets.")
@click.option("--include-replies", is_flag=True, help="Include replies.")
@click.option("--refresh", is_flag=True, help="Bypass cache.")
def social_digest(
    query: str,
    provider: str,
    limit: int,
    lang: str,
    min_likes: int,
    min_reposts: int,
    exclude_terms: tuple[str, ...],
    include_reposts: bool,
    include_replies: bool,
    refresh: bool,
) -> None:
    payload = _api_request(
        "GET",
        _social_query_path(
            query=query,
            provider=provider,
            limit=limit,
            lang=lang,
            min_likes=min_likes,
            min_reposts=min_reposts,
            exclude_terms=exclude_terms,
            include_reposts=include_reposts,
            include_replies=include_replies,
            summarize=True,
            refresh=refresh,
        ),
    )
    _emit(payload, human=lambda: _render_social_payload(payload))


@main.group()
def bot() -> None:
    """Bot control commands."""


@bot.command("status")
def bot_status() -> None:
    try:
        payload = _api_request("GET", "/api/bot/status", auto_start=False)
    except Exception:
        payload = {"is_running": False, "started_at": None, "uptime_seconds": None, "last_error": None}
    _emit(
        payload,
        human=lambda: click.echo(
            "\n".join(
                [
                    f"Running: {payload['is_running']}",
                    f"Started at: {payload.get('started_at') or ''}",
                    f"Uptime seconds: {payload.get('uptime_seconds')}",
                    f"Last error: {payload.get('last_error') or 'none'}",
                ]
            )
        ),
    )


@bot.command("start")
def bot_start() -> None:
    _run_launcher("start_trading_platform.sh")
    payload = _api_request("POST", "/api/bot/start")
    _emit(payload, human=lambda: click.echo(payload["message"]))


@bot.command("stop")
def bot_stop() -> None:
    payload = _api_request("POST", "/api/bot/stop", auto_start=False)
    _emit(payload, human=lambda: click.echo(payload["message"]))


@main.group()
def app() -> None:
    """Local app launcher commands."""


@app.command("start")
def app_start() -> None:
    message = _run_launcher("start_trading_platform.sh")
    _emit({"message": message}, human=lambda: click.echo(message))


@app.command("stop")
def app_stop() -> None:
    message = _run_launcher("stop_trading_platform.sh")
    _emit({"message": message}, human=lambda: click.echo(message))


@app.command("open")
def app_open() -> None:
    _run_launcher("start_trading_platform.sh")
    webbrowser.open(APP_URL)
    _emit({"url": APP_URL}, human=lambda: click.echo(f"Opened {APP_URL}"))


@main.command()
def repl() -> None:
    """Interactive REPL."""

    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.history import FileHistory
    except ImportError:
        prompt = None
        FileHistory = None

    skin = ReplSkin("trading-platform", version=VERSION)
    skin.print_banner()

    history_path = str(Path.home() / ".cli-anything-trading-platform-history")

    while True:
        try:
            if prompt is not None and FileHistory is not None:
                command = prompt(skin.prompt(), history=FileHistory(history_path))
            else:
                command = input(skin.prompt())
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        text = command.strip()
        if not text:
            continue
        if text in {"exit", "quit"}:
            break
        if text == "help":
            click.echo(
                "Examples: monitoring overview --refresh | universe search NVDA | "
                "watchlist add ABNB | social digest \"NVDA AI\""
            )
            continue

        try:
            args = shlex.split(text)
            main.main(args=args, prog_name="cli-anything-trading-platform", standalone_mode=False, obj={"json": False})
        except SystemExit:
            continue
        except Exception as exc:  # pragma: no cover - interactive guard
            skin.error(str(exc))


if __name__ == "__main__":
    main()
