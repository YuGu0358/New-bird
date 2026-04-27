"""DCF (discounted cash flow) — 2-stage FCFE model.

Stage 1: high-growth phase (years 1..N), grows at `growth_stage1`.
Stage 2: stable / terminal phase, grows at `growth_terminal` in perpetuity.

We bundle a tiny ±1pt sensitivity grid so the UI can render fair_low /
fair_high bands without re-calling the API.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DCFInputs:
    fcfe0: float  # most-recent FCFE per share (or per total for shares_out=None)
    growth_stage1: float  # decimal — 0.10 = 10% per year
    growth_terminal: float  # decimal — typically 0.02 .. 0.04
    discount_rate: float  # decimal — WACC or cost-of-equity, e.g. 0.10
    years_stage1: int = 7
    shares_out: float | None = None


@dataclass
class DCFOutput:
    fair_value_per_share: float
    fair_low: float
    fair_high: float
    breakdown: dict[str, float]
    grid: list[dict[str, float]] = field(default_factory=list)


def _project(cf0: float, growth: float, n: int) -> list[float]:
    out: list[float] = []
    cf = cf0
    for _ in range(n):
        cf *= 1 + growth
        out.append(cf)
    return out


def _pv(cfs: list[float], discount: float) -> float:
    return sum(cf / (1 + discount) ** (i + 1) for i, cf in enumerate(cfs))


def run_dcf(inp: DCFInputs) -> DCFOutput:
    if inp.discount_rate <= inp.growth_terminal:
        raise ValueError("discount_rate must exceed growth_terminal for a finite valuation")

    cfs = _project(inp.fcfe0, inp.growth_stage1, inp.years_stage1)
    pv_stage1 = _pv(cfs, inp.discount_rate)
    terminal_cf = cfs[-1] * (1 + inp.growth_terminal)
    terminal_value = terminal_cf / (inp.discount_rate - inp.growth_terminal)
    pv_terminal = terminal_value / (1 + inp.discount_rate) ** inp.years_stage1
    fair_value = pv_stage1 + pv_terminal

    grid: list[dict[str, float]] = []
    for dg in (-0.01, 0.0, 0.01):
        for dd in (-0.01, 0.0, 0.01):
            d = inp.discount_rate + dd
            g = inp.growth_terminal
            if d <= g:
                continue
            cfs2 = _project(inp.fcfe0, inp.growth_stage1 + dg, inp.years_stage1)
            pv1 = _pv(cfs2, d)
            tv = cfs2[-1] * (1 + g) / (d - g)
            pvt = tv / (1 + d) ** inp.years_stage1
            grid.append({"delta_growth": dg, "delta_discount": dd, "fair_value": pv1 + pvt})

    fair_low = min(g["fair_value"] for g in grid) if grid else fair_value
    fair_high = max(g["fair_value"] for g in grid) if grid else fair_value

    return DCFOutput(
        fair_value_per_share=fair_value,
        fair_low=fair_low,
        fair_high=fair_high,
        breakdown={
            "pv_stage1": pv_stage1,
            "pv_terminal": pv_terminal,
            "terminal_value_undiscounted": terminal_value,
        },
        grid=grid,
    )
