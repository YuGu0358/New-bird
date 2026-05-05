"""WorldQuant Alpha 101 seed factors.

A curated subset of the public Alpha 101 catalogue, transliterated into our
operator vocabulary. They serve as the initial population for genetic-
programming style factor mining and exercise a representative slice of the
operator library.

Each entry is a serialised :class:`FactorNode` string  parse them with
:func:`get_seed_population`.
"""

from __future__ import annotations

from typing import List

from .ast import FactorNode, parse


SEEDS: List[str] = [
    # Alpha #1 — argmax over a sign-conditioned series
    "rank(ts_argmax(power(if_else(returns,ts_std(returns,20),close),2),5))",
    # Alpha #2 — log-volume vs intraday return correlation
    "neg(correlation(rank(delta(log(volume),2)),rank(div(sub(close,open),open)),6))",
    # Alpha #3 — open vs volume rank correlation
    "neg(correlation(rank(open),rank(volume),10))",
    # Alpha #4 — time-series rank of low
    "neg(ts_rank(rank(low),9))",
    # Alpha #5 — vwap mean reversion rank
    "mul(rank(sub(open,div(ts_sum(vwap,10),10))),neg(abs(rank(sub(close,vwap)))))",
    # Alpha #6 — open / volume correlation
    "neg(correlation(open,volume,10))",
    # Alpha #7 — adv-conditioned momentum
    "if_else(sub(20,volume),mul(neg(ts_rank(abs(delta(close,7)),60)),sign(delta(close,7))),neg(1))",
    # Alpha #8 — sum-of-open vs sum-of-returns lagged delta
    "neg(rank(sub(mul(ts_sum(open,5),ts_sum(returns,5)),delay(mul(ts_sum(open,5),ts_sum(returns,5)),10))))",
    # Alpha #9 — conditional momentum with delta(close)
    "if_else(sub(ts_min(delta(close,1),5),0),delta(close,1),if_else(sub(0,ts_max(delta(close,1),5)),delta(close,1),neg(delta(close,1))))",
    # Alpha #12 — sign of volume delta times negative price delta
    "mul(sign(delta(volume,1)),neg(delta(close,1)))",
    # Alpha #13 — cross-sectional covariance of close vs volume ranks
    "neg(rank(covariance(rank(close),rank(volume),5)))",
    # Alpha #15 — sum of correlations of high/volume ranks
    "neg(ts_sum(rank(correlation(rank(high),rank(volume),3)),3))",
    # Alpha #17 — joint rank of ts_rank(close), delta-of-delta, and ts_rank(volume/adv)
    "neg(mul(mul(rank(ts_rank(close,10)),rank(delta(delta(close,1),1))),rank(ts_rank(div(volume,ts_mean(volume,20)),5))))",
    # Alpha #21 — moving-average regime classifier
    "if_else(sub(add(div(ts_sum(close,8),8),ts_std(close,8)),div(ts_sum(close,2),2)),neg(1),if_else(sub(div(ts_sum(close,2),2),sub(div(ts_sum(close,8),8),ts_std(close,8))),1,if_else(sub(1,div(volume,ts_mean(volume,20))),1,neg(1))))",
    # Alpha #23 — high-of-high momentum
    "if_else(sub(div(ts_sum(high,20),20),high),neg(delta(high,2)),0)",
    # Alpha #24 — long-window mean reversion
    "if_else(sub(div(delta(div(ts_sum(close,100),100),100),delay(close,100)),0.05),neg(sub(close,ts_min(close,100))),neg(delta(close,3)))",
    # Alpha #28 — adv/low/high covariance + close-vwap mean reversion
    "sub(add(covariance(ts_mean(volume,20),low,5),div(add(high,low),2)),close)",
    # Alpha #32 — z-score of price vs long-window mean
    "add(zscore(sub(div(ts_sum(close,7),7),close)),mul(20,correlation(vwap,delay(close,5),230)))",
    # Alpha #33 — open / close ratio rank
    "rank(neg(power(sub(1,div(open,close)),1)))",
    # Alpha #41 — log-vwap minus geometric-mean of high-low
    "sub(sqrt(mul(high,low)),vwap)",
    # ---- Phase 3.2: fundamentals seeds (require factor_daily_fundamentals)
    # Value: cross-sectional rank of -P/B (low P/B → high score)
    "rank(neg(pb_ratio))",
    # Value: earnings yield = EPS / Price ≈ EPS / market_cap × shares
    # Approximated here as EPS_TTM / market_cap (per-share-EPS × shares /
    # market_cap → equivalent to 1/PE when PE > 0). Robust to PE NaN.
    "rank(div(eps_ttm,market_cap))",
    # Quality: ROE rank (profitability)
    "rank(roe)",
    # Quality: gross margin rank
    "rank(gross_margin)",
    # Leverage: low debt-to-equity preferred
    "rank(neg(debt_to_equity))",
    # Size: small-cap effect — rank of -market_cap (smaller → higher score)
    "rank(neg(market_cap))",
    # Composite: profitability × value (gross margin × earnings yield)
    "mul(rank(gross_margin),rank(div(eps_ttm,market_cap)))",
    # Reversal-on-fundamentals: 5d momentum residualized by ROE rank
    "sub(rank(neg(delta(close,5))),rank(roe))",
]


def get_seed_population() -> List[FactorNode]:
    """Parse all seeds into FactorNode trees."""
    return [parse(s) for s in SEEDS]
