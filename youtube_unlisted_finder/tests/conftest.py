"""Pytest configuration: importable modules, source-tree write guard, network guard.

Every production path constant is redirected to pytest's tmp_path, so tests never
touch credentials, tokens, config, logs or reports, and any attempt to write
inside the tool directory or open a non-loopback socket fails loudly. The
YouTube API is replaced by an in-memory fake.
"""

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from googleapiclient.errors import HttpError

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

# Interpreter and pytest housekeeping that legitimately writes inside the tree
_ALLOWED_PARTS = ("__pycache__", ".pytest_cache")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = "wax+"
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
_NETWORK_EVENTS = ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname")
_PROCESS_EVENTS = ("subprocess.Popen", "os.system")
_guard_active = False

# Modules that import the path constants by value, so each binding is patched
_PATH_MODULES = ("config", "utils", "youtube_client", "report", "main")

FAKE_PAGE_SIZE = 2


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
    """Fail loudly on source-tree writes, non-loopback network use or processes."""
    if not _guard_active or len(args) == 0:
        return
    if event in _PROCESS_EVENTS:
        raise AssertionError(f"Test attempted to spawn a process: {event} {args!r}")
    if event in _NETWORK_EVENTS:
        address = args[1] if len(args) > 1 else args[0]
        target = address if event == "socket.connect" else args[0]
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
        paths = tuple(a for a in args[:2] if a is not None and a != -1)
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
    reports = tmp_path / "reports"
    mapping = {
        "CONFIG_DIR": config_dir,
        "CLIENT_SECRET_FILE": config_dir / "client_secret.json",
        "TOKEN_FILE": config_dir / "token.json",
        "LOG_FILE": config_dir / "log.txt",
        "REPORTS_DIR": reports,
    }
    for module_name in _PATH_MODULES:
        module = importlib.import_module(module_name)
        for name, value in mapping.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, str(value))
    return SimpleNamespace(**{k.lower(): v for k, v in mapping.items()})


def make_video(
    video_id: str, privacy: str = "unlisted", title: str | None = None,
    channel: str = "Some Channel",
) -> dict[str, Any]:
    """Build a videos.list resource."""
    return {
        "id": video_id,
        "snippet": {"title": title or f"Title {video_id}", "channelTitle": channel},
        "status": {"privacyStatus": privacy},
    }


def http_error(status: int = 404) -> HttpError:
    """Build an HttpError without any network use."""
    return HttpError(SimpleNamespace(status=status, reason="error"), b"{}")


class FakeRequest:
    """A request whose execute() returns a canned response or raises."""

    def __init__(self, response: Any) -> None:
        self.response = response

    def execute(self) -> Any:
        """Return the response, or raise it when it is an exception."""
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _Endpoint:
    """Mimics a googleapiclient resource exposing only list()."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def list(self, **kwargs: Any) -> FakeRequest:
        """Return a request for the handler's response."""
        return FakeRequest(self._handler(kwargs))


def _page(items: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Slice items into FAKE_PAGE_SIZE pages addressed by pageToken."""
    start = int(kwargs.get("pageToken") or 0)
    end = start + FAKE_PAGE_SIZE
    response: dict[str, Any] = {"items": items[start:end]}
    if end < len(items):
        response["nextPageToken"] = str(end)
    return response


class FakeYouTube:
    """In-memory stand-in for the googleapiclient YouTube service."""

    def __init__(self) -> None:
        self.playlists_data: list[tuple[str, str]] = []
        self.playlist_items: dict[str, list[str] | Exception] = {}
        self.videos_data: dict[str, dict[str, Any]] = {}
        self.liked: list[str] = []
        self.videos_id_batches: list[list[str]] = []

    def playlists(self) -> _Endpoint:
        """Return the playlists endpoint."""
        return _Endpoint(self._playlists)

    def playlistItems(self) -> _Endpoint:  # noqa: N802 - mirrors the real API
        """Return the playlistItems endpoint."""
        return _Endpoint(self._playlist_items)

    def videos(self) -> _Endpoint:
        """Return the videos endpoint."""
        return _Endpoint(self._videos)

    def _playlists(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if kwargs.get("mine"):
            entries = [{"id": i, "snippet": {"title": t}} for i, t in self.playlists_data]
            return _page(entries, kwargs)
        wanted = kwargs["id"]
        entries = [
            {"id": i, "snippet": {"title": t}}
            for i, t in self.playlists_data if i == wanted
        ]
        return {"items": entries}

    def _playlist_items(self, kwargs: dict[str, Any]) -> Any:
        ids = self.playlist_items[kwargs["playlistId"]]
        if isinstance(ids, Exception):
            return ids
        entries = [{"contentDetails": {"videoId": v}} for v in ids]
        return _page(entries, kwargs)

    def _videos(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if kwargs.get("myRating"):
            return _page([self.videos_data[v] for v in self.liked], kwargs)
        # The real API rejects maxResults together with id
        assert "maxResults" not in kwargs, "videos.list: id and maxResults conflict"
        batch = kwargs["id"].split(",")
        self.videos_id_batches.append(batch)
        return {"items": [self.videos_data[v] for v in batch if v in self.videos_data]}


@pytest.fixture
def fake_youtube() -> FakeYouTube:
    """Return an empty in-memory YouTube service."""
    return FakeYouTube()
