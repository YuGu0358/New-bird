"""Seed list of macro indicators.

Borrowed from Tradewell's 6-indicator ensemble + supporting series. Every
indicator has:
  - code: the FRED series id (or our own derivative key)
  - source: "FRED" or "DERIVED" (computed from another series)
  - category: groups the cards on the dashboard
  - is_ensemble_core: 6 of these light up the "ensemble health" KPI
  - default_thresholds: drives the signal-level dot
  - i18n_key: i18n key for the localized display name (frontend resolves)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class IndicatorSeed:
    code: str
    category: Literal["inflation", "liquidity", "rates", "credit", "growth", "fx", "vol"]
    source: Literal["FRED", "DERIVED"]
    base_series: str | None = None  # for DERIVED rows; FRED series to read first
    derive_kind: str | None = None  # "yoy_pct" or None
    is_ensemble_core: bool = False
    default_thresholds: dict[str, Any] = field(default_factory=dict)
    i18n_key: str = ""  # e.g. "macro.indicators.cpi_yoy"
    description_key: str = ""  # e.g. "macro.indicators.cpi_yoy_desc"
    unit: str = ""  # display unit suffix, e.g. "%" or "$M"


# 16-indicator seed — six are flagged is_ensemble_core for the dashboard ensemble KPI.
SEED_INDICATORS: tuple[IndicatorSeed, ...] = (
    # ----- Inflation
    IndicatorSeed(
        code="CPIAUCSL_YOY",
        category="inflation",
        source="DERIVED",
        base_series="CPIAUCSL",
        derive_kind="yoy_pct",
        is_ensemble_core=False,
        default_thresholds={"ok_max": 2.5, "warn_max": 4.0, "danger_max": 6.0, "direction": "higher_is_worse"},
        i18n_key="macro.indicators.cpi_yoy",
        description_key="macro.indicators.cpi_yoy_desc",
        unit="%",
    ),
    IndicatorSeed(
        code="PCEPI_YOY",
        category="inflation",
        source="DERIVED",
        base_series="PCEPI",
        derive_kind="yoy_pct",
        is_ensemble_core=False,
        default_thresholds={"ok_max": 2.0, "warn_max": 3.0, "danger_max": 5.0, "direction": "higher_is_worse"},
        i18n_key="macro.indicators.pce_yoy",
        description_key="macro.indicators.pce_yoy_desc",
        unit="%",
    ),
    # ----- Liquidity
    IndicatorSeed(
        code="WALCL",
        category="liquidity",
        source="FRED",
        default_thresholds={"direction": "informational"},
        i18n_key="macro.indicators.walcl",
        description_key="macro.indicators.walcl_desc",
        unit="$M",
    ),
    IndicatorSeed(
        code="RRPONTSYD",
        category="liquidity",
        source="FRED",
        default_thresholds={"direction": "informational"},
        i18n_key="macro.indicators.rrp",
        description_key="macro.indicators.rrp_desc",
        unit="$B",
    ),
    IndicatorSeed(
        code="WTREGEN",
        category="liquidity",
        source="FRED",
        default_thresholds={"direction": "informational"},
        i18n_key="macro.indicators.tga",
        description_key="macro.indicators.tga_desc",
        unit="$B",
    ),
    # ----- Rates & curve
    IndicatorSeed(
        code="DGS10",
        category="rates",
        source="FRED",
        default_thresholds={"ok_max": 4.5, "warn_max": 5.5, "danger_max": 7.0, "direction": "higher_is_worse"},
        i18n_key="macro.indicators.dgs10",
        description_key="macro.indicators.dgs10_desc",
        unit="%",
    ),
    IndicatorSeed(
        code="DGS2",
        category="rates",
        source="FRED",
        default_thresholds={"direction": "informational"},
        i18n_key="macro.indicators.dgs2",
        description_key="macro.indicators.dgs2_desc",
        unit="%",
    ),
    IndicatorSeed(
        code="T10Y2Y",
        category="rates",
        source="FRED",
        is_ensemble_core=True,  # yield-curve inversion
        default_thresholds={"ok_max": 999.0, "warn_max": 0.5, "danger_max": 0.0, "direction": "higher_is_better"},
        i18n_key="macro.indicators.t10y2y",
        description_key="macro.indicators.t10y2y_desc",
        unit="bps",
    ),
    # ----- Credit
    IndicatorSeed(
        code="BAMLH0A0HYM2",
        category="credit",
        source="FRED",
        is_ensemble_core=True,  # HY OAS — credit stress
        default_thresholds={"ok_max": 4.0, "warn_max": 5.5, "danger_max": 7.0, "direction": "higher_is_worse"},
        i18n_key="macro.indicators.hy_oas",
        description_key="macro.indicators.hy_oas_desc",
        unit="%",
    ),
    # ----- Growth / recession
    IndicatorSeed(
        code="RECPROUSM156N",
        category="growth",
        source="FRED",
        is_ensemble_core=True,  # NY Fed recession probability
        default_thresholds={"ok_max": 15.0, "warn_max": 30.0, "danger_max": 50.0, "direction": "higher_is_worse"},
        i18n_key="macro.indicators.rec_prob",
        description_key="macro.indicators.rec_prob_desc",
        unit="%",
    ),
    # ----- FX / dollar
    IndicatorSeed(
        code="DTWEXBGS",
        category="fx",
        source="FRED",
        default_thresholds={"direction": "informational"},
        i18n_key="macro.indicators.dxy",
        description_key="macro.indicators.dxy_desc",
        unit="",
    ),
    # ----- Volatility / sentiment
    IndicatorSeed(
        code="VIXCLS",
        category="vol",
        source="FRED",
        is_ensemble_core=True,  # vol regime proxy
        default_thresholds={"ok_max": 18.0, "warn_max": 25.0, "danger_max": 35.0, "direction": "higher_is_worse"},
        i18n_key="macro.indicators.vix",
        description_key="macro.indicators.vix_desc",
        unit="",
    ),
)


CATEGORY_ORDER: tuple[str, ...] = ("inflation", "liquidity", "rates", "credit", "growth", "fx", "vol")
