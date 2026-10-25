"""Tests for main: argument parsing, source collection and the full run."""

import csv
import json

import pytest
from google.auth.exceptions import TransportError

import main
from conftest import http_error, make_video
from watch_later import WatchLaterError


@pytest.fixture
def env(paths, fake_youtube, monkeypatch):
    """Ready-to-run environment: credentials present, API and yt-dlp faked."""
    paths.client_secret_file.write_text("{}", encoding="utf-8")

    def fake_authenticate(self):
        self.service = fake_youtube
        return fake_youtube

    monkeypatch.setattr(main.YouTubeClient, "authenticate", fake_authenticate)
    state = {"wl_ids": [], "wl_error": None, "wl_calls": []}

    def fake_wl(browser, cookies_file):
        state["wl_calls"].append((browser, cookies_file))
        if state["wl_error"]:
            raise WatchLaterError(state["wl_error"])
        return state["wl_ids"]

    monkeypatch.setattr(main, "fetch_watch_later_ids", fake_wl)
    fake_youtube.videos_data = {}
    return state


def _add(fake, playlist_id, title, ids, privacy="unlisted"):
    fake.playlists_data.append((playlist_id, title))
    fake.playlist_items[playlist_id] = ids
    for vid in ids:
        fake.videos_data.setdefault(vid, make_video(vid, privacy))


def test_parse_args_defaults():
    args = main._parse_args([])
    assert args.playlist == [] and not args.liked and not args.no_watch_later
    assert args.format == main.DEFAULT_FORMAT and args.output is None


def test_parse_args_playlist_is_repeatable_and_accepts_urls():
    args = main._parse_args([
        "-p", "PL1", "--playlist", "https://www.youtube.com/playlist?list=PL2",
    ])
    assert args.playlist == ["PL1", "PL2"]


def test_parse_args_rejects_bad_playlist_and_format():
    with pytest.raises(SystemExit):
        main._parse_args(["-p", "not valid!"])
    with pytest.raises(SystemExit):
        main._parse_args(["-f", "xml"])


def test_main_returns_error_without_credentials(paths, capsys):
    assert main.main(["-o", str(paths.config_dir.parent / "r.md")]) == 1
    assert "client_secret.json" in capsys.readouterr().out


def test_default_scan_covers_own_playlists_and_watch_later(env, fake_youtube, tmp_path):
    _add(fake_youtube, "PL1", "Music", ["a", "b"])
    _add(fake_youtube, "PL2", "Misc", ["b", "p"], privacy="public")
    env["wl_ids"] = ["d", "a"]
    fake_youtube.videos_data["d"] = make_video("d", "unlisted")
    out = tmp_path / "r.json"
    assert main.main(["-f", "json", "-o", str(out)]) == 0
    data = {v["video_id"]: v for v in json.loads(out.read_text(encoding="utf-8"))}
    assert set(data) == {"a", "b", "d"}
    assert data["a"]["playlists"] == ["Music", "Watch Later"]
    assert data["b"]["playlists"] == ["Music", "Misc"]


def test_no_watch_later_skips_yt_dlp(env, fake_youtube, tmp_path):
    _add(fake_youtube, "PL1", "Music", ["a"])
    assert main.main(["--no-watch-later", "-o", str(tmp_path / "r.md")]) == 0
    assert env["wl_calls"] == []


def test_include_watch_later_config_false_skips_yt_dlp(
    env, fake_youtube, tmp_path, monkeypatch
):
    monkeypatch.setattr(main, "INCLUDE_WATCH_LATER", False)
    _add(fake_youtube, "PL1", "Music", ["a"])
    main.main(["-o", str(tmp_path / "r.md")])
    assert env["wl_calls"] == []


