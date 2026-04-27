"""Options-chain analytics service — yfinance + black-scholes + GEX rollup.

The yfinance option_chain API gives us strike, lastPrice, bid/ask, volume,
openInterest, impliedVolatility, but no gamma. We compute gamma (and re-stamp
delta) via Black-Scholes so the GEX engine has consistent inputs.

Why not the QuantLib router? The /api/quantlib/option/* endpoints are for
single-option pricing; this service is for whole-chain GEX/wall analytics.
Two different products, two different code paths.

Two distinct caches:
- `_chain_cache` — built OptionContract list keyed by (ticker, max_expiries).
  Shared by both `get_gex_summary()` and `get_expiry_focus()` so the second
  call doesn't refetch yfinance.
- `_summary_cache` — final GEX summary payloads keyed the same way.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries
from core.options_chain import (
    OptionContract,
    black_scholes_greeks,
    focus_expiry,
    scan_pinning,
    summarize_chain,
)

logger = logging.getLogger(__name__)

_CHAIN_CACHE_TTL = timedelta(minutes=15)
# (ticker, max_expiries) → (cached_at, {spot, contracts, expiries})
_chain_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
# (ticker, max_expiries) → (cached_at, summary_payload)
_summary_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}

# How many expiries to scan; deeper chains slow yfinance dramatically.
DEFAULT_MAX_EXPIRIES = 6
DEFAULT_RISK_FREE = 0.04


def _build_contracts_blocking(ticker: str, max_expiries: int, r: float) -> dict[str, Any]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        spot = float(t.fast_info.last_price or 0)
    except Exception:  # noqa: BLE001
        spot = 0.0
    if spot <= 0:
        try:
            hist = t.history(period="5d", auto_adjust=False)
            if not hist.empty:
                spot = float(hist["Close"].iloc[-1])
        except Exception:  # noqa: BLE001
            spot = 0.0

    # Average daily $-volume over the last ~21 trading days. Used by
    # scan_pinning() to compute the GEX/ADV pressure component. Optional:
    # if the history call fails the friday-scan just skips that one
    # +10-point lever in the pinning score.
    adv_dollar: float | None = None
    try:
        hist_1mo = t.history(period="1mo", auto_adjust=False)
        if not hist_1mo.empty and "Volume" in hist_1mo.columns:
            avg_vol = float(hist_1mo["Volume"].dropna().mean() or 0)
            if avg_vol > 0 and spot > 0:
                adv_dollar = avg_vol * spot
    except Exception:  # noqa: BLE001
        adv_dollar = None

    expiry_strings = list(t.options or [])[:max_expiries]
    contracts: list[OptionContract] = []
    today = date.today()

    for exp_iso in expiry_strings:
        try:
            chain = t.option_chain(exp_iso)
        except Exception as exc:  # noqa: BLE001
            logger.debug("option_chain(%s, %s) failed: %s", ticker, exp_iso, exc)
            continue
        try:
            expiry_d = date.fromisoformat(exp_iso)
        except ValueError:
            continue

        dte_days = max((expiry_d - today).days, 1)
        t_yrs = dte_days / 365.0

        for side, frame in (("C", chain.calls), ("P", chain.puts)):
            for _, row in frame.iterrows():
                try:
                    strike = float(row.get("strike") or 0)
                    if strike <= 0:
                        continue
                    iv = row.get("impliedVolatility")
                    iv_f = float(iv) if iv is not None and not (iv != iv) else None
                    oi = int(row.get("openInterest") or 0)
                    vol = int(row.get("volume") or 0)
                    last = row.get("lastPrice")
                    last_f = float(last) if last is not None and not (last != last) else None
                    bid = row.get("bid")
                    bid_f = float(bid) if bid is not None and not (bid != bid) else None
                    ask = row.get("ask")
                    ask_f = float(ask) if ask is not None and not (ask != ask) else None

                    greeks = None
                    if iv_f and iv_f > 0 and spot > 0:
                        greeks = black_scholes_greeks(
                            spot=spot,
                            strike=strike,
                            time_to_expiry_yrs=t_yrs,
                            iv=iv_f,
                            r=r,
                            option_type=side,
                        )

                    contracts.append(
                        OptionContract(
                            expiry=expiry_d,
                            strike=strike,
                            option_type=side,
                            open_interest=oi,
                            volume=vol,
                            iv=iv_f,
                            delta=greeks.delta if greeks else None,
                            gamma=greeks.gamma if greeks else None,
                            last=last_f,
                            bid=bid_f,
                            ask=ask_f,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 — skip malformed rows
                    logger.debug("option row parse failed for %s %s: %s", ticker, exp_iso, exc)
                    continue

    return {
        "spot": spot,
        "contracts": contracts,
        "expiries": expiry_strings,
        "adv_dollar": adv_dollar,
    }


async def _get_chain(
    ticker: str,
    *,
    max_expiries: int,
    risk_free: float,
    force: bool,
) -> dict[str, Any]:
    """Fetch (and cache) the raw chain — used by both gex and focus endpoints."""
    normalized = ticker.upper()
    cache_key = f"{normalized}:{max_expiries}"
    now = datetime.now(timezone.utc)
    cached = _chain_cache.get(cache_key)
    if not force and cached and now - cached[0] <= _CHAIN_CACHE_TTL:
        return cached[1]
    raw = await run_sync_with_retries(
        _build_contracts_blocking, normalized, max_expiries, risk_free
    )
    _chain_cache[cache_key] = (now, raw)
    return raw


async def get_gex_summary(
    ticker: str,
    *,
    max_expiries: int = DEFAULT_MAX_EXPIRIES,
    risk_free: float = DEFAULT_RISK_FREE,
    force: bool = False,
) -> dict[str, Any]:
    """Pull the chain and return the GEX rollup payload."""
    normalized = ticker.upper()
    cache_key = f"{normalized}:{max_expiries}"
    now = datetime.now(timezone.utc)
    cached = _summary_cache.get(cache_key)
    if not force and cached and now - cached[0] <= _CHAIN_CACHE_TTL:
        return cached[1]

    raw = await _get_chain(normalized, max_expiries=max_expiries, risk_free=risk_free, force=force)
    spot = float(raw.get("spot") or 0)
    contracts = raw.get("contracts") or []

    if not contracts or spot <= 0:
        payload = {
            "ticker": normalized,
            "spot": spot,
            "call_wall": None,
            "put_wall": None,
            "zero_gamma": None,
            "max_pain": None,
            "total_gex": 0.0,
            "call_gex_total": 0.0,
            "put_gex_total": 0.0,
            "by_strike": [],
            "by_expiry": [],
            "expiries": raw.get("expiries") or [],
            "generated_at": now,
        }
        _summary_cache[cache_key] = (now, payload)
        return payload

    summary = summarize_chain(ticker=normalized, spot=spot, contracts=contracts)
    payload = {
        **(asdict(summary) if summary else {}),
        "expiries": raw.get("expiries") or [],
        "generated_at": now,
    }
    _summary_cache[cache_key] = (now, payload)
    return payload


async def get_friday_scan(
    ticker: str,
    expiry_iso: str | None = None,
    *,
    max_expiries: int = DEFAULT_MAX_EXPIRIES,
    risk_free: float = DEFAULT_RISK_FREE,
) -> dict[str, Any] | None:
    """Pinning-probability scan for one expiry.

    If `expiry_iso` is None we pick the next Friday found in the chain (or
    the next expiry within 7 days, whichever comes first). Returns the
    score 0..100 + verdict + human-readable reasons.
    """
    normalized = ticker.upper()
    raw = await _get_chain(
        normalized, max_expiries=max_expiries, risk_free=risk_free, force=False
    )
    spot = float(raw.get("spot") or 0)
    contracts = raw.get("contracts") or []
    adv_dollar = raw.get("adv_dollar")
    expiry_strings = raw.get("expiries") or []
    if not contracts or spot <= 0:
        return None

    today = date.today()
    target: date | None = None
    if expiry_iso:
        try:
            target = date.fromisoformat(expiry_iso)
        except ValueError as exc:
            raise ValueError(f"Invalid expiry date: {expiry_iso}") from exc
    else:
        # Auto-pick: next Friday in the chain, else the nearest expiry.
        candidates: list[date] = []
        for s in expiry_strings:
            try:
                candidates.append(date.fromisoformat(s))
            except ValueError:
                continue
        candidates.sort()
        fridays = [d for d in candidates if d.weekday() == 4 and d >= today]
        if fridays:
            target = fridays[0]
        elif candidates:
            target = candidates[0]
    if target is None:
        return None

    scan = scan_pinning(
        ticker=normalized,
        spot=spot,
        contracts=contracts,
        target_expiry=target,
        today=today,
        adv_dollar=adv_dollar,
    )
    return {
        "ticker": scan.ticker,
        "spot": scan.spot,
        "target_expiry": scan.target_expiry,
        "dte_calendar": scan.dte_calendar,
        "has_data": scan.has_data,
        "atm_iv": scan.atm_iv,
        "expected_move": scan.expected_move,
        "expected_low": scan.expected_low,
        "expected_high": scan.expected_high,
        "contract_count": scan.contract_count,
        "total_chain_oi": scan.total_chain_oi,
        "median_strike_oi": scan.median_strike_oi,
        "total_friday_gex": scan.total_friday_gex,
        "friday_gex_pressure_pct": scan.friday_gex_pressure_pct,
        "adv_dollar": scan.adv_dollar,
        "call_wall": _wall_dict(scan.call_wall),
        "put_wall": _wall_dict(scan.put_wall),
        "max_pain": scan.max_pain,
        "put_call_oi_ratio": scan.put_call_oi_ratio,
        "pinning_score": scan.pinning_score,
        "verdict": scan.verdict,
        "reasons": list(scan.reasons),
        "suggested_short_call": scan.suggested_short_call,
        "suggested_short_put": scan.suggested_short_put,
        "breakeven_low": scan.breakeven_low,
        "breakeven_high": scan.breakeven_high,
        "generated_at": datetime.now(timezone.utc),
    }


def _wall_dict(w: Any) -> dict[str, Any]:
    return {
        "strike": w.strike,
        "oi": w.oi,
        "concentration_pct": w.concentration_pct,
        "salience_mult": w.salience_mult,
        "pressure_pct": w.pressure_pct,
        "distance_pct": w.distance_pct,
        "gex_dollar": w.gex_dollar,
    }


async def get_expiry_focus(
    ticker: str,
    expiry_iso: str,
    *,
    max_expiries: int = DEFAULT_MAX_EXPIRIES,
    risk_free: float = DEFAULT_RISK_FREE,
    top_n: int = 5,
) -> dict[str, Any] | None:
    """Per-expiry OI focus (top resistance / support strikes + expected move)."""
    normalized = ticker.upper()
    try:
        target = date.fromisoformat(expiry_iso)
    except ValueError as exc:
        raise ValueError(f"Invalid expiry date: {expiry_iso}") from exc

    raw = await _get_chain(
        normalized,
        max_expiries=max_expiries,
        risk_free=risk_free,
        force=False,
    )
    spot = float(raw.get("spot") or 0)
    contracts = raw.get("contracts") or []
    if not contracts or spot <= 0:
        return None

    focus = focus_expiry(
        ticker=normalized,
        spot=spot,
        contracts=contracts,
        expiry=target,
        top_n=top_n,
    )
    if focus is None:
        return None

    return {
        "ticker": focus.ticker,
        "expiry": focus.expiry,
        "dte": focus.dte,
        "spot": focus.spot,
        "atm_iv": focus.atm_iv,
        "expected_move": focus.expected_move,
        "expected_low": focus.expected_low,
        "expected_high": focus.expected_high,
        "max_pain": focus.max_pain,
        "total_call_oi": focus.total_call_oi,
        "total_put_oi": focus.total_put_oi,
        "put_call_oi_ratio": focus.put_call_oi_ratio,
        "top_call_strikes": [asdict(s) for s in focus.top_call_strikes],
        "top_put_strikes": [asdict(s) for s in focus.top_put_strikes],
        "generated_at": datetime.now(timezone.utc),
    }
