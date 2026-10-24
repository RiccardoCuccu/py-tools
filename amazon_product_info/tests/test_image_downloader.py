"""Tests for image_downloader.py using a fake HTTP session and tmp_path."""

import asyncio

import pytest

import config
from fetcher_html import HTTPSessionManager
from image_downloader import ImageDownloader


class _FakeResponse:
    def __init__(self, body=b"imgdata", status=200):
        self.body = body
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def read(self):
        return self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture
def no_sleep(monkeypatch):
    """Skip the exponential back-off delays."""

    async def instant(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _session(monkeypatch, responses):
    session = _FakeSession(responses)

    async def get_session():
        return session

    monkeypatch.setattr(HTTPSessionManager, "get_session", get_session)
    return session


def test_constructor_does_not_create_directory(tmp_path):
    """The images directory only appears when an image is actually saved."""
    target = tmp_path / "images"
    ImageDownloader(str(target))
    assert not target.exists()


def test_default_directory_comes_from_config(monkeypatch, tmp_path):
    """The output directory defaults to config.IMAGES_OUTPUT_DIR."""
    monkeypatch.setattr(config, "IMAGES_OUTPUT_DIR", str(tmp_path / "from_config"))
    assert ImageDownloader().output_dir == tmp_path / "from_config"


def test_download_saves_file(monkeypatch, tmp_path):
    """The image is stored as {ASIN}.jpg, creating nested directories."""
    _session(monkeypatch, [_FakeResponse(b"abc")])
    downloader = ImageDownloader(str(tmp_path / "a" / "b"))
    path = asyncio.run(downloader.download_image("https://x/i.jpg", "B0ABCDEFGH"))

    saved = tmp_path / "a" / "b" / "B0ABCDEFGH.jpg"
    assert path == str(saved)
    assert saved.read_bytes() == b"abc"
    assert not list(saved.parent.glob("*.part"))


def test_download_sanitizes_asin(monkeypatch, tmp_path):
    """Path separators in the ASIN cannot escape the output directory."""
    _session(monkeypatch, [_FakeResponse()])
    downloader = ImageDownloader(str(tmp_path))
    path = asyncio.run(downloader.download_image("https://x/i.jpg", "../evil"))
    assert path is not None
    assert (tmp_path / "___evil.jpg").exists()


def test_download_retries_then_succeeds(monkeypatch, tmp_path, no_sleep):
    """Transient HTTP errors are retried up to the limit."""
    session = _session(monkeypatch, [_FakeResponse(status=500), _FakeResponse(b"ok")])
    downloader = ImageDownloader(str(tmp_path))
    path = asyncio.run(downloader.download_image("https://x/i.jpg", "A1", max_retries=3))
    assert path is not None
    assert session.calls == 2


def test_download_gives_up_after_max_retries(monkeypatch, tmp_path, no_sleep):
    """Persistent failures return None after exactly max_retries attempts."""
    session = _session(monkeypatch, [_FakeResponse(status=404)] * 3)
    downloader = ImageDownloader(str(tmp_path))
    assert asyncio.run(downloader.download_image("https://x/i.jpg", "A1", max_retries=3)) is None
    assert session.calls == 3
    assert not (tmp_path / "A1.jpg").exists()


def test_default_retries_from_config(monkeypatch, tmp_path, no_sleep):
    """The retry limit defaults to config.IMAGE_DOWNLOAD_MAX_RETRIES."""
    monkeypatch.setattr(config, "IMAGE_DOWNLOAD_MAX_RETRIES", 2)
    session = _session(monkeypatch, [_FakeResponse(status=500)] * 2)
    downloader = ImageDownloader(str(tmp_path))
    assert asyncio.run(downloader.download_image("https://x/i.jpg", "A1")) is None
    assert session.calls == 2


def test_empty_body_is_not_saved(monkeypatch, tmp_path, no_sleep):
    """A 200 response with no content is treated as a failure."""
    _session(monkeypatch, [_FakeResponse(b"")] * 2)
    downloader = ImageDownloader(str(tmp_path))
    assert asyncio.run(downloader.download_image("https://x/i.jpg", "A1", max_retries=2)) is None
    assert not (tmp_path / "A1.jpg").exists()


def test_write_failure_returns_none_without_leftovers(monkeypatch, tmp_path):
    """If the output path is unusable the call fails cleanly."""
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    _session(monkeypatch, [_FakeResponse()])
    downloader = ImageDownloader(str(blocker))
    assert asyncio.run(downloader.download_image("https://x/i.jpg", "A1")) is None