def test_watch_later_failure_warns_and_scan_continues(
    env, fake_youtube, tmp_path, capsys, paths
):
    _add(fake_youtube, "PL1", "Music", ["a"])
    env["wl_error"] = "cookie database is locked"
    out = tmp_path / "r.md"
    assert main.main(["-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Watch Later skipped" in text and "--cookies-file" in text
    assert "[Title a]" in out.read_text(encoding="utf-8")
    assert "Watch Later skipped" in paths.log_file.read_text(encoding="utf-8")


def test_cli_cookie_flags_override_config(env, fake_youtube, tmp_path):
    main.main([
        "--browser", "firefox", "--cookies-file", "c.txt",
        "-o", str(tmp_path / "r.md"),
    ])
    assert env["wl_calls"] == [("firefox", "c.txt")]


def test_playlist_flag_scans_only_that_playlist(env, fake_youtube, tmp_path):
    _add(fake_youtube, "PL1", "Music", ["a"])
    _add(fake_youtube, "PL2", "Misc", ["b"])
    out = tmp_path / "r.json"
    main.main(["-p", "PL2", "-f", "json", "-o", str(out)])
    ids = [v["video_id"] for v in json.loads(out.read_text(encoding="utf-8"))]
    assert ids == ["b"]
    assert env["wl_calls"] == []


def test_playlist_wl_routes_to_yt_dlp(env, fake_youtube, tmp_path):
    env["wl_ids"] = ["w"]
    fake_youtube.videos_data["w"] = make_video("w")
    out = tmp_path / "r.json"
    main.main(["-p", "WL", "-f", "json", "-o", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["playlists"] == ["Watch Later"]


def test_unreadable_playlist_is_logged_and_skipped(env, fake_youtube, tmp_path, capsys):
    _add(fake_youtube, "PL1", "Music", ["a"])
    fake_youtube.playlist_items["PL2"] = http_error(404)
    out = tmp_path / "r.json"
    assert main.main(["-p", "PL2", "-p", "PL1", "-f", "json", "-o", str(out)]) == 0
    assert "Could not read playlist" in capsys.readouterr().out
    assert [v["video_id"] for v in json.loads(out.read_text(encoding="utf-8"))] == ["a"]


def test_liked_flag_uses_liked_videos_without_extra_classification(
    env, fake_youtube, tmp_path
):
    fake_youtube.videos_data = {
        "x": make_video("x", "unlisted"), "y": make_video("y", "public"),
    }
    fake_youtube.liked = ["x", "y"]
    out = tmp_path / "r.json"
    assert main.main(["--liked", "-f", "json", "-o", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [v["video_id"] for v in data] == ["x"]
    assert data[0]["playlists"] == ["Liked videos"]
    assert fake_youtube.videos_id_batches == []


def test_liked_combined_with_playlist(env, fake_youtube, tmp_path):
    _add(fake_youtube, "PL1", "Music", ["a"])
    fake_youtube.videos_data["x"] = make_video("x")
    fake_youtube.liked = ["x"]
    out = tmp_path / "r.json"
    main.main(["-p", "PL1", "-l", "-f", "json", "-o", str(out)])
    ids = {v["video_id"] for v in json.loads(out.read_text(encoding="utf-8"))}
    assert ids == {"a", "x"}


def test_summary_reports_counts_skipped_and_quota(env, fake_youtube, tmp_path, capsys):
    _add(fake_youtube, "PL1", "Music", ["a", "gone"])
    del fake_youtube.videos_data["gone"]
    main.main(["--no-watch-later", "-o", str(tmp_path / "r.md")])
    out = capsys.readouterr().out
    assert "Videos checked: 2" in out
    assert "Unlisted found: 1" in out
    assert "Skipped (private or deleted): 1" in out
    assert "API quota used: 3 units" in out


def test_csv_format_output(env, fake_youtube, tmp_path):
    _add(fake_youtube, "PL1", "Music", ["a"])
    out = tmp_path / "r.csv"
    main.main(["--no-watch-later", "-f", "csv", "-o", str(out)])
    rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[1][3] == "a"


def test_default_output_goes_to_reports_dir(env, fake_youtube, paths):
    _add(fake_youtube, "PL1", "Music", ["a"])
    main.main(["--no-watch-later"])
    files = list(paths.reports_dir.iterdir())
    assert len(files) == 1 and files[0].name.startswith("unlisted_")


def test_api_failure_returns_error_exit(
    env, fake_youtube, tmp_path, capsys, monkeypatch
):
    _add(fake_youtube, "PL1", "Music", ["a"])

    def boom(self, ids, known=None):
        raise http_error(403)

    monkeypatch.setattr(main.YouTubeClient, "fetch_videos", boom)
    code = main.main(["--no-watch-later", "-o", str(tmp_path / "r.md")])
    assert code == 1
    assert "YouTube API request failed" in capsys.readouterr().out


def test_playlist_title_lookup_failure_is_logged_and_skipped(
    env, fake_youtube, tmp_path, capsys, monkeypatch
):
    _add(fake_youtube, "PL1", "Music", ["a"])
    original = main.YouTubeClient.get_playlist_title

    def flaky(self, playlist_id):
        if playlist_id == "PLbad":
            raise http_error(500)
        return original(self, playlist_id)

    monkeypatch.setattr(main.YouTubeClient, "get_playlist_title", flaky)
    out = tmp_path / "r.json"
    assert main.main(["-p", "PLbad", "-p", "PL1", "-f", "json", "-o", str(out)]) == 0
    assert "Could not read playlist 'PLbad'" in capsys.readouterr().out
    assert [v["video_id"] for v in json.loads(out.read_text(encoding="utf-8"))] == ["a"]


def test_liked_failure_is_logged_and_other_sources_continue(
    env, fake_youtube, tmp_path, capsys, monkeypatch
):
    _add(fake_youtube, "PL1", "Music", ["a"])

    def boom(self):
        raise http_error(500)

    monkeypatch.setattr(main.YouTubeClient, "list_liked_videos", boom)
    out = tmp_path / "r.json"
    assert main.main(["-p", "PL1", "-l", "-f", "json", "-o", str(out)]) == 0
    assert "Could not read liked videos" in capsys.readouterr().out
    assert [v["video_id"] for v in json.loads(out.read_text(encoding="utf-8"))] == ["a"]


def test_empty_watch_later_warns_naming_cookie_source(
    env, fake_youtube, tmp_path, capsys, paths
):
    _add(fake_youtube, "PL1", "Music", ["a"])
    env["wl_ids"] = []
    main.main(["--browser", "firefox", "-o", str(tmp_path / "r.md")])
    out = capsys.readouterr().out
    assert "Watch Later returned no videos using firefox browser cookies" in out
    assert "Watch Later returned no videos" in paths.log_file.read_text(
        encoding="utf-8"
    )


def test_empty_watch_later_warning_names_cookies_file(
    env, fake_youtube, tmp_path, capsys
):
    _add(fake_youtube, "PL1", "Music", ["a"])
    main.main(["--cookies-file", "c.txt", "-o", str(tmp_path / "r.md")])
    assert "cookies file c.txt" in capsys.readouterr().out


@pytest.mark.parametrize("error", [
    ValueError("bad client secret"), KeyError("installed"),
    OSError("no file"), TransportError("offline"),
])
def test_authentication_failure_returns_error_exit(
    env, tmp_path, capsys, monkeypatch, paths, error
):
    def fail(self):
        raise error

    monkeypatch.setattr(main.YouTubeClient, "authenticate", fail)
    assert main.main(["-o", str(tmp_path / "r.md")]) == 1
    assert "Authentication failed" in capsys.readouterr().out
    assert "Authentication failed" in paths.log_file.read_text(encoding="utf-8")
    assert not (tmp_path / "r.md").exists()


def test_invalid_playlist_argument_gives_readable_error(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main._parse_args(["-p", "not valid!"])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "not a playlist id or URL" in err and "expected a playlist id" in err


def test_output_in_missing_folder_is_created(env, fake_youtube, tmp_path):
    _add(fake_youtube, "PL1", "Music", ["a"])
    out = tmp_path / "new" / "nested" / "r.md"
    assert main.main(["--no-watch-later", "-o", str(out)]) == main.EXIT_OK
    assert out.exists()


def test_unwritable_output_returns_error_and_logs_path(
    env, fake_youtube, tmp_path, capsys, paths
):
    _add(fake_youtube, "PL1", "Music", ["a"])
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder", encoding="utf-8")
    out = blocker / "r.md"
    assert main.main(["--no-watch-later", "-o", str(out)]) == main.EXIT_ERROR
    message = capsys.readouterr().out
    assert "Could not write the report" in message and str(out) in message
    assert "Could not write the report" in paths.log_file.read_text(encoding="utf-8")
