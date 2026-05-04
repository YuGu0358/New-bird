"""Tests for secure_storage_service + runtime_settings vault routing.

Each test patches `keyring` so we never touch the real OS keychain.
The runtime_settings master switch is exercised end-to-end through
get_setting / save_settings.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from app import runtime_settings
from app.services import secure_storage_service


class _FakeKeyring:
    """In-memory keyring replacement.

    Implements the subset of the `keyring` module surface used by
    secure_storage_service: ``get_password``, ``set_password``,
    ``delete_password``. The ``_keyring_module`` swap-in returns this
    object directly, so we just need duck-typing on those three names.
    """

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> _FakeKeyring:
    fake = _FakeKeyring()
    monkeypatch.setattr(secure_storage_service, "_keyring_module", lambda: fake)
    return fake


def test_get_secret_returns_none_when_keyring_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secure_storage_service, "_keyring_module", lambda: None)
    assert secure_storage_service.get_secret("SOME_KEY") is None


def test_set_secret_returns_false_when_keyring_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secure_storage_service, "_keyring_module", lambda: None)
    assert secure_storage_service.set_secret("K", "V") is False


def test_round_trip_via_keyring(fake_keyring: _FakeKeyring) -> None:
    assert secure_storage_service.set_secret("K", "V") is True
    assert secure_storage_service.get_secret("K") == "V"
    secure_storage_service.delete_secret("K")
    assert secure_storage_service.get_secret("K") is None


def test_get_secret_swallows_backend_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom:
        def get_password(self, *_: object) -> str:
            raise RuntimeError("backend locked")

    monkeypatch.setattr(secure_storage_service, "_keyring_module", lambda: _Boom())
    # Must not raise.
    assert secure_storage_service.get_secret("X") is None


def test_set_secret_swallows_backend_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom:
        def set_password(self, *_: object) -> None:
            raise RuntimeError("backend locked")

    monkeypatch.setattr(secure_storage_service, "_keyring_module", lambda: _Boom())
    assert secure_storage_service.set_secret("K", "V") is False


def test_delete_secret_swallows_missing_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Raises:
        def delete_password(self, *_: object) -> None:
            raise RuntimeError("not found")

    monkeypatch.setattr(secure_storage_service, "_keyring_module", lambda: _Raises())
    # Must not raise.
    secure_storage_service.delete_secret("missing")


# ---------- runtime_settings integration ----------


class RuntimeSettingsVaultTests(unittest.TestCase):
    """Integration tests that round-trip through runtime_settings.save_settings
    / get_setting with a fake keyring backend and an isolated SQLite file.
    """

    def setUp(self) -> None:
        # Per-test temp DB so we never touch the dev SQLite.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self._original_db = runtime_settings.DATABASE_FILE
        runtime_settings.DATABASE_FILE = Path(self._tmp.name) / "settings.db"
        self.addCleanup(self._restore_db)

        # Per-test fake keyring (so each test gets a clean slate).
        self.fake = _FakeKeyring()
        self._keyring_patch = patch.object(
            secure_storage_service, "_keyring_module", lambda: self.fake
        )
        self._keyring_patch.start()
        self.addCleanup(self._keyring_patch.stop)

    def _restore_db(self) -> None:
        runtime_settings.DATABASE_FILE = self._original_db

    def _set_master_switch(self, value: bool) -> None:
        """The master switch lives in SQLite. Write directly via save_settings;
        the key is sensitive=False so it always lands in SQLite (not vault)."""
        runtime_settings.save_settings(
            {"SECURE_STORAGE_ENABLED": "true" if value else "false"}
        )

    def test_master_switch_off_keeps_sqlite_path(self) -> None:
        self._set_master_switch(False)
        runtime_settings.save_settings({"ALPACA_API_KEY": "sqlite-stored"})
        self.assertEqual(
            runtime_settings.get_setting("ALPACA_API_KEY"), "sqlite-stored"
        )
        # Vault should be empty -- master switch was off, so we never wrote.
        self.assertNotIn(
            (secure_storage_service.SERVICE_NAME, "ALPACA_API_KEY"),
            self.fake.store,
        )

    def test_master_switch_on_routes_sensitive_to_vault(self) -> None:
        self._set_master_switch(True)
        runtime_settings.save_settings({"ALPACA_API_KEY": "vault-stored"})

        # Public read API returns the vault value.
        self.assertEqual(
            runtime_settings.get_setting("ALPACA_API_KEY"), "vault-stored"
        )
        # Vault contains the secret under the namespaced service.
        self.assertEqual(
            self.fake.store.get(
                (secure_storage_service.SERVICE_NAME, "ALPACA_API_KEY")
            ),
            "vault-stored",
        )
        # SQLite copy must NOT exist (we delete it on successful vault write).
        sqlite_value = runtime_settings._read_stored_values().get("ALPACA_API_KEY")
        self.assertIn(sqlite_value, (None, ""))

    def test_master_switch_on_keeps_non_sensitive_in_sqlite(self) -> None:
        self._set_master_switch(True)
        # DISPLAY_NAME is sensitive=False.
        runtime_settings.save_settings({"DISPLAY_NAME": "Yu Gu"})
        self.assertEqual(runtime_settings.get_setting("DISPLAY_NAME"), "Yu Gu")
        # Vault must NOT contain non-sensitive entries.
        self.assertNotIn(
            (secure_storage_service.SERVICE_NAME, "DISPLAY_NAME"),
            self.fake.store,
        )
        # SQLite has it.
        self.assertEqual(
            runtime_settings._read_stored_values().get("DISPLAY_NAME"), "Yu Gu"
        )

    def test_vault_failure_falls_back_to_sqlite(self) -> None:
        """When set_secret returns False (backend error), runtime_settings
        must persist to SQLite instead of silently losing the value."""
        self._set_master_switch(True)

        with patch.object(
            secure_storage_service, "set_secret", return_value=False
        ):
            runtime_settings.save_settings(
                {"ALPACA_API_KEY": "fallback-value"}
            )

        # Round-trip through SQLite even though vault was "enabled".
        self.assertEqual(
            runtime_settings.get_setting("ALPACA_API_KEY"), "fallback-value"
        )
        # And the SQLite copy is present.
        self.assertEqual(
            runtime_settings._read_stored_values().get("ALPACA_API_KEY"),
            "fallback-value",
        )

    def test_master_switch_itself_never_routed_to_vault(self) -> None:
        """SECURE_STORAGE_ENABLED is sensitive=False, but defend-in-depth:
        even if someone flipped the flag to True, the master switch must
        never end up in the keyring (chicken-and-egg)."""
        self._set_master_switch(True)
        # Toggle again to write the switch while vault is "on".
        runtime_settings.save_settings({"SECURE_STORAGE_ENABLED": "true"})
        self.assertNotIn(
            (
                secure_storage_service.SERVICE_NAME,
                "SECURE_STORAGE_ENABLED",
            ),
            self.fake.store,
        )

    def test_get_setting_falls_back_to_sqlite_on_vault_miss(self) -> None:
        """If the vault is enabled but the secret is absent (e.g. existing
        legacy SQLite value, switch only just turned on), get_setting must
        still surface the SQLite copy."""
        # Pre-seed SQLite while switch is off.
        self._set_master_switch(False)
        runtime_settings.save_settings({"ALPACA_API_KEY": "legacy-sqlite"})
        # Now flip on -- vault is empty, SQLite holds the value.
        self._set_master_switch(True)
        self.assertEqual(
            runtime_settings.get_setting("ALPACA_API_KEY"), "legacy-sqlite"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
