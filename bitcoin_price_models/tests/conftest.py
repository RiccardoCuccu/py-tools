"""Pytest configuration: importable modules and the write, network, browser guards.

Every production path constant is redirected to pytest's tmp_path, so tests never
touch the real price data or log, and any attempt to write inside the tool
directory, reach the network or launch a browser fails loudly.
"""

import importlib
import os
import socket
import sys
import webbrowser
from pathlib import Path
from types import SimpleNamespace

import pytest


TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
_guard_active = False

# Modules that import the path constants by value, so each binding is patched
_PATH_MODULES = (
    "config",
    "utils",
    "price_data",
    "halvings",
    "lib_cache",
    "chart_html",
    "main",
)


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


def _blocked_network(*_args: object, **_kwargs: object) -> None:
    """Replacement for socket connect calls: tests must never reach the network."""
    raise AssertionError("Test attempted network access")


@pytest.fixture(autouse=True)
def _forbid_source_tree_writes():
    """Fail any test that writes into the tool dir."""
    global _guard_active
    _guard_active = True
    try:
        yield
    finally:
        _guard_active = False


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch):
    """Fail any test that opens a network connection."""
    monkeypatch.setattr(socket.socket, "connect", _blocked_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_network)
    monkeypatch.setattr(socket, "create_connection", _blocked_network)


def _blocked_browser(*_args: object, **_kwargs: object) -> None:
    """Replacement for webbrowser openers: tests must never launch a browser."""
    raise AssertionError("Test attempted to open a browser")


@pytest.fixture(autouse=True)
def _forbid_browser(monkeypatch):
    """Fail any test that tries to launch a real browser."""
    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, _blocked_browser)


@pytest.fixture(autouse=True)
def paths(tmp_path_factory, monkeypatch):
    """Redirect every production path constant to a pytest temp dir."""
    data_dir = tmp_path_factory.mktemp("paths") / "data"
    data_dir.mkdir()  # separate from tmp_path so tests can list tmp_path
    output_dir = data_dir.parent / "output"
    mapping = {
        "DATA_DIR": data_dir,
        "JSON_FILE": data_dir / "market-price.json",
        "LOG_FILE": data_dir / "log.txt",
        "HALVINGS_FILE": data_dir / "halvings.json",
        "LWC_FILE": data_dir / "lightweight-charts.js",
        "OUTPUT_DIR": output_dir,
        "CHART_FILE": output_dir / "chart.html",
    }
    for module_name in _PATH_MODULES:
        module = importlib.import_module(module_name)
        for name, value in mapping.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, str(value))
    return SimpleNamespace(**{k.lower(): v for k, v in mapping.items()})
