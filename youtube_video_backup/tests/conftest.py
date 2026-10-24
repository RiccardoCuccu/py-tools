"""Pytest configuration: importable modules, source-tree write guard, network guard.

Every production path constant is redirected to pytest's tmp_path, so tests never
touch credentials, tokens, config, logs, archives or downloads, and any attempt to
write inside the tool directory or open a non-loopback socket fails loudly.
"""

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
_NETWORK_EVENTS = ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname")
_guard_active = False

# Modules that import the path constants by value, so each binding is patched
_PATH_MODULES = ("config", "utils", "youtube_client", "video_handler", "main")


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
    """Fail loudly on any write inside the tool dir or any non-loopback network use."""
    if not _guard_active or not args:
        return
    if event in _NETWORK_EVENTS:
        target = args[1] if event == "socket.connect" and len(args) > 1 else args[0]
        host = target[0] if isinstance(target, tuple) and target else target
        if host not in _LOOPBACK_HOSTS:
            raise AssertionError(f"Test attempted network access: {event} {target!r}")
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
def _forbid_source_tree_writes_and_network():
    """Fail any test that writes into the tool dir or reaches the network."""
    global _guard_active
    _guard_active = True
    try:
        yield
    finally:
        _guard_active = False


@pytest.fixture(autouse=True)
def paths(tmp_path, monkeypatch):
    """Redirect every production path constant to tmp_path and return the paths."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    mapping = {
        "CONFIG_DIR": config_dir,
        "CONFIG_FILE": config_dir / "config.json",
        "CLIENT_SECRET_FILE": config_dir / "client_secret.json",
        "TOKEN_FILE": config_dir / "token.json",
        "STATE_FILE": config_dir / "state.json",
        "ARCHIVE_FILE": config_dir / "archive.txt",
        "LOG_FILE": config_dir / "log.txt",
        "API_KEY_FILE": config_dir / "api_key.txt",
        "CHANNEL_VIDEOS_FILE": config_dir / "channel_videos.json",
        "DOWNLOAD_DIR": downloads,
    }
    for module_name in _PATH_MODULES:
        module = importlib.import_module(module_name)
        for name, value in mapping.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, str(value))
    return SimpleNamespace(**{k.lower(): v for k, v in mapping.items()})
