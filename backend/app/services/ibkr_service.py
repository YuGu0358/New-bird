"""IBKR (Interactive Brokers) service layer mirroring the Alpaca surface.

Five public coroutines wrap ``ib_async`` calls into the Newbird-shaped dicts
that the rest of the platform consumes:

* :func:`get_account` — account summary mapped to {id, status, currency,
  equity, cash, buying_power}
* :func:`list_positions` — open positions filtered to ``IBKR_ACCOUNT_ID``
* :func:`list_orders` — merged open + completed (last 7 days) order list
* :func:`submit_order` — Stock + MarketOrder submission, with notional →
  qty conversion via mid-price
* :func:`close_position` — submits the opposite-side market order to flatten
  an existing position

Connection lifecycle is owned by :func:`app.services.ibkr_client.get_client`;
this module never touches sockets directly and never reads HOST/PORT/CLIENT_ID.
``IBKR_ACCOUNT_ID`` is read here because it filters response payloads rather
than the connection itself.

All side translation (``buy``/``sell`` ↔ ``BUY``/``SELL``) happens at this
boundary; IBKR's uppercase codes never leak out into Newbird code.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from ib_async import MarketOrder, Stock

from app import runtime_settings
from app.services.ibkr_client import IBKRConfigError, get_client

# Tags returned by ``ib.accountSummary()`` that we map onto the Newbird shape.
_TAG_EQUITY = "NetLiquidation"
_TAG_BUYING_POWER = "BuyingPower"
_TAG_CASH = "TotalCashValue"
_TAG_ACCOUNT_TYPE = "AccountType"

# How far back to look when status='closed'. IBKR's completed-orders feed is
# session-scoped, but we still bound it for paper/live parity with Alpaca.
_CLOSED_ORDERS_LOOKBACK = timedelta(days=7)

_BUY_ACTION = "BUY"
_SELL_ACTION = "SELL"


# --------------------------------------------------------------------------- #
# settings                                                                    #
# --------------------------------------------------------------------------- #

def _require_account_id() -> str:
    """Return the configured IBKR account id, raising on missing config."""

    account_id = (runtime_settings.get_setting("IBKR_ACCOUNT_ID", "") or "").strip()
    if not account_id:
        raise IBKRConfigError(
            "IBKR_ACCOUNT_ID is not configured — set it in the settings page or backend/.env."
        )
    return account_id


# --------------------------------------------------------------------------- #
# small helpers                                                               #
# --------------------------------------------------------------------------- #

def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_side_to_ibkr(side: str) -> str:
    """Translate Newbird lowercase ``buy``/``sell`` into IBKR ``BUY``/``SELL``."""

    cleaned = (side or "").strip().lower()
    if cleaned == "buy":
        return _BUY_ACTION
    if cleaned == "sell":
        return _SELL_ACTION
    raise ValueError(f"Unsupported order side {side!r}; expected 'buy' or 'sell'.")


def _normalize_action_to_newbird(action: str) -> str:
    """Translate IBKR ``BUY``/``SELL`` back to Newbird lowercase."""

    cleaned = (action or "").strip().upper()
    if cleaned == _BUY_ACTION:
        return "buy"
    if cleaned == _SELL_ACTION:
        return "sell"
    return cleaned.lower() or "buy"


def _make_stock_contract(symbol: str) -> Stock:
    """Build the canonical SMART/USD equity contract for ``symbol``."""

    cleaned = (symbol or "").strip().upper()
    if not cleaned:
        raise ValueError("symbol is required")
    return Stock(symbol=cleaned, exchange="SMART", currency="USD")


def _account_status_from_type(account_type: str) -> str:
    """Map IBKR account-type string onto a coarse Newbird status label."""

    if not account_type:
        return "ACTIVE"
    if account_type.upper() in {"PAPER", "DEMO"}:
        return "PAPER"
    return "ACTIVE"


# --------------------------------------------------------------------------- #
# Trade → dict shaping                                                        #
# --------------------------------------------------------------------------- #

def _trade_submitted_at(trade: Any) -> datetime | None:
    """Pull the earliest log timestamp off a Trade for ``submitted_at``."""

    log = getattr(trade, "log", None) or []
    times: list[datetime] = []
    for entry in log:
        ts = getattr(entry, "time", None)
        if isinstance(ts, datetime):
            times.append(ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))
    return min(times) if times else None


def _trade_to_dict(trade: Any) -> dict[str, Any]:
    """Render an ib_async ``Trade`` into the Newbird order shape."""

    contract = getattr(trade, "contract", None)
    order = getattr(trade, "order", None)
    status = getattr(trade, "orderStatus", None)

    perm_id = getattr(order, "permId", 0) or getattr(status, "permId", 0) or getattr(order, "orderId", 0)
    symbol = getattr(contract, "symbol", "") if contract is not None else ""
    action = getattr(order, "action", "") if order is not None else ""
    qty = _to_float(getattr(order, "totalQuantity", 0)) if order is not None else 0.0
    status_str = getattr(status, "status", "") if status is not None else ""
    avg_fill = _to_float(getattr(status, "avgFillPrice", 0.0)) if status is not None else 0.0

    return {
        "id": str(perm_id) if perm_id else "",
        "symbol": symbol,
        "side": _normalize_action_to_newbird(action),
        "qty": qty,
        "status": status_str,
        "submitted_at": _trade_submitted_at(trade),
        "filled_avg_price": avg_fill if avg_fill > 0 else None,
    }


def _trade_to_submit_dict(trade: Any) -> dict[str, Any]:
    """``submit_order`` / ``close_position`` return shape (no filled price)."""

    base = _trade_to_dict(trade)
    return {
        "id": base["id"],
        "symbol": base["symbol"],
        "side": base["side"],
        "qty": base["qty"],
        "status": base["status"],
        "submitted_at": base["submitted_at"],
    }


# --------------------------------------------------------------------------- #
# market price (for notional → qty)                                           #
# --------------------------------------------------------------------------- #

async def _resolve_market_price(ib: Any, contract: Stock) -> float:
    """Return current mid-price for ``contract`` or raise if unavailable."""

    tickers = await ib.reqTickersAsync(contract)
    price = float("nan")
    if tickers:
        ticker = tickers[0]
        marketPrice = getattr(ticker, "marketPrice", None)
        if callable(marketPrice):
            price = float(marketPrice())
        else:
            price = _to_float(marketPrice)

    if math.isnan(price) or price <= 0:
        raise ValueError(
            "market price unavailable for IBKR notional order — pass qty instead"
        )
    return price


# --------------------------------------------------------------------------- #
# public API                                                                  #
# --------------------------------------------------------------------------- #

async def get_account() -> dict[str, Any]:
    """Read accountSummary() under ``IBKR_ACCOUNT_ID`` and map to Newbird shape.

    Returns a dict with keys ``{id, status, currency, equity, cash, buying_power}``.
    """

    account_id = _require_account_id()

    async with get_client() as ib:
        rows = ib.accountSummary()

    equity = 0.0
    cash = 0.0
    buying_power = 0.0
    currency = "USD"
    account_type = ""

    for row in rows or []:
        if getattr(row, "account", "") != account_id:
            continue
        tag = getattr(row, "tag", "")
        value = getattr(row, "value", "")
        if tag == _TAG_EQUITY:
            equity = _to_float(value)
            currency = getattr(row, "currency", currency) or currency
        elif tag == _TAG_BUYING_POWER:
            buying_power = _to_float(value)
        elif tag == _TAG_CASH:
            cash = _to_float(value)
        elif tag == _TAG_ACCOUNT_TYPE:
            account_type = str(value or "")

    return {
        "id": account_id,
        "status": _account_status_from_type(account_type),
        "currency": currency,
        "equity": equity,
        "cash": cash,
        "buying_power": buying_power,
    }


async def list_positions() -> list[dict[str, Any]]:
    """List open positions for ``IBKR_ACCOUNT_ID`` mapped to the Newbird shape."""

    account_id = _require_account_id()

    async with get_client() as ib:
        positions = ib.positions() or []
        # filter early so we don't request market data for irrelevant accounts
        own_positions = [p for p in positions if getattr(p, "account", "") == account_id]
        if not own_positions:
            return []

        contracts = [getattr(p, "contract", None) for p in own_positions]
        contracts = [c for c in contracts if c is not None]
        try:
            tickers = await ib.reqTickersAsync(*contracts)
        except Exception:
            tickers = []

    # Walk tickers once; index into the resulting price list both by contract
    # symbol and by position index (mocks may not back-reference the contract).
    price_by_symbol: dict[str, float] = {}
    indexed_prices: list[float] = []
    for ticker in tickers or []:
        market_price_fn = getattr(ticker, "marketPrice", None)
        try:
            price = float(market_price_fn()) if callable(market_price_fn) else _to_float(market_price_fn)
        except Exception:
            price = float("nan")
        indexed_prices.append(price)
        ticker_contract = getattr(ticker, "contract", None)
        ticker_symbol = getattr(ticker_contract, "symbol", "") if ticker_contract is not None else ""
        if ticker_symbol and not math.isnan(price) and price > 0:
            price_by_symbol[ticker_symbol] = price

    rows: list[dict[str, Any]] = []
    for index, position in enumerate(own_positions):
        contract = getattr(position, "contract", None)
        symbol = getattr(contract, "symbol", "") if contract is not None else ""
        qty = _to_float(getattr(position, "position", 0.0))
        avg_cost = _to_float(getattr(position, "avgCost", 0.0))

        current_price = price_by_symbol.get(symbol)
        if current_price is None and index < len(indexed_prices):
            candidate = indexed_prices[index]
            if not math.isnan(candidate) and candidate > 0:
                current_price = candidate
        if current_price is None:
            current_price = avg_cost

        market_value = qty * current_price
        unrealized_pl = (current_price - avg_cost) * qty
        side = "long" if qty >= 0 else "short"

        rows.append(
            {
                "symbol": symbol,
                "qty": qty,
                "avg_entry_price": avg_cost,
                "market_value": market_value,
                "current_price": current_price,
                "unrealized_pl": unrealized_pl,
                "side": side,
            }
        )
    return rows


async def list_orders(*, status: str = "all", limit: int | None = None) -> list[dict[str, Any]]:
    """Merge open + completed orders into the Newbird order shape.

    ``status`` selects which streams are read:
    * ``'open'``   → only ``ib.openTrades()``
    * ``'closed'`` → only ``ib.reqCompletedOrdersAsync()`` within last 7 days
    * ``'all'``    → both
    """

    _require_account_id()
    normalized = (status or "all").strip().lower()
    if normalized not in {"all", "open", "closed"}:
        raise ValueError(f"unsupported status filter {status!r}")

    open_trades: list[Any] = []
    closed_trades: list[Any] = []

    async with get_client() as ib:
        if normalized in {"open", "all"}:
            open_trades = list(ib.openTrades() or [])
        if normalized in {"closed", "all"}:
            raw_completed = await ib.reqCompletedOrdersAsync(False)
            closed_trades = list(raw_completed or [])

    cutoff = datetime.now(timezone.utc) - _CLOSED_ORDERS_LOOKBACK
    rows = [_trade_to_dict(trade) for trade in open_trades]
    for trade in closed_trades:
        ts = _trade_submitted_at(trade)
        if ts is None or ts >= cutoff:
            rows.append(_trade_to_dict(trade))

    rows.sort(
        key=lambda r: r["submitted_at"] or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )

    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


async def submit_order(
    *,
    symbol: str,
    side: str,
    notional: float | None = None,
    qty: float | None = None,
) -> dict[str, Any]:
    """Submit a market order. Provide exactly one of ``notional`` or ``qty``."""

    if (qty is None and notional is None) or (qty is not None and notional is not None):
        raise ValueError("Provide exactly one of qty or notional when submitting an order.")

    _require_account_id()
    contract = _make_stock_contract(symbol)
    action = _normalize_side_to_ibkr(side)

    async with get_client() as ib:
        if qty is None:
            price = await _resolve_market_price(ib, contract)
            assert notional is not None  # type narrowing for mypy
            resolved_qty = float(notional) / price
        else:
            resolved_qty = float(qty)

        if resolved_qty <= 0:
            raise ValueError("Resolved order quantity must be positive.")

        order = MarketOrder(action=action, totalQuantity=resolved_qty)
        trade = ib.placeOrder(contract, order)

    return _trade_to_submit_dict(trade)


async def close_position(symbol: str) -> dict[str, Any]:
    """Submit the opposite-side market order to flatten ``symbol``.

    Raises ``ValueError`` when no open position is held for that symbol.
    """

    account_id = _require_account_id()
    cleaned_symbol = (symbol or "").strip().upper()
    if not cleaned_symbol:
        raise ValueError("symbol is required")

    async with get_client() as ib:
        positions = ib.positions() or []
        match = None
        for position in positions:
            if getattr(position, "account", "") != account_id:
                continue
            contract = getattr(position, "contract", None)
            pos_symbol = getattr(contract, "symbol", "") if contract is not None else ""
            if pos_symbol.upper() == cleaned_symbol and _to_float(getattr(position, "position", 0.0)) != 0:
                match = position
                break

        if match is None:
            raise ValueError(f"No open IBKR position for {cleaned_symbol!r}.")

        qty = _to_float(getattr(match, "position", 0.0))
        action = _SELL_ACTION if qty > 0 else _BUY_ACTION
        contract = _make_stock_contract(cleaned_symbol)
        order = MarketOrder(action=action, totalQuantity=abs(qty))
        trade = ib.placeOrder(contract, order)

    return _trade_to_submit_dict(trade)
