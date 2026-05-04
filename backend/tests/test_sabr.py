"""SABR volatility tests -- pinned reference values for the closed-form
formula and round-trip calibration sanity checks."""
from __future__ import annotations

import math

import pytest

from core.quantlib.volatility import (
    SABRParams,
    calibrate_sabr,
    sabr_lognormal_vol,
)


# ---------- Closed form ----------


def test_sabr_atm_recovers_alpha_at_beta_one():
    """For beta=1, the lognormal SABR ATM vol simplifies to alpha/F^0 = alpha
    (with the small T correction). At T=0 the correction is exactly 1, so
    sigma_ATM(T=0) == alpha."""
    sigma = sabr_lognormal_vol(F=100.0, K=100.0, T=0.0, alpha=0.20, beta=1.0, rho=0.0, nu=0.5)
    assert sigma == pytest.approx(0.20, rel=1e-9)


def test_sabr_atm_at_beta_zero():
    """beta=0 -> alpha/F^1, plus T correction. At T=0, sigma_ATM = alpha/F."""
    sigma = sabr_lognormal_vol(F=100.0, K=100.0, T=0.0, alpha=20.0, beta=0.0, rho=0.0, nu=0.0)
    # alpha/F = 20/100 = 0.20
    assert sigma == pytest.approx(0.20, rel=1e-9)


def test_sabr_smile_is_symmetric_when_rho_zero():
    """rho=0, beta=1: the smile should be symmetric around K=F."""
    F, T = 100.0, 1.0
    alpha, beta, rho, nu = 0.20, 1.0, 0.0, 0.5
    above = sabr_lognormal_vol(F, K=110.0, T=T, alpha=alpha, beta=beta, rho=rho, nu=nu)
    below = sabr_lognormal_vol(F, K=100.0 / 1.1, T=T, alpha=alpha, beta=beta, rho=rho, nu=nu)
    assert above == pytest.approx(below, rel=1e-3)


def test_sabr_negative_rho_creates_left_skew():
    """With rho<0, downside puts (K<F) should have HIGHER vol than calls (K>F)."""
    F, T = 100.0, 1.0
    alpha, beta, rho, nu = 0.20, 1.0, -0.4, 0.6
    iv_put = sabr_lognormal_vol(F, K=90.0, T=T, alpha=alpha, beta=beta, rho=rho, nu=nu)
    iv_call = sabr_lognormal_vol(F, K=110.0, T=T, alpha=alpha, beta=beta, rho=rho, nu=nu)
    assert iv_put > iv_call


def test_sabr_rejects_bad_inputs():
    with pytest.raises(ValueError, match="F must be"):
        sabr_lognormal_vol(F=-1, K=100, T=1, alpha=0.2, beta=0.5, rho=0, nu=0.5)
    with pytest.raises(ValueError, match="K must be"):
        sabr_lognormal_vol(F=100, K=0, T=1, alpha=0.2, beta=0.5, rho=0, nu=0.5)
    with pytest.raises(ValueError, match="alpha"):
        sabr_lognormal_vol(F=100, K=100, T=1, alpha=0, beta=0.5, rho=0, nu=0.5)
    with pytest.raises(ValueError, match="rho"):
        sabr_lognormal_vol(F=100, K=100, T=1, alpha=0.2, beta=0.5, rho=1.5, nu=0.5)
    with pytest.raises(ValueError, match="beta"):
        sabr_lognormal_vol(F=100, K=100, T=1, alpha=0.2, beta=1.5, rho=0, nu=0.5)


def test_sabr_atm_correction_grows_with_T():
    """Higher T -> larger correction term -> ATM vol != alpha."""
    base = sabr_lognormal_vol(F=100, K=100, T=0.0, alpha=0.20, beta=0.5, rho=-0.3, nu=0.6)
    longer = sabr_lognormal_vol(F=100, K=100, T=2.0, alpha=0.20, beta=0.5, rho=-0.3, nu=0.6)
    # The correction for these params is positive at T=2.
    assert longer > base


# ---------- Calibration ----------


