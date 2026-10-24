"""Pytest configuration: make the tool importable and guard files and network."""

import os
import socket
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
# User data and huge model files: tests must never read, list or modify them
_PROTECTED_DIRS = tuple(TOOL_DIR / name for name in ("models", "audios", "transcripts"))
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
_guard_active = False


def _normalized(path: object) -> str | None:
    """Return a normalised absolute path, or None for fds and dir_fd-relative calls."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    return os.path.normcase(os.path.abspath(os.fsdecode(path)))


def _under(norm: str, root: Path) -> bool:
    """Return True if the normalised path is root itself or lies below it."""
    root_norm = os.path.normcase(str(root))
    return norm == root_norm or norm.startswith(root_norm + os.sep)


def _inside_tool_dir(path: object) -> bool:
    """Return True if *path* is a real path under the tool dir (not housekeeping)."""
    norm = _normalized(path)
    if norm is None or not _under(norm, TOOL_DIR):
        return False
    return not any(part in norm.split(os.sep) for part in _ALLOWED_PARTS)


def _is_protected(path: object) -> bool:
    """Return True if *path* is inside a protected user-data directory."""
    norm = _normalized(path)
    return norm is not None and any(_under(norm, d) for d in _PROTECTED_DIRS)


def _audit(event: str, args: tuple[object, ...]) -> None:
    """Fail loudly on protected-dir access and on writes, renames, deletes or mkdirs in the tool dir."""
    if not _guard_active or len(args) == 0:
        return
    if event in ("open", "os.listdir", "os.scandir") and _is_protected(args[0]):
        raise AssertionError(f"Test touched protected user data: {args[0]!r}")
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


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any attempt to open a network connection."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("Test attempted to reach the network")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
