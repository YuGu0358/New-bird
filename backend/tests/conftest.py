from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point DATA_DIR at a fresh tmp dir so SQLite/runtime settings are isolated."""
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir)
        monkeypatch.setenv("DATA_DIR", str(path))
        # Force runtime_settings to re-read DATABASE_FILE on next import use
        from app import runtime_settings

        monkeypatch.setattr(
            runtime_settings,
            "DATABASE_FILE",
            path / "trading_platform.db",
        )
        yield path


@pytest.fixture
def client(isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Boot the FastAPI app with isolated state and yield a TestClient.

    Neutralizes background monitor startup so tests don't spawn polling loops.
    Skips the lifespan context entirely (TestClient without `with`).
    """
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "")
    monkeypatch.setenv("POLYGON_API_KEY", "")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "")

    # Stub background monitors before app import so any startup hook is a no-op.
    from app.services import bot_controller, price_alerts_service, social_polling_service

    async def _noop(*args, **kwargs):
        return None

    # price_alerts_service.start_monitor / shutdown_monitor were removed when the
    # in-process polling loop was retired in favor of the APScheduler job; keep the
    # patches tolerant so older lifespan code or future re-introductions still no-op.
    monkeypatch.setattr(price_alerts_service, "start_monitor", _noop, raising=False)
    monkeypatch.setattr(price_alerts_service, "shutdown_monitor", _noop, raising=False)
    # social_polling_service.start_monitor / shutdown_monitor were removed when the
    # in-process polling loop was retired in favor of the APScheduler job; keep the
    # patches tolerant so older lifespan code or future re-introductions still no-op.
    monkeypatch.setattr(social_polling_service, "start_monitor", _noop, raising=False)
    monkeypatch.setattr(social_polling_service, "shutdown_monitor", _noop, raising=False)
    monkeypatch.setattr(bot_controller, "shutdown_bot", _noop)

    from app.main import app

    # Do NOT use `with TestClient(app)` - that triggers FastAPI startup events
    # which would re-bind the (now-stubbed) symbols too late. Plain construction
    # skips the lifespan and is sufficient for HTTP route smoke tests.
    yield TestClient(app)
