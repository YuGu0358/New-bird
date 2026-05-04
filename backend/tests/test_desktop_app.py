from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_app


class DesktopAppTests(unittest.TestCase):
    def test_load_runtime_env_discovers_repo_env_next_to_desktop_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            desktop_root = Path(temp_dir) / "Desktop"
            app_root = desktop_root / "Newbird Platform.app" / "Contents" / "MacOS"
            repo_env = desktop_root / "trading_platform" / "backend" / ".env"

            app_root.mkdir(parents=True)
            repo_env.parent.mkdir(parents=True)
            repo_env.write_text(
                "\n".join(
                    (
                        "ALPACA_API_KEY=test-alpaca-key",
                        "POLYGON_API_KEY=test-polygon-key",
                    )
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TRADING_PLATFORM_ENV_FILE", None)
                os.environ.pop("TRADING_PLATFORM_ENV_SOURCE", None)
                os.environ.pop("ALPACA_API_KEY", None)
                os.environ.pop("POLYGON_API_KEY", None)

                loaded_path = desktop_app._load_runtime_env(anchor_paths=[app_root])

                self.assertEqual(loaded_path, repo_env.resolve())
                self.assertEqual(os.environ["ALPACA_API_KEY"], "test-alpaca-key")
                self.assertEqual(os.environ["POLYGON_API_KEY"], "test-polygon-key")
                self.assertEqual(
                    os.environ["TRADING_PLATFORM_ENV_SOURCE"],
                    str(repo_env.resolve()),
                )


if __name__ == "__main__":
    unittest.main()
