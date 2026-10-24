"""Tests for steam_cloud_downloader: name handling, page parsing, file downloads, folder
cleanup on failure, ZIP creation, session cookies, and the login flow (browser, HTTP
session and filesystem are all faked; every output path lives in tmp_path).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import requests
from selenium.common.exceptions import TimeoutException

import steam_cloud_downloader as scd


class FakeResponse:
    """Minimal stand-in for requests.Response usable as a context manager."""

    def __init__(self, text: str = "", status_code: int = 200, chunks=(b"data",)) -> None:
        self.text = text
        self.status_code = status_code
        self._chunks = chunks

    def iter_content(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeSession:
    """Session returning scripted responses keyed by URL; records every call."""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if url not in self.responses:
            return FakeResponse(status_code=404)
        return self.responses[url]


def app_page(game: str, rows: list[tuple[str, str]]) -> str:
    """Build a remotestorageapp page with one table row per (file name, url)."""
    body = "".join(
        f"<tr><td>a</td><td>{name}</td><td>c</td><td>d</td>"
        f'<td><a href="{url}">dl</a></td></tr>'
        for name, url in rows
    )
    return (
        f'<div id="main_content" class="page_content"><h2>{game}</h2>'
        f'<table class="accountTable"><tbody>{body}</tbody></table></div>'
    )


APP_URL = "https://store.steampowered.com/account/remotestorageapp/?appid={}"


@pytest.fixture
def saves_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "steam_saves"
    monkeypatch.setattr(scd, "STEAM_SAVES_ROOT", str(root))
    monkeypatch.setattr(scd, "SCRIPT_DIR", str(tmp_path))
    return root


# Name handling

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hollow Knight: Silksong", "hollow_knight_silksong"),
        ("  --Dark Souls III!!  ", "dark_souls_iii"),
        ("", ""),
        ("***", ""),
    ],
)
def test_snake_case(text: str, expected: str) -> None:
    assert scd.snake_case(text) == expected


def test_game_folder_name_falls_back_to_appid() -> None:
    assert scd.get_game_folder_name("???", "730") == "app_730"
    assert scd.get_game_folder_name("Portal 2", "620") == "portal_2"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("save.dat", "save.dat"),
        ("dir/slot1.sav", "dir_slot1.sav"),
        ("..\\..\\evil.dll", ".._.._evil.dll"),
        ("a:b*c?.sav", "a_b_c_.sav"),
        ("trailing. ", "trailing"),
        ("con.txt", "_con.txt"),
        ("NUL", "_NUL"),
        ("..", ""),
        (".", ""),
        ("", ""),
        ("   ", ""),
        ("bad\x00name\x1f.sav", "bad_name_.sav"),
    ],
)
def test_sanitize_file_name(name: str, expected: str) -> None:
    assert scd.sanitize_file_name(name) == expected


@pytest.mark.parametrize(
    "name", ["../../x", "..\\x", "/etc/passwd", "C:\\Windows\\x", "a/../b"]
)
def test_sanitized_name_is_a_single_path_component(name: str) -> None:
    safe = scd.sanitize_file_name(name)
    assert "/" not in safe and "\\" not in safe and ":" not in safe
    assert safe not in ("", ".", "..")


def test_unique_file_name_numbers_collisions_case_insensitively() -> None:
    used: set[str] = set()
    assert scd.unique_file_name("a.sav", used) == "a.sav"
    assert scd.unique_file_name("A.SAV", used) == "A_2.SAV"
    assert scd.unique_file_name("a.sav", used) == "a_3.sav"
    assert scd.unique_file_name("noext", used) == "noext"
    assert scd.unique_file_name("noext", used) == "noext_2"


# Page parsing

def test_get_appids_deduplicates_and_sorts_numerically() -> None:
    html = (
        '<a href="remotestorageapp/?appid=730">x</a>'
        '<a href="remotestorageapp/?appid=70">y</a>'
        '<a href="remotestorageapp/?appid=730">dup</a>'
        '<a href="/other?appid=5">ignored</a>'
    )
    session = FakeSession({"https://store.steampowered.com/account/remotestorage": FakeResponse(html)})
    assert scd.get_appids_from_remotestorage(session) == ["70", "730"]
    assert session.calls[0][1]["timeout"] == scd.REQUEST_TIMEOUT_SECONDS


def test_get_appids_returns_empty_on_http_error() -> None:
    session = FakeSession({})
    assert scd.get_appids_from_remotestorage(session) == []


# Downloads

def test_download_file_writes_final_file_and_no_part(tmp_path: Path) -> None:
    target = tmp_path / "a.sav"
    session = FakeSession({"https://x/f": FakeResponse(chunks=(b"ab", b"cd"))})
    assert scd.download_file(session, "https://x/f", str(target)) is True
    assert target.read_bytes() == b"abcd"
    assert not Path(str(target) + scd.PART_FILE_SUFFIX).exists()


def test_download_file_http_error_leaves_nothing(tmp_path: Path) -> None:
    target = tmp_path / "a.sav"
    session = FakeSession({"https://x/f": FakeResponse(status_code=500)})
    assert scd.download_file(session, "https://x/f", str(target)) is False
    assert list(tmp_path.iterdir()) == []


def test_download_file_interrupted_transfer_removes_part_file(tmp_path: Path) -> None:
    target = tmp_path / "a.sav"
    broken = FakeResponse(chunks=(b"ab", requests.ConnectionError("reset")))
    session = FakeSession({"https://x/f": broken})
    assert scd.download_file(session, "https://x/f", str(target)) is False
    assert list(tmp_path.iterdir()) == []


def test_download_saves_for_app_saves_sanitized_files(saves_root: Path) -> None:
    page = app_page(
        "Portal 2",
        [("slot1.sav", "https://cdn/1"), ("../../evil.dll", "https://cdn/2")],
    )
    session = FakeSession({
        APP_URL.format(620): FakeResponse(page),
        "https://cdn/1": FakeResponse(chunks=(b"one",)),
        "https://cdn/2": FakeResponse(chunks=(b"two",)),
    })
    scd.download_saves_for_app(session, "620")

    game = saves_root / "portal_2"
    assert sorted(p.name for p in game.iterdir()) == [".._.._evil.dll", "slot1.sav"]
    # Nothing escaped the game folder
    assert not (saves_root.parent / "evil.dll").exists()
    assert not (saves_root / "evil.dll").exists()


def test_download_saves_for_app_colliding_names_do_not_overwrite(saves_root: Path) -> None:
    page = app_page("G", [("a/b.sav", "https://cdn/1"), ("a_b.sav", "https://cdn/2")])
    session = FakeSession({
        APP_URL.format(1): FakeResponse(page),
        "https://cdn/1": FakeResponse(chunks=(b"one",)),
        "https://cdn/2": FakeResponse(chunks=(b"two",)),
    })
    scd.download_saves_for_app(session, "1")
    contents = sorted(p.read_bytes() for p in (saves_root / "g").iterdir())
    assert contents == [b"one", b"two"]


def test_download_saves_for_app_failure_discards_partial_folder(saves_root: Path) -> None:
    page = app_page("G", [("ok.sav", "https://cdn/1"), ("bad.sav", "https://cdn/2")])
    session = FakeSession({
        APP_URL.format(1): FakeResponse(page),
        "https://cdn/1": FakeResponse(chunks=(b"one",)),
        "https://cdn/2": FakeResponse(status_code=500),
    })
    scd.download_saves_for_app(session, "1")
    # A leftover folder would be skipped as complete on the next run
    assert not (saves_root / "g").exists()


def test_download_saves_for_app_skips_folder_with_files(saves_root: Path) -> None:
    existing = saves_root / "g"
    existing.mkdir(parents=True)
    (existing / "keep.sav").write_bytes(b"old")
    page = app_page("G", [("new.sav", "https://cdn/1")])
    session = FakeSession({APP_URL.format(1): FakeResponse(page)})
    scd.download_saves_for_app(session, "1")
    assert [p.name for p in existing.iterdir()] == ["keep.sav"]
    assert len(session.calls) == 1  # only the app page, no file download


def test_download_saves_for_app_uses_appid_when_name_missing(saves_root: Path) -> None:
    page = (
        '<table class="accountTable"><tbody><tr><td>a</td><td>f.sav</td><td>c</td>'
        '<td>d</td><td><a href="https://cdn/1">dl</a></td></tr></tbody></table>'
    )
    session = FakeSession({
        APP_URL.format(9): FakeResponse(page),
        "https://cdn/1": FakeResponse(chunks=(b"x",)),
    })
    scd.download_saves_for_app(session, "9")
    assert (saves_root / "app_9" / "f.sav").read_bytes() == b"x"


def test_download_saves_for_app_ignores_non_http_links_and_short_rows(
    saves_root: Path,
) -> None:
    page = (
        '<div id="main_content" class="page_content"><h2>G</h2>'
        '<table class="accountTable"><tbody>'
        '<tr><td>short</td></tr>'
        '<tr><td>a</td><td>f.sav</td><td>c</td><td>d</td>'
        '<td><a href="javascript:void(0)">dl</a></td></tr>'
        '</tbody></table></div>'
    )
    session = FakeSession({APP_URL.format(1): FakeResponse(page)})
    scd.download_saves_for_app(session, "1")
    assert not (saves_root / "g").exists()
    assert len(session.calls) == 1


def test_download_saves_for_app_page_error_creates_nothing(saves_root: Path) -> None:
    session = FakeSession({APP_URL.format(1): FakeResponse(status_code=403)})
    scd.download_saves_for_app(session, "1")
    assert not saves_root.exists()


# Archive

def test_create_zip_archive_contains_files(saves_root: Path, tmp_path: Path) -> None:
    (saves_root / "g").mkdir(parents=True)
    (saves_root / "g" / "a.sav").write_bytes(b"abc")
    zip_path = scd.create_zip_archive(str(saves_root))

    assert Path(zip_path).parent == tmp_path
    assert Path(zip_path).name.endswith("_steam_cloud_backup.zip")
    with zipfile.ZipFile(zip_path) as zf:
        assert [n for n in zf.namelist() if not n.endswith("/")] == ["g/a.sav"]


def test_create_zip_archive_missing_folder_returns_empty(saves_root: Path) -> None:
    assert scd.create_zip_archive(str(saves_root)) == ""


# Session and login

def test_build_session_keeps_cookie_domain_and_path() -> None:
    session = scd.build_session([
        {"name": "sid", "value": "v", "domain": ".steampowered.com", "path": "/acc"},
    ])
    cookie = next(iter(session.cookies))
    assert (cookie.name, cookie.value) == ("sid", "v")
    assert cookie.domain == ".steampowered.com"
    assert cookie.path == "/acc"
    assert "User-Agent" in session.headers


class FakeDriver:
    """Fake Chrome driver; current_url is configurable."""

    instances: list["FakeDriver"] = []

    def __init__(self, url: str = "https://store.steampowered.com/account", cookies=None):
        self.current_url = url
        self._cookies = cookies if cookies is not None else [
            {"name": "sessionid", "value": "SECRET-VALUE", "domain": ".steampowered.com"}
        ]
        self.quit_called = False
        FakeDriver.instances.append(self)

    def get(self, url: str) -> None:
        pass

    def get_cookies(self):
        return self._cookies

    def quit(self) -> None:
        self.quit_called = True


def test_login_returns_cookies_without_printing_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeDriver.instances = []
    monkeypatch.setattr(scd, "ChromeDriver", FakeDriver)
    cookies = scd.login_with_selenium()

    assert cookies[0]["name"] == "sessionid"
    assert FakeDriver.instances[0].quit_called
    captured = capsys.readouterr()
    assert "SECRET-VALUE" not in captured.out + captured.err


def test_login_timeout_still_quits_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeDriver.instances = []
    monkeypatch.setattr(
        scd, "ChromeDriver", lambda: FakeDriver(url="https://store.steampowered.com/login/")
    )
    monkeypatch.setattr(scd, "TIMEOUT_SECONDS", 0.2)
    with pytest.raises(TimeoutException):
        scd.login_with_selenium()
    assert FakeDriver.instances[0].quit_called


def test_login_without_cookies_raises_and_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeDriver.instances = []
    monkeypatch.setattr(scd, "ChromeDriver", lambda: FakeDriver(cookies=[]))
    with pytest.raises(RuntimeError):
        scd.login_with_selenium()
    assert FakeDriver.instances[0].quit_called


# main

def test_main_archives_then_removes_originals(
    saves_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = app_page("G", [("a.sav", "https://cdn/1")])
    session = FakeSession({
        "https://store.steampowered.com/account/remotestorage":
            FakeResponse('<a href="remotestorageapp/?appid=1">g</a>'),
        APP_URL.format(1): FakeResponse(page),
        "https://cdn/1": FakeResponse(chunks=(b"x",)),
    })
    monkeypatch.setattr(scd, "login_with_selenium", lambda: [])
    monkeypatch.setattr(scd, "build_session", lambda cookies: session)

    scd.main()

    assert not saves_root.exists()
    zips = list(tmp_path.glob("*_steam_cloud_backup.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert [n for n in zf.namelist() if not n.endswith("/")] == ["g/a.sav"]


def test_main_keeps_originals_if_archive_fails(
    saves_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saves_root.mkdir()
    (saves_root / "keep.sav").write_bytes(b"x")
    session = FakeSession({
        "https://store.steampowered.com/account/remotestorage":
            FakeResponse('<a href="remotestorageapp/?appid=1">g</a>'),
    })
    monkeypatch.setattr(scd, "login_with_selenium", lambda: [])
    monkeypatch.setattr(scd, "build_session", lambda cookies: session)
    monkeypatch.setattr(scd, "download_saves_for_app", lambda s, a: None)

    def broken_zip(folder: str) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(scd, "create_zip_archive", broken_zip)
    scd.main()  # the error is reported, not raised

    assert (saves_root / "keep.sav").read_bytes() == b"x"
