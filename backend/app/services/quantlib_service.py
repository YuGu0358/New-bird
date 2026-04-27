"""Thin service wrapper — adapts API request models to core/quantlib calls.

Catches QuantLibError + ValueError and re-raises as QuantLibInputError
the router can map to HTTP 422.
"""
from __future__ import annotations

from datetime import date as DateType
from typing import Any

from core.quantlib import (
    BondParams,
    OptionParams,
    QuantLibError,
    bond_risk_metrics,
    bond_yield_to_maturity,
    greeks_european_bs,
    historical_var,
    parametric_var,
    price_american_binomial,
    price_european_bs,
)


class QuantLibInputError(ValueError):
    """User-supplied inputs failed validation. Maps to HTTP 422."""


def _to_date(value: Any) -> DateType:
    if isinstance(value, DateType):
        return value
    if isinstance(value, str):
        return DateType.fromisoformat(value)
    raise QuantLibInputError(f"Cannot parse date: {value!r}")


def _coerce_option_params(payload: dict[str, Any]) -> OptionParams:
    try:
        return OptionParams(
            spot=float(payload["spot"]),
            strike=float(payload["strike"]),
            rate=float(payload["rate"]),
            dividend=float(payload.get("dividend", 0.0)),
            volatility=float(payload["volatility"]),
            valuation=_to_date(payload["valuation"]),
            expiry=_to_date(payload["expiry"]),
            right=str(payload.get("right", "call")).lower(),  # type: ignore[arg-type]
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise QuantLibInputError(str(exc)) from exc


def _coerce_bond_params(payload: dict[str, Any]) -> BondParams:
    try:
        return BondParams(
            settlement=_to_date(payload["settlement"]),
            maturity=_to_date(payload["maturity"]),
            coupon_rate=float(payload["coupon_rate"]),
            frequency=int(payload.get("frequency", 2)),
            face=float(payload.get("face", 100.0)),
            clean_price=float(payload.get("clean_price", 100.0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise QuantLibInputError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Public service surface
# ---------------------------------------------------------------------------


def option_price(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_option_params(payload)
    style = str(payload.get("style", "european")).lower()
    try:
        if style == "european":
            price = price_european_bs(params)
        elif style == "american":
            steps = int(payload.get("steps", 200))
            price = price_american_binomial(params, steps=steps)
        else:
            raise QuantLibInputError(f"Unknown exercise style: {style!r}")
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {
        "style": style,
        "right": params.right,
        "price": price,
        "days_to_expiry": params.days_to_expiry(),
    }


def option_greeks(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_option_params(payload)
    try:
        g = greeks_european_bs(params)
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {
        "delta": g.delta,
        "gamma": g.gamma,
        "vega": g.vega,
        "theta": g.theta,
        "rho": g.rho,
    }


def bond_yield(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_bond_params(payload)
    try:
        ytm = bond_yield_to_maturity(params)
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {"yield_to_maturity": ytm}


def bond_risk(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_bond_params(payload)
    try:
        metrics = bond_risk_metrics(params)
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {
        "yield_to_maturity": metrics.yield_to_maturity,
        "macaulay_duration": metrics.macaulay_duration,
        "modified_duration": metrics.modified_duration,
        "convexity": metrics.convexity,
    }


def value_at_risk(payload: dict[str, Any]) -> dict[str, Any]:
    method = str(payload.get("method", "parametric")).lower()
    notional = float(payload.get("notional", 0.0))
    confidence = float(payload.get("confidence", 0.95))
    horizon_days = int(payload.get("horizon_days", 1))

    if method == "parametric":
        result = parametric_var(
            notional=notional,
            mean_return=float(payload.get("mean_return", 0.0)),
            std_return=float(payload.get("std_return", 0.0)),
            confidence=confidence,
            horizon_days=horizon_days,
        )
    elif method == "historical":
        result = historical_var(
            notional=notional,
            returns=list(payload.get("returns") or []),
            confidence=confidence,
            horizon_days=horizon_days,
        )
    else:
        raise QuantLibInputError(f"Unknown VaR method: {method!r}")

    return {
        "var": result.var,
        "cvar": result.cvar,
        "confidence": result.confidence,
        "horizon_days": result.horizon_days,
        "method": result.method,
    }
