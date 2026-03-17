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
import webview

APP_NAME = "Trading Raven Platform"
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
            return candidate

    raise RuntimeError(
        "找不到前端构建产物。请先运行前端构建，或使用桌面构建脚本打包应用。"
    )


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


def main() -> None:
    _prepare_environment()

    from app.main import app

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
        APP_NAME,
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
