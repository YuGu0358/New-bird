"""SABR (Hagan 2002) lognormal-vol approximation + calibrator.

The SABR model parameterises a smile with four numbers:
- alpha: instantaneous volatility level
- beta: elasticity, in [0, 1]; 0 = normal, 1 = lognormal
- rho:  correlation between forward and vol, in (-1, 1)
- nu:   vol-of-vol, > 0

Hagan's small-time-to-expiry expansion gives a closed-form expression
for Black-Scholes implied volatility sigma(K; F, T). The formula has two
pieces: a leading factor that diverges to zero at the ATM strike (need
a Taylor series there) and a correction term in T.

We expose two callables:
- `sabr_lognormal_vol(F, K, T, alpha, beta, rho, nu)` -> sigma
- `calibrate_sabr(F, T, strikes, market_vols, *, beta=0.5)` -> (params, residuals)

`beta` is held fixed during calibration (the standard market convention --
beta is chosen to encode "model belief", e.g. 0 for rates / 0.5 for FX /
1 for equity-vol with sticky-strike). The optimizer fits {alpha, rho, nu} only.

Pure compute. No I/O. scipy is the only third-party dep, used for
least-squares solve.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np  # numpy is a transitive dep already (yfinance, scipy)
from scipy.optimize import least_squares


# Numerical safety: when |log(F/K)| is below this, we treat K as ATM and
# use the Taylor-series ATM formula. 1e-10 is well below the noise floor
# of any real strike grid.
_ATM_LOG_EPSILON = 1e-10


@dataclass(frozen=True)
class SABRParams:
    alpha: float
    beta: float
    rho: float
    nu: float


def sabr_lognormal_vol(
    F: float,
    K: float,
    T: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    """Hagan 2002 closed-form lognormal IV approximation.

    Inputs:
        F: forward (or spot for short tenors)
        K: strike
        T: time to expiry in years
        alpha, beta, rho, nu: SABR params

    Returns:
        Black-Scholes-implied volatility (annualised, lognormal).

    Raises:
        ValueError on degenerate inputs (F<=0, K<=0, T<0, alpha<=0, nu<0,
        |rho|>=1, beta<0 or beta>1).
    """
    if F <= 0:
        raise ValueError("F must be > 0")
    if K <= 0:
        raise ValueError("K must be > 0")
    if T < 0:
        raise ValueError("T must be >= 0")
    if alpha <= 0:
        raise ValueError("alpha must be > 0")
    if nu < 0:
        raise ValueError("nu must be >= 0")
    if not (-1.0 < rho < 1.0):
        raise ValueError("rho must satisfy -1 < rho < 1")
    if not (0.0 <= beta <= 1.0):
        raise ValueError("beta must be in [0, 1]")

    log_fk = math.log(F / K)
    one_minus_beta = 1.0 - beta
    fk_pow = (F * K) ** (one_minus_beta / 2.0)

    # Pre-asymptotic factor (1 + correction*T) -- same for ATM and non-ATM.
    correction = 1.0 + (
        ((one_minus_beta ** 2) / 24.0) * (alpha ** 2) / (fk_pow ** 2)
        + 0.25 * rho * beta * nu * alpha / fk_pow
        + ((2.0 - 3.0 * rho ** 2) / 24.0) * (nu ** 2)
    ) * T

    # Leading factor -- Taylor expansion at K=F to avoid division by zero.
    if abs(log_fk) < _ATM_LOG_EPSILON:
        # ATM case: sigma_ATM = (alpha / fk_pow) * correction
        return (alpha / fk_pow) * correction

    # Non-ATM general case.
    z = (nu / alpha) * fk_pow * log_fk
    # x(z) = log((sqrt(1 - 2*rho*z + z^2) + z - rho)/(1 - rho))
    sqrt_term = math.sqrt(1.0 - 2.0 * rho * z + z ** 2)
    x_z = math.log((sqrt_term + z - rho) / (1.0 - rho))

    if abs(x_z) < _ATM_LOG_EPSILON:
        # Defensive: if x(z) collapses to zero numerically, treat as ATM.
        return (alpha / fk_pow) * correction

    log_fk_sq = log_fk ** 2
    leading_denom = 1.0 + (
        (one_minus_beta ** 2 / 24.0) * log_fk_sq
        + (one_minus_beta ** 4 / 1920.0) * log_fk_sq ** 2
    )

    return (alpha / fk_pow) / leading_denom * (z / x_z) * correction


def calibrate_sabr(
    F: float,
    T: float,
    strikes: Sequence[float],
    market_vols: Sequence[float],
    *,
    beta: float = 0.5,
    initial_guess: tuple[float, float, float] | None = None,
) -> tuple[SABRParams, list[float]]:
    """Least-squares fit of {alpha, rho, nu} to a market smile.

    `beta` is held fixed (market convention). Returns the best-fit
    parameters and the per-strike residuals (model_iv - market_iv).

    Initial guess defaults to (alpha=ATM_market_vol, rho=0, nu=0.5) which
    converges robustly for typical equity-options smiles. Callers with
    domain knowledge can override.

    Raises:
        ValueError if strikes / market_vols length mismatch or empty.
    """
    if len(strikes) != len(market_vols):
        raise ValueError("strikes and market_vols must be same length")
    if not strikes:
        raise ValueError("at least one (strike, vol) pair required")
    if not (0.0 <= beta <= 1.0):
        raise ValueError("beta must be in [0, 1]")

    strikes_arr = np.asarray(strikes, dtype=float)
    vols_arr = np.asarray(market_vols, dtype=float)

    if initial_guess is None:
        # Pick the strike closest to forward as the ATM proxy for alpha_0.
        atm_idx = int(np.argmin(np.abs(strikes_arr - F)))
        atm_vol = float(vols_arr[atm_idx])
        # Hagan ATM ~= alpha / F^(1-beta); invert for alpha_0.
        alpha0 = atm_vol * (F ** (1.0 - beta))
        initial_guess = (alpha0, 0.0, 0.5)

    def residuals(theta: np.ndarray) -> np.ndarray:
        alpha, rho, nu = theta
        out = np.empty(len(strikes_arr), dtype=float)
        for i, K in enumerate(strikes_arr):
            try:
                model_iv = sabr_lognormal_vol(
                    F, float(K), T, alpha, beta, rho, nu
                )
            except ValueError:
                # Optimizer occasionally probes invalid params; return a
                # large penalty so it backs off rather than crashes.
                model_iv = 1e6
            out[i] = model_iv - vols_arr[i]
        return out

    bounds = (
        # alpha > 0, rho in (-0.999, 0.999), nu > 0
        [1e-6, -0.999, 1e-6],
        [10.0, 0.999, 10.0],
    )
    result = least_squares(
        residuals,
        x0=np.asarray(initial_guess, dtype=float),
        bounds=bounds,
        max_nfev=200,
    )
    alpha_fit, rho_fit, nu_fit = result.x
    params = SABRParams(
        alpha=float(alpha_fit),
        beta=float(beta),
        rho=float(rho_fit),
        nu=float(nu_fit),
    )
    return params, [float(r) for r in result.fun]
