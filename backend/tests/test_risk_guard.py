"""RiskGuard composes policies and proxies a Broker."""
from __future__ import annotations

from typing import Any, Optional

import pytest

from core.broker.base import Broker
from core.risk.errors import RiskViolationError
from core.risk.guard import RiskGuard
from core.risk.policies.max_position_size import MaxPositionSizePolicy
from core.risk.policies.symbol_blocklist import SymbolBlocklistPolicy
from core.risk.portfolio_snapshot import PortfolioSnapshot


class _FakeBroker(Broker):
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.closed: list[str] = []

    async def list_positions(self) -> list[dict[str, Any]]:
        return []

    async def list_orders(self, *, status: str = "all", limit: Optional[int] = None) -> list[dict[str, Any]]:
        return []

    async def submit_order(self, *, symbol: str, side: str, notional: Optional[float] = None, qty: Optional[float] = None) -> dict[str, Any]:
        self.submitted.append({"symbol": symbol, "side": side, "notional": notional, "qty": qty})
        return {"id": "ok", "symbol": symbol, "side": side}

    async def close_position(self, symbol: str) -> dict[str, Any]:
        self.closed.append(symbol)
        return {"closed": symbol}

    async def get_account(self) -> dict[str, Any]:
        return {
            "id": "fake",
            "status": "ACTIVE",
            "currency": "USD",
            "equity": 100_000.0,
            "cash": 100_000.0,
            "buying_power": 100_000.0,
        }


def _empty_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(cash=100_000.0, equity=100_000.0)


@pytest.mark.asyncio
async def test_guard_allows_clean_order() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(
        inner,
        policies=[MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)],
        snapshot_provider=lambda: _empty_snapshot(),
    )
    response = await guard.submit_order(symbol="AAPL", side="buy", notional=1_000.0)
    assert response["id"] == "ok"
    assert inner.submitted == [{"symbol": "AAPL", "side": "buy", "notional": 1_000.0, "qty": None}]
    assert guard.violations == []


@pytest.mark.asyncio
async def test_guard_raises_on_first_violation() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(
        inner,
        policies=[
            SymbolBlocklistPolicy(symbols=["GME"]),
            MaxPositionSizePolicy(max_notional_per_symbol=5_000.0),
        ],
        snapshot_provider=lambda: _empty_snapshot(),
    )
    with pytest.raises(RiskViolationError) as excinfo:
        await guard.submit_order(symbol="GME", side="buy", notional=500.0)
    assert "blocklist" in excinfo.value.result.policy_name
    assert inner.submitted == []
    assert len(guard.violations) == 1
    assert guard.violations[0].policy_name == "symbol_blocklist"


@pytest.mark.asyncio
async def test_guard_passes_through_close_position_without_checks() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(
        inner,
        policies=[SymbolBlocklistPolicy(symbols=["AAPL"])],
        snapshot_provider=lambda: _empty_snapshot(),
    )
    response = await guard.close_position("AAPL")
    # close_position is an exit — should not be gated.
    assert response == {"closed": "AAPL"}


@pytest.mark.asyncio
async def test_guard_proxies_list_methods() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(inner, policies=[], snapshot_provider=lambda: _empty_snapshot())
    assert await guard.list_positions() == []
    assert await guard.list_orders() == []
