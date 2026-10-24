"""Pytest configuration: importable modules, source-tree and network guards, fake keyring."""

import os
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

import keyring
import keyring.errors

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
# Real user data that tests must never read, list or touch in any way
_PROTECTED_NAMES = (".serpapi_config", "config.json", ".plagiarism_cache")
_PROTECTED_SUFFIX = "_plagiarism_report.txt"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
_NETWORK_EVENTS = (
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyaddr",
)
_guard_active = False


def _tool_parts(path: object) -> list[str] | None:
    """Return the path components below the tool dir, or None if outside it."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None  # file descriptors and dir_fd-relative calls
    norm = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    root = os.path.normcase(str(TOOL_DIR))
    if norm != root and not norm.startswith(root + os.sep):
        return None
    return norm[len(root):].split(os.sep)


def _is_protected(parts: list[str]) -> bool:
    """Return True for real user data: credentials, config, cache and reports."""
    return any(
        part in _PROTECTED_NAMES or part.endswith(_PROTECTED_SUFFIX) for part in parts
    )


def _is_housekeeping(parts: list[str]) -> bool:
    """Return True for interpreter and pytest bookkeeping paths."""
    return any(part in _ALLOWED_PARTS for part in parts)


def _check_path(path: object, *, writing: bool) -> None:
    """Raise if a test touches the source tree (write) or user data (any access)."""
    parts = _tool_parts(path)
    if parts is None:
        return
    if _is_protected(parts):
        raise AssertionError(f"Test attempted to access real user data: {path!r}")
    if writing and not _is_housekeeping(parts):
        raise AssertionError(f"Test attempted to modify the source tree: {path!r}")


def _audit(event: str, args: tuple[object, ...]) -> None:
    """Fail loudly on source-tree writes, user-data access and network use."""
    if not _guard_active or not args:
        return
    first = args[0]
    if event in _NETWORK_EVENTS:
        raise AssertionError(f"Test attempted network access: {event} {args[1:]!r}")
    if event == "open":
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
        writing = bool(flags & _WRITE_FLAGS or any(c in mode for c in _WRITE_MODE_CHARS))
        _check_path(first, writing=writing)
    elif event in ("os.remove", "os.rename", "os.mkdir", "os.rmdir"):
        for path in args[:2]:
            if path is not None:
                _check_path(path, writing=True)
    elif event in ("os.listdir", "os.scandir"):
        _check_path(first, writing=False)


sys.addaudithook(_audit)


@pytest.fixture(autouse=True)
def _forbid_real_io():
    """Fail any test that writes into the tool dir, reads user data or uses the network."""
    global _guard_active
    _guard_active = True
    try:
        yield
    finally:
        _guard_active = False


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
