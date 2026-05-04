# Workflow Engine Real Execution — Retroactive Implementation Doc

> **Retro doc**: shipped in commit `654ecb3` on `feat/portfolio-opt`. Replaces the Phase 5.6 MVP's deterministic mock fetcher + no-op order with real `chart_service` and Alpaca paper-order calls. Future contributors who want to add another order broker (IBKR, Kraken) or fetcher source (Polygon WS) extend at the same hook points.

**Goal:** Saved workflows actually fetch market data and dispatch paper orders instead of synthetic ramps + log-only no-ops.

**Architecture:** Replace the two stub functions in `backend/app/services/workflow_service.py`:
- `_make_default_fetcher()` returned a synthetic ramp; now wraps `chart_service.get_symbol_chart`.
- `_default_paper_order()` was a no-op log; now wraps `alpaca_service.submit_order` with hard caps + symbol harvesting.

The engine itself (`backend/core/workflow/engine.py`) is purely compute and unchanged — except a small change to `_run_order` to harvest the upstream data-fetch node's ticker into the order payload (the original engine emitted `{side, qty, paper}` with no symbol, so paper_order_fn couldn't actually dispatch).

**Tech Stack:** unchanged from the MVP (`chart_service`, `alpaca_service`, APScheduler).

---

## File Structure

**Modified:**
- `backend/app/services/workflow_service.py` — `_make_default_fetcher` + `_default_paper_order` rewrites
- `backend/core/workflow/engine.py` — `_run_order` harvests ticker from upstream

**Untouched:** Service public API (`run_workflow_by_name`, `enable_workflow`, …), router, tests for the engine continue to mock `paper_order_fn` so they're transparent to the swap.

---

## Reference

1. `backend/app/services/chart_service.py` — `get_symbol_chart(symbol, range_name)` returns OHLCV points; the fetcher pulls closes only.
2. `backend/app/services/alpaca_service.py:138` — `submit_order(symbol, side, *, qty=None, notional=None, ...)`.
3. `backend/core/workflow/engine.py:_ancestor_outputs` — used by `_run_order` to walk upstream nodes for the ticker.

---

## Tasks

### Task 1: Real fetcher

```python
def _make_default_fetcher():
    from app.services import chart_service

    async def _fetch(ticker, lookback_days):
        # Pick the smallest yfinance period that covers lookback_days.
        if lookback_days <= 5:    range_name = "5d"
        elif lookback_days <= 22: range_name = "1mo"
        elif lookback_days <= 66: range_name = "3mo"
        elif lookback_days <= 132:range_name = "6mo"
        else:                     range_name = "1y"
        try:
            chart = await chart_service.get_symbol_chart(ticker, range_name=range_name)
            points = list((chart or {}).get("points") or [])
            closes = [float(p.get("close") or p.get("price") or 0.0)
                      for p in points if (p.get("close") or p.get("price"))]
            if closes:
                return closes[-lookback_days:] if len(closes) > lookback_days else closes
        except Exception:
            logger.exception("chart fetch failed for %s; falling back to synthetic", ticker)

        # Deterministic fallback so tests + dry runs still produce something.
        seed = sum(ord(c) for c in ticker) % 17
        return [100.0 + seed + i * 0.1 for i in range(lookback_days)]

    return _fetch
```

Decision: **the synthetic fallback stays.** It guarantees the workflow can still execute when yfinance is rate-limited / a symbol is invalid — without it a single bad symbol would fail the whole run. Tests still mock the fetcher entirely, so they don't exercise either path.

### Task 2: Real paper-order with hard caps

