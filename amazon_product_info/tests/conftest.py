"""Pytest configuration: make the tool modules importable and guard the environment."""

import os
import socket
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
_guard_active = False


def _inside_tool_dir(path: object) -> bool:
    """Return True if *path* is a real path under the tool dir (not housekeeping)."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False  # file descriptors and dir_fd-relative calls
    raw = os.fsdecode(path)
    norm = os.path.normcase(os.path.abspath(raw))
    root = os.path.normcase(str(TOOL_DIR))
    if norm != root and not norm.startswith(root + os.sep):
        return False
    return not any(part in norm.split(os.sep) for part in _ALLOWED_PARTS)


def _audit(event: str, args: tuple[object, ...]) -> None:
    """Fail loudly on any write, rename, delete or mkdir inside the tool dir."""
    if not _guard_active or not args:
        return
    if event == "open":
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
        if not (flags & _WRITE_FLAGS or any(c in mode for c in _WRITE_MODE_CHARS)):
            return
        paths = tuple(args[:1])
    elif event in ("os.remove", "os.rename", "os.mkdir", "os.rmdir"):
        paths = tuple(a for a in args[:2] if a is not None)
    else:
        return
    for path in paths:
        if _inside_tool_dir(path):
            raise AssertionError(f"Test attempted to modify the source tree: {path!r}")


sys.addaudithook(_audit)


@pytest.fixture(autouse=True)
def _forbid_source_tree_writes():
    """Fail any test that writes outside pytest temp locations into the tool dir."""
    global _guard_active
    _guard_active = True
    try:
        yield
    finally:
        _guard_active = False


def _is_loopback(address: object) -> bool:
    """Return True for loopback targets (asyncio uses a local socketpair on Windows)."""
    host = address[0] if isinstance(address, tuple) and address else address
    return isinstance(host, str) and host in _LOOPBACK_HOSTS


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch):
    """Fail loudly on any non-loopback network access."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _blocked(target: object) -> None:
        raise AssertionError(f"Test attempted network access: {target!r}")

    def connect(self, address):
        if not _is_loopback(address):
            _blocked(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _is_loopback(address):
            _blocked(address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        _blocked(address)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            _blocked(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch):
    """Replace any real PA-API credentials loaded from config.json with dummies."""
    import config

    monkeypatch.setattr(config, "PA_API_ACCESS_KEY", "test-access-key")
    monkeypatch.setattr(config, "PA_API_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config, "PA_API_PARTNER_TAG", "test-tag-21")