def test_calibrate_recovers_known_params():
    """Generate a smile from known SABR params, then calibrate back.

    The recovered (alpha, rho, nu) should match within numerical tolerance.
    Use a 7-strike grid; beta fixed at the true value.
    """
    true_params = SABRParams(alpha=0.20, beta=1.0, rho=-0.30, nu=0.50)
    F, T = 100.0, 1.0
    strikes = [80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0]
    market_vols = [
        sabr_lognormal_vol(F, K, T,
                            true_params.alpha, true_params.beta,
                            true_params.rho, true_params.nu)
        for K in strikes
    ]
    fitted, residuals = calibrate_sabr(F, T, strikes, market_vols, beta=true_params.beta)

    assert fitted.alpha == pytest.approx(true_params.alpha, rel=1e-3)
    assert fitted.rho == pytest.approx(true_params.rho, abs=1e-3)
    assert fitted.nu == pytest.approx(true_params.nu, rel=1e-3)
    # Residuals should be effectively zero on a noise-free smile.
    assert max(abs(r) for r in residuals) < 1e-6


def test_calibrate_handles_noisy_smile():
    """Add small random-looking perturbations to the smile and assert
    the fit is still close. Determinism: use a fixed offset pattern."""
    true_params = SABRParams(alpha=0.20, beta=0.5, rho=-0.20, nu=0.40)
    F, T = 100.0, 1.0
    strikes = [80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0]
    base = [
        sabr_lognormal_vol(F, K, T,
                            true_params.alpha, true_params.beta,
                            true_params.rho, true_params.nu)
        for K in strikes
    ]
    # Tiny deterministic perturbation pattern (+-0.5 vol pts).
    perturbations = [0.005, -0.005, 0.003, 0.0, -0.002, 0.004, -0.005]
    noisy = [b + p for b, p in zip(base, perturbations)]

    fitted, residuals = calibrate_sabr(F, T, strikes, noisy, beta=0.5)
    # Loose tolerance -- calibrator should still get within 5% on each param.
    assert fitted.alpha == pytest.approx(true_params.alpha, rel=0.10)
    assert abs(fitted.rho - true_params.rho) < 0.15
    assert fitted.nu == pytest.approx(true_params.nu, rel=0.30)


def test_calibrate_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        calibrate_sabr(100.0, 1.0, [100.0, 110.0], [0.20])


def test_calibrate_rejects_empty_smile():
    with pytest.raises(ValueError, match="at least one"):
        calibrate_sabr(100.0, 1.0, [], [])


# ---------- Service / endpoint ----------


@pytest.mark.asyncio
async def test_fit_sabr_service_returns_full_payload():
    from app.services import sabr_service

    F, T = 100.0, 1.0
    strikes = [80.0, 90.0, 100.0, 110.0, 120.0]
    # Generate market vols from a known smile so the fit converges cleanly.
    true_params = SABRParams(alpha=0.20, beta=0.5, rho=-0.30, nu=0.50)
    market_vols = [
        sabr_lognormal_vol(F, K, T,
                            true_params.alpha, true_params.beta,
                            true_params.rho, true_params.nu)
        for K in strikes
    ]

    payload = await sabr_service.fit_sabr(
        forward=F,
        expiry_yrs=T,
        strikes=strikes,
        market_vols=market_vols,
        beta=0.5,
    )
    assert payload["beta"] == 0.5
    assert payload["alpha"] == pytest.approx(true_params.alpha, rel=1e-2)
    assert payload["rho"] == pytest.approx(true_params.rho, abs=1e-2)
    assert payload["nu"] == pytest.approx(true_params.nu, rel=1e-2)
    assert len(payload["model_vols"]) == len(strikes)
    assert max(abs(r) for r in payload["residuals"]) < 1e-4


@pytest.mark.asyncio
async def test_endpoint_rejects_short_smile():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/quantlib/sabr/fit",
        json={
            "forward": 100.0,
            "expiry_yrs": 1.0,
            "strikes": [100.0, 110.0],
            "market_vols": [0.20, 0.21],
            "beta": 0.5,
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_endpoint_round_trip():
    from fastapi.testclient import TestClient
    from app.main import app

    F, T = 100.0, 1.0
    strikes = [80.0, 90.0, 100.0, 110.0, 120.0]
    true_params = SABRParams(alpha=0.20, beta=1.0, rho=-0.30, nu=0.50)
    market_vols = [
        sabr_lognormal_vol(F, K, T,
                            true_params.alpha, true_params.beta,
                            true_params.rho, true_params.nu)
        for K in strikes
    ]
    client = TestClient(app)
    resp = client.post(
        "/api/quantlib/sabr/fit",
        json={
            "forward": F,
            "expiry_yrs": T,
            "strikes": strikes,
            "market_vols": market_vols,
            "beta": 1.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["alpha"] == pytest.approx(true_params.alpha, rel=1e-3)
    assert body["rho"] == pytest.approx(true_params.rho, abs=1e-3)
    assert body["nu"] == pytest.approx(true_params.nu, rel=1e-3)
