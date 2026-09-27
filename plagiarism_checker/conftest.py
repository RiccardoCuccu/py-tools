"""Pytest configuration: make the tool module importable from the tests package."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import keyring
import keyring.errors


class _InMemoryKeyring:
    """Minimal in-memory stand-in for a real OS keyring backend, used in tests only."""

    def __init__(self) -> None:
        self._store: dict = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str):
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        key = (service, username)
        if key not in self._store:
            raise keyring.errors.PasswordDeleteError("no such password")
        del self._store[key]


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> _InMemoryKeyring:
    """Replace the OS keyring with an in-memory fake so tests never touch the real Credential Manager.

    Individual tests can further monkeypatch `keyring.get_keyring` (e.g. to a
    `keyring.backends.fail.Keyring` instance) to simulate an unavailable backend.
    """
    backend = _InMemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    return backend
