"""Pytest configuration: make the tool module importable and guard the source tree."""

import os
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
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
