from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_save_settings_persists_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_database_file = runtime_settings.DATABASE_FILE
            runtime_settings.DATABASE_FILE = Path(temp_dir) / "settings.db"

            env_overrides = {
                "ALPACA_API_KEY": "",
                "ALPACA_SECRET_KEY": "",
                "POLYGON_API_KEY": "",
                "TAVILY_API_KEY": "",
                "SETTINGS_ADMIN_TOKEN": "",
            }

            try:
                with patch.dict(os.environ, env_overrides, clear=False):
                    initial_status = runtime_settings.get_settings_status()
                    self.assertFalse(initial_status["is_ready"])

                    saved_status = runtime_settings.save_settings(
                        {
                            "ALPACA_API_KEY": "alpaca-key",
                            "ALPACA_SECRET_KEY": "alpaca-secret",
                            "POLYGON_API_KEY": "polygon-key",
                            "TAVILY_API_KEY": "tavily-key",
                        }
                    )

                    self.assertTrue(saved_status["is_ready"])
                    self.assertIn("ALPACA_API_KEY", saved_status["updated_keys"])
                    self.assertEqual(
                        runtime_settings.get_setting("ALPACA_API_KEY"),
                        "alpaca-key",
                    )
            finally:
                runtime_settings.DATABASE_FILE = original_database_file

    def test_display_name_is_persisted_and_exposed_in_settings_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_database_file = runtime_settings.DATABASE_FILE
            runtime_settings.DATABASE_FILE = Path(temp_dir) / "settings.db"

            env_overrides = {
                "DISPLAY_NAME": "",
                "ALPACA_API_KEY": "",
                "ALPACA_SECRET_KEY": "",
                "POLYGON_API_KEY": "",
                "TAVILY_API_KEY": "",
                "SETTINGS_ADMIN_TOKEN": "",
            }

            try:
                with patch.dict(os.environ, env_overrides, clear=False):
                    runtime_settings.save_settings({"DISPLAY_NAME": "Yugu"})

                    self.assertEqual(runtime_settings.get_setting("DISPLAY_NAME"), "Yugu")

                    status = runtime_settings.get_settings_status()
                    display_name_item = next(
                        item for item in status["items"] if item["key"] == "DISPLAY_NAME"
                    )

                    self.assertFalse(display_name_item["required"])
                    self.assertFalse(display_name_item["sensitive"])
                    self.assertTrue(display_name_item["configured"])
                    self.assertEqual(display_name_item["source"], "stored")
                    self.assertEqual(display_name_item["value"], "Yugu")
            finally:
                runtime_settings.DATABASE_FILE = original_database_file


if __name__ == "__main__":
    unittest.main()
