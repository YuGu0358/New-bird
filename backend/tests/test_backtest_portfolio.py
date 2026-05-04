"""BacktestPortfolio fill semantics, mark-to-market, equity snapshots."""
from __future__ import annotations

from datetime import datetime, timezone

from core.backtest.portfolio import BacktestPortfolio


def _now(year: int = 2025, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_initial_state() -> None:
    p = BacktestPortfolio(initial_cash=100_000.0)
    assert p.cash == 100_000.0
    assert p.positions == {}
    assert p.equity(prices={}) == 100_000.0


def test_buy_notional_creates_position() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, notional=1_000.0, timestamp=_now())
    pos = p.positions["AAPL"]
    assert pos.qty == 10.0
    assert pos.average_entry_price == 100.0
    assert p.cash == 9_000.0


def test_buy_qty_creates_position() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="MSFT", price=400.0, qty=5.0, timestamp=_now())
    assert p.positions["MSFT"].qty == 5.0
    assert p.cash == 8_000.0


def test_add_on_buy_increases_qty_and_updates_avg() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, qty=10.0, timestamp=_now())
    p.fill_buy(symbol="AAPL", price=80.0, qty=5.0, timestamp=_now(month=2))
    pos = p.positions["AAPL"]
    assert pos.qty == 15.0
    # weighted average: (10*100 + 5*80) / 15 = 1400 / 15 ≈ 93.3333
    assert round(pos.average_entry_price, 4) == 93.3333


def test_close_position_credits_cash_and_records_trade() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, qty=10.0, timestamp=_now())
    p.fill_close(symbol="AAPL", price=110.0, timestamp=_now(month=2), reason="take_profit")
    assert "AAPL" not in p.positions
    assert p.cash == 10_100.0
    assert any(t.side == "sell" and t.symbol == "AAPL" for t in p.trades)


def test_equity_marks_open_positions() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, qty=10.0, timestamp=_now())
    # Cash 9000 + 10 shares @ 105 = 10050
    assert p.equity(prices={"AAPL": 105.0}) == 10_050.0


def test_record_equity_snapshot_appends_curve() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    ts = _now()
    p.record_equity_snapshot(timestamp=ts, prices={})
    assert p.equity_curve == [(ts, 10_000.0)]
