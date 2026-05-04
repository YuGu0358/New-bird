"""Framework code shared across the trading platform.

`core` is intentionally free of provider-specific imports (Alpaca, Polygon,
yfinance). It defines the abstract surfaces (Strategy ABC, signals, broker
interface in later phases). Concrete implementations live under
`backend/strategies/`, `backend/services/`, etc.
"""
