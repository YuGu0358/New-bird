"""Each policy in isolation: allow/deny boundary cases."""
from __future__ import annotations

import pytest

from core.risk.policies.max_daily_loss import MaxDailyLossPolicy
from core.risk.policies.max_open_positions import MaxOpenPositionsPolicy
from core.risk.policies.max_position_size import MaxPositionSizePolicy
from core.risk.policies.max_total_exposure import MaxTotalExposurePolicy
from core.risk.policies.symbol_blocklist import SymbolBlocklistPolicy
from core.risk.portfolio_snapshot import PortfolioPositionView, PortfolioSnapshot
from core.risk.types import OrderRequest


def _empty_snapshot(cash: float = 100_000.0, equity: float | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(cash=cash, equity=equity if equity is not None else cash)


def _snapshot_with_positions(
    *,
    cash: float,
    positions: dict[str, PortfolioPositionView],
    realized_pnl_today: float = 0.0,
) -> PortfolioSnapshot:
    equity = cash + sum(p.market_value for p in positions.values())
    return PortfolioSnapshot(
        cash=cash,
        equity=equity,
        positions=positions,
        realized_pnl_today=realized_pnl_today,
    )


@pytest.mark.asyncio
async def test_max_position_size_allows_below_cap() -> None:
    policy = MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, _empty_snapshot())
    assert result.allowed


@pytest.mark.asyncio
async def test_max_position_size_blocks_when_combined_exceeds_cap() -> None:
    policy = MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)
    snap = _snapshot_with_positions(
        cash=95_000.0,
        positions={
            "AAPL": PortfolioPositionView(
                symbol="AAPL",
                qty=40.0,
                average_entry_price=100.0,
                current_price=110.0,
                market_value=4_400.0,
                unrealized_pl=400.0,
            )
        },
    )
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0, current_price=110.0)
    result = await policy.evaluate(request, snap)
    # Existing 4400 + new 1000 = 5400 > 5000 cap → deny
    assert not result.allowed
    assert "AAPL" in result.reason


@pytest.mark.asyncio
async def test_max_position_size_allows_sell() -> None:
    policy = MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)
    request = OrderRequest(symbol="AAPL", side="sell", qty=10.0, current_price=110.0)
    result = await policy.evaluate(request, _empty_snapshot())
    # Sells reduce position, not increase — allowed.
    assert result.allowed


@pytest.mark.asyncio
async def test_max_total_exposure_allows_below_threshold() -> None:
    policy = MaxTotalExposurePolicy(max_exposure_pct=0.5)
    snap = _snapshot_with_positions(
        cash=80_000.0,
        positions={
            "AAPL": PortfolioPositionView(
                symbol="AAPL", qty=10.0, average_entry_price=100.0,
                current_price=100.0, market_value=1_000.0, unrealized_pl=0.0,
            )
        },
    )
    request = OrderRequest(symbol="MSFT", side="buy", notional=10_000.0)
    result = await policy.evaluate(request, snap)
    # Existing exposure 1000 + new 10000 = 11000; equity 81000; ratio ≈ 0.136 < 0.5
    assert result.allowed


@pytest.mark.asyncio
async def test_max_total_exposure_denies_above_threshold() -> None:
    policy = MaxTotalExposurePolicy(max_exposure_pct=0.5)
    snap = _snapshot_with_positions(
        cash=20_000.0,
        positions={
            "AAPL": PortfolioPositionView(
                symbol="AAPL", qty=350.0, average_entry_price=100.0,
                current_price=100.0, market_value=35_000.0, unrealized_pl=0.0,
            )
        },
    )
    request = OrderRequest(symbol="MSFT", side="buy", notional=10_000.0)
    result = await policy.evaluate(request, snap)
    # Existing exposure 35000 + new 10000 = 45000; equity 55000; ratio ≈ 0.818 > 0.5
    assert not result.allowed


@pytest.mark.asyncio
async def test_max_open_positions_allows_below_count() -> None:
    policy = MaxOpenPositionsPolicy(max_positions=5)
    snap = _snapshot_with_positions(
        cash=90_000.0,
        positions={
            f"S{i}": PortfolioPositionView(
                symbol=f"S{i}", qty=10.0, average_entry_price=10.0,
                current_price=10.0, market_value=100.0, unrealized_pl=0.0,
            )
            for i in range(3)
        },
    )
    request = OrderRequest(symbol="NEW", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert result.allowed


@pytest.mark.asyncio
async def test_max_open_positions_blocks_at_cap_for_new_symbol() -> None:
    policy = MaxOpenPositionsPolicy(max_positions=3)
    snap = _snapshot_with_positions(
        cash=90_000.0,
        positions={
            f"S{i}": PortfolioPositionView(
                symbol=f"S{i}", qty=10.0, average_entry_price=10.0,
                current_price=10.0, market_value=100.0, unrealized_pl=0.0,
            )
            for i in range(3)
        },
    )
    request = OrderRequest(symbol="NEW", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert not result.allowed


@pytest.mark.asyncio
async def test_max_open_positions_allows_add_on_to_existing() -> None:
    policy = MaxOpenPositionsPolicy(max_positions=3)
    positions = {
        f"S{i}": PortfolioPositionView(
            symbol=f"S{i}", qty=10.0, average_entry_price=10.0,
            current_price=10.0, market_value=100.0, unrealized_pl=0.0,
        )
        for i in range(3)
    }
    snap = _snapshot_with_positions(cash=90_000.0, positions=positions)
    request = OrderRequest(symbol="S1", side="buy", notional=100.0)
    result = await policy.evaluate(request, snap)
    # Adding to an existing position doesn't grow the position count.
    assert result.allowed


@pytest.mark.asyncio
async def test_max_daily_loss_allows_when_above_threshold() -> None:
    policy = MaxDailyLossPolicy(max_loss_usd=500.0)
    snap = _snapshot_with_positions(cash=99_000.0, positions={}, realized_pnl_today=-200.0)
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert result.allowed


@pytest.mark.asyncio
async def test_max_daily_loss_blocks_when_loss_exceeded() -> None:
    policy = MaxDailyLossPolicy(max_loss_usd=500.0)
    snap = _snapshot_with_positions(cash=99_000.0, positions={}, realized_pnl_today=-650.0)
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert not result.allowed


@pytest.mark.asyncio
async def test_max_daily_loss_does_not_block_sells() -> None:
    """Selling should always be allowed even after the daily-loss circuit
    breaker trips — closing positions is how you stop the bleeding."""
    policy = MaxDailyLossPolicy(max_loss_usd=500.0)
    snap = _snapshot_with_positions(cash=99_000.0, positions={}, realized_pnl_today=-650.0)
    request = OrderRequest(symbol="AAPL", side="sell", qty=10.0, current_price=100.0)
    result = await policy.evaluate(request, snap)
    assert result.allowed


@pytest.mark.asyncio
async def test_symbol_blocklist_denies_listed() -> None:
    policy = SymbolBlocklistPolicy(symbols=["GME", "AMC"])
    request = OrderRequest(symbol="GME", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, _empty_snapshot())
    assert not result.allowed


@pytest.mark.asyncio
async def test_symbol_blocklist_allows_unlisted() -> None:
    policy = SymbolBlocklistPolicy(symbols=["GME", "AMC"])
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, _empty_snapshot())
    assert result.allowed
