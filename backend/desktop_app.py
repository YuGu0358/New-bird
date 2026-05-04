from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import aiosqlite  # Ensure PyInstaller collects the async SQLite driver.
import uvicorn
from dotenv import dotenv_values

APP_NAME = "Newbird Platform"
WINDOW_SIZE = (1480, 980)
MIN_WINDOW_SIZE = (1220, 820)


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def _app_support_dir() -> Path:
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        appdata_root = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        path = appdata_root / APP_NAME
    else:
        xdg_root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = xdg_root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _frontend_dist_dir() -> Path:
    bundle_root = _bundle_root()
    candidates = (
        bundle_root / "frontend_dist",
        Path(__file__).resolve().parents[1] / "frontend" / "dist",
    )

    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate.resolve()

    raise RuntimeError(
        "找不到前端构建产物。请先运行前端构建，或使用桌面构建脚本打包应用。"
    )


def _candidate_env_files(anchor_paths: list[Path] | tuple[Path, ...] | None = None) -> list[Path]:
    patterns = (
        ".env",
        "backend/.env",
        "trading_platform/backend/.env",
    )
    anchors = list(
        anchor_paths
        if anchor_paths is not None
        else [
            Path.cwd(),
            Path(__file__).resolve().parent,
            _bundle_root(),
            Path(sys.executable).resolve().parent,
        ]
    )
    candidates: list[Path] = []
    seen: set[Path] = set()

    for anchor in anchors:
        for root in (anchor, *anchor.parents):
            for pattern in patterns:
                candidate = (root / pattern).expanduser().resolve()
                if candidate in seen or not candidate.exists() or not candidate.is_file():
                    continue
                seen.add(candidate)
                candidates.append(candidate)

    return candidates


def _load_runtime_env(anchor_paths: list[Path] | tuple[Path, ...] | None = None) -> Path | None:
    explicit_env = os.getenv("TRADING_PLATFORM_ENV_FILE", "").strip()
    if explicit_env:
        candidates = [Path(explicit_env).expanduser().resolve()]
    else:
        candidates = _candidate_env_files(anchor_paths=anchor_paths)

    for candidate in candidates:
        values = dotenv_values(candidate)
        for key, value in values.items():
            if not key or value is None:
                continue
            normalized_value = str(value).strip()
            if normalized_value and not os.getenv(key):
                os.environ[key] = normalized_value
        if values:
            os.environ["TRADING_PLATFORM_ENV_SOURCE"] = str(candidate)
            return candidate

    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except URLError:
            time.sleep(0.25)

    raise RuntimeError(f"桌面应用后端启动超时：{url}")


def _prepare_environment() -> None:
    os.environ.setdefault("DATA_DIR", str(_app_support_dir()))
    os.environ["TRADING_PLATFORM_FRONTEND_DIST"] = str(_frontend_dist_dir())
    _load_runtime_env()


def _resolve_window_title() -> str:
    from app import runtime_settings

    configured_title = str(runtime_settings.get_setting("DISPLAY_NAME", APP_NAME) or "").strip()
    return configured_title or APP_NAME


def main() -> None:
    _prepare_environment()

    from app.main import app
    import webview

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )

    server_thread = threading.Thread(target=server.run, name="trading-raven-server", daemon=True)
    server_thread.start()

    _wait_for_server(f"http://127.0.0.1:{port}/api/bot/status")

    window = webview.create_window(
        _resolve_window_title(),
        url=f"http://127.0.0.1:{port}",
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_WINDOW_SIZE,
        text_select=True,
    )
    window.events.closed += lambda: setattr(server, "should_exit", True)
    webview.start()


if __name__ == "__main__":
    main()