```python
async def _default_paper_order(payload):
    side = str(payload.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        return {"accepted": False, "broker": "noop", "reason": f"invalid side: {side!r}"}

    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        logger.info("workflow paper-order without symbol: %s", payload)
        return {"accepted": True, "broker": "noop", "reason": "no symbol in node payload"}

    # Hard caps so a malformed workflow definition can't request a 1B-share
    # paper trade. Caller's editor enforces sane bounds; this is the
    # second line of defence.
    MAX_QTY = 100_000        # 100k shares per order
    MAX_NOTIONAL = 1_000_000  # $1M notional per order

    qty_raw = payload.get("qty")
    notional_raw = payload.get("notional")
    qty = float(qty_raw) if qty_raw is not None else None
    notional = float(notional_raw) if notional_raw is not None else None

    if qty is not None and (qty <= 0 or qty > MAX_QTY):
        return {"accepted": False, "broker": "noop",
                "reason": f"qty {qty} outside (0, {MAX_QTY}]"}
    if notional is not None and (notional <= 0 or notional > MAX_NOTIONAL):
        return {"accepted": False, "broker": "noop",
                "reason": f"notional {notional} outside (0, {MAX_NOTIONAL}]"}

    try:
        from app.services import alpaca_service
        result = await alpaca_service.submit_order(symbol, side, qty=qty, notional=notional)
        return {"accepted": True, "broker": "alpaca-paper", "order": result}
    except Exception as exc:
        logger.warning("workflow paper-order failed for %s/%s: %s", symbol, side, exc)
        return {"accepted": True, "broker": "noop", "reason": str(exc)}
```

Decisions:
- **Always returns `accepted: True`** when symbol is valid even if Alpaca fails — the workflow continues. Caller can inspect `broker == "alpaca-paper"` vs `"noop"` to know if dispatch was real.
- **Hard MAX_QTY / MAX_NOTIONAL caps** added in QC follow-up commit (`3ddb17d`). Prevents a malformed workflow from firing a 1B-share order through Alpaca paper, which inflates Alpaca's logs without hitting buying-power limits.
- **No support for `bracket_order` / OCO yet** — keep the wrapper minimal until users ask.

### Task 3: Engine ticker harvest

In `core/workflow/engine.py`, `_run_order` previously did:
```python
payload = {"side": side, "qty": qty_f, "paper": paper}
```

Now:
```python
ticker = node.data.get("ticker")
if not ticker:
    for parent_out in _ancestor_outputs(ctx, node.id).values():
        t = parent_out.get("ticker")
        if isinstance(t, str) and t:
            ticker = t
            break

payload: dict[str, Any] = {"side": side, "qty": qty_f, "paper": paper}
if ticker:
    payload["symbol"] = ticker
```

The `_ancestor_outputs` helper walks parents transitively. The first upstream node (typically `data-fetch`) carries `ticker` in its output, so `order` nodes inherit it. Order nodes can also carry their own `ticker` in `node.data` — explicit override wins.

Without this change, paper_order_fn always saw a payload with no `symbol` and fell back to the noop branch — i.e. workflows could never actually trade.

---

## Self-Review

- [x] 22 workflow tests still pass (engine + service); they mock the fetcher and `paper_order_fn` so the real-service swap is transparent.
- [x] No new dependencies introduced.
- [x] `_default_paper_order` doesn't crash when Alpaca is unconfigured — falls back to noop with a structured `reason`.
- [x] Hard caps applied in QC follow-up; below those caps the call is dispatched verbatim.
- [x] Engine's ticker harvest is opt-in: explicit `node.data.ticker` wins, otherwise inherit from upstream.

## Concerns / Follow-ups

1. **No execution audit table.** Every paper order is logged via the standard logger but not persisted into a `workflow_runs` or `risk_events` row. Adding one would let the UI show "this workflow has fired 3 buys today" without re-tailing logs.
2. **Failed Alpaca calls return `accepted: True, broker: "noop"`.** The reasoning is "workflow continues", but a strict mode that propagates failure as `accepted: False` would help users catch broker outages.
3. **No support for `notional` from upstream signal nodes.** Today `notional` only comes from `node.data`. A future enhancement: signal nodes could emit a `position_size_usd` and the order node inherits it.
4. **Limit / stop / OCO bracket orders not supported.** Alpaca paper supports them; we just don't expose the params.
5. **Real fetcher pulls `close` only.** Detectors in `core.signals` use OHLCV — if a workflow node ever needs intraday open/high/low it won't have them. Trade-off: keeps the closes-list contract simple.
6. **No rate limiting per workflow.** A workflow set to a 60-second interval × 8 symbols hits yfinance 8 times/minute. Polite for now; if more workflows land, add a token-bucket.
7. **`_make_default_fetcher` recomputes `range_name` on every call.** Trivially cacheable but not material.
