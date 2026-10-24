"""Tests for download_audio_util: filename sanitising, download flow and temp-file handling."""

import hashlib
from pathlib import Path

import pytest
import requests

import download_audio_util as da


class FakeStream:
    """Context-manager stand-in for a streaming requests.Response."""

    def __init__(self, chunks: list[bytes], status_code: int = 200) -> None:
        self.chunks = chunks
        self.status_code = status_code

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def iter_content(self, chunk_size: int):
        yield from self.chunks


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    """Directory standing in for the tool's audios folder."""
    return tmp_path / "audios"


@pytest.fixture(autouse=True)
def _no_ffmpeg_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never search for or configure the real ffmpeg during tests."""
    monkeypatch.setattr(da, "_configure_ffmpeg", lambda: None)


def fake_convert(source: str, wav: str) -> None:
    """Conversion stand-in that writes a small WAV placeholder."""
    Path(wav).write_bytes(b"RIFF")


# --- _safe_filename_from_url ---


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://cdn.example/path/My Episode-01.mp3", "My_Episode_01"),
        ("https://cdn.example/path/My%20Episode.mp3?token=abc#frag", "My_Episode"),
        ("https://cdn.example/path/Caf%C3%A9_Cr%C3%A8me.mp3", "Cafe_Creme"),
        ("https://cdn.example/a/b/ep.final.mp3", "epfinal"),
        ("https://cdn.example/x/..%2F..%2Fevil.mp3", "evil"),
    ],
)
def test_safe_filename_sanitises(url: str, expected: str) -> None:
    """Spaces, accents, query strings and path tricks collapse to a plain name."""
    assert da._safe_filename_from_url(url) == expected


def test_safe_filename_never_contains_path_separators() -> None:
    """Whatever the URL holds, the stem is a single safe path component."""
    stem = da._safe_filename_from_url("https://h/a/..%2F..%2F..%2Fwindows%2Fsystem32%5Cx.mp3")
    assert "/" not in stem and "\\" not in stem and ".." not in stem


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example/",
        "https://cdn.example/path/",
        "https://cdn.example/" + "".join(map(chr, (0x65E5, 0x672C))) + ".mp3",
        "https://cdn.example/CON.mp3",
        "https://cdn.example/nul.mp3",
        "https://cdn.example/Lpt1.mp3",
    ],
)
def test_safe_filename_falls_back_to_hash_stem(url: str) -> None:
    """Empty or reserved names get a stable hash-based stem instead of an invalid file name."""
    expected_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[: da.URL_HASH_LENGTH]
    assert da._safe_filename_from_url(url) == f"{da.FALLBACK_STEM_PREFIX}_{expected_hash}"


def test_safe_filename_is_length_limited() -> None:
    """Very long names are truncated."""
    stem = da._safe_filename_from_url("https://cdn.example/" + "a" * 500 + ".mp3")
    assert len(stem) == da.MAX_FILENAME_STEM_LENGTH


# --- download_audio ---


def test_download_audio_converts_and_removes_temp_file(
    monkeypatch: pytest.MonkeyPatch, audio_dir: Path
) -> None:
    """The WAV name is returned, the WAV exists and the raw download is gone."""
    monkeypatch.setattr(da.requests, "get", lambda *a, **k: FakeStream([b"abc", b"def"]))
    monkeypatch.setattr(da, "_convert_to_wav", fake_convert)

    name = da.download_audio("https://cdn.example/dir/Ep One.mp3", str(audio_dir))

    assert name == "Ep_One.wav"
    assert sorted(p.name for p in audio_dir.iterdir()) == ["Ep_One.wav"]


def test_download_audio_passes_timeout_and_streams(
    monkeypatch: pytest.MonkeyPatch, audio_dir: Path
) -> None:
    """The request is streamed with a timeout."""
    seen: dict = {}

    def fake_get(url: str, **kwargs: object) -> FakeStream:
        seen.update(kwargs)
        return FakeStream([b"x"])

    monkeypatch.setattr(da.requests, "get", fake_get)
    monkeypatch.setattr(da, "_convert_to_wav", fake_convert)

    da.download_audio("https://cdn.example/a.m4a", str(audio_dir))

    assert seen["stream"] is True
    assert seen["timeout"] == da.DOWNLOAD_TIMEOUT_SECONDS


def test_download_audio_http_error_leaves_no_partial_file(
    monkeypatch: pytest.MonkeyPatch, audio_dir: Path
) -> None:
    """An HTTP error propagates and no download or WAV file remains."""
    monkeypatch.setattr(da.requests, "get", lambda *a, **k: FakeStream([], status_code=404))

    with pytest.raises(requests.HTTPError):
        da.download_audio("https://cdn.example/a.mp3", str(audio_dir))

    assert list(audio_dir.iterdir()) == []


def test_download_audio_empty_download_is_rejected(
    monkeypatch: pytest.MonkeyPatch, audio_dir: Path
) -> None:
    """A zero-byte download raises and is cleaned up."""
    monkeypatch.setattr(da.requests, "get", lambda *a, **k: FakeStream([]))

    with pytest.raises(RuntimeError, match="empty"):
        da.download_audio("https://cdn.example/a.mp3", str(audio_dir))

    assert list(audio_dir.iterdir()) == []


def test_download_audio_interrupted_stream_leaves_no_partial_file(
    monkeypatch: pytest.MonkeyPatch, audio_dir: Path
) -> None:
    """A connection drop mid-download removes the partial file."""

    class Broken(FakeStream):
        def iter_content(self, chunk_size: int):
            yield b"partial"
            raise requests.ConnectionError("reset")

    monkeypatch.setattr(da.requests, "get", lambda *a, **k: Broken([]))

    with pytest.raises(requests.ConnectionError):
        da.download_audio("https://cdn.example/a.mp3", str(audio_dir))

    assert list(audio_dir.iterdir()) == []


def test_download_audio_conversion_failure_removes_both_files(
    monkeypatch: pytest.MonkeyPatch, audio_dir: Path
) -> None:
    """A failed conversion deletes the download and any truncated WAV."""

    def failing_convert(source: str, wav: str) -> None:
        Path(wav).write_bytes(b"half")
        raise ValueError("bad audio")

    monkeypatch.setattr(da.requests, "get", lambda *a, **k: FakeStream([b"data"]))
    monkeypatch.setattr(da, "_convert_to_wav", failing_convert)

    with pytest.raises(RuntimeError, match="Audio conversion failed"):
        da.download_audio("https://cdn.example/a.mp3", str(audio_dir))

    assert list(audio_dir.iterdir()) == []


# --- _remove_file ---


def test_remove_file_missing_is_a_noop(tmp_path: Path) -> None:
    """Removing a file that does not exist does nothing."""
    da._remove_file(str(tmp_path / "absent"))


def test_remove_file_retries_then_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A persistently locked file is retried, then reported without raising."""
    target = tmp_path / "locked.download"
    target.write_bytes(b"x")
    attempts: list[str] = []

    def locked(path: str) -> None:
        attempts.append(path)
        raise PermissionError("in use")

    monkeypatch.setattr(da.os, "remove", locked)
    monkeypatch.setattr(da.time, "sleep", lambda s: None)

    da._remove_file(str(target))

    assert len(attempts) == da.REMOVE_RETRIES
    assert "could not delete" in capsys.readouterr().err
