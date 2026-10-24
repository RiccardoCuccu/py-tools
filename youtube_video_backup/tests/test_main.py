"""Tests for main.py: prompts, upload retry policy, source selection, full run."""

import sys
from types import SimpleNamespace

import pytest

import main
from utils import StorageManager

from test_video_handler import http_error


def make_config(**overrides):
    values = dict(
        auto_confirm=True, dry_run=False, delete_after_upload=False,
        source_channel_id="UC1", backup_channel_id="UC2", download_delay=0,
        initial_full_backup=True,
    )
    values.update(overrides)
    config = SimpleNamespace(**values)
    config.should_do_full_backup = (
        lambda state: config.initial_full_backup and not state.get("full_backup_completed", False)
    )
    return config


def video(video_id, published):
    return {"id": video_id, "title": video_id, "published": published, "url": f"u/{video_id}"}


def feed_input(monkeypatch, answers):
    queue = list(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": queue.pop(0))


def test_confirm_backup_answers(monkeypatch):
    assert main.confirm_backup(auto_confirm=True) is True
    feed_input(monkeypatch, ["y", "n"])
    assert main.confirm_backup() is True
    assert main.confirm_backup() is False


def test_confirm_backup_quit_exits(monkeypatch):
    feed_input(monkeypatch, ["q"])
    with pytest.raises(SystemExit) as exc:
        main.confirm_backup()
    assert exc.value.code == 0


def test_ask_retry_operation(monkeypatch):
    assert main.ask_retry_operation("upload", auto_confirm=True) is False
    feed_input(monkeypatch, ["x", "r", "s"])
    assert main.ask_retry_operation("upload") is True
    assert main.ask_retry_operation("upload") is False


def test_run_upload_reraises_fatal_errors(monkeypatch):
    def failing(*args):
        raise http_error(400, "uploadLimitExceeded")
    monkeypatch.setattr(main, "upload_video", failing)
    youtube = SimpleNamespace(service=None)
    with pytest.raises(Exception, match="uploadLimitExceeded"):
        main._run_upload(youtube, {}, make_config(), SimpleNamespace())


def test_run_upload_reraises_quota_exceeded(monkeypatch):
    def failing(*args):
        raise http_error(403, "quotaExceeded")
    monkeypatch.setattr(main, "upload_video", failing)
    with pytest.raises(Exception, match="quotaExceeded"):
        main._run_upload(SimpleNamespace(service=None), {}, make_config(), SimpleNamespace())


def test_run_upload_skips_other_errors_in_auto_mode(monkeypatch):
    def failing(*args):
        raise RuntimeError("transient")
    monkeypatch.setattr(main, "upload_video", failing)
    errors = []
    logger = SimpleNamespace(log_error=errors.append)
    assert main._run_upload(SimpleNamespace(service=None), {}, make_config(), logger) is None
    assert len(errors) == 1


class FakeYouTube:
    def __init__(self, storage=None, rss=(), api=()):
        self.storage = storage
        self.rss = list(rss)
        self.api = list(api)
        self.service = "service"
        self.quota_today = 0
        self.calls = []

    def get_quota_today(self):
        return self.quota_today

    def get_quota_usage(self):
        return 0

    def get_channel_videos_rss(self, channel_id):
        self.calls.append("rss")
        return self.rss

    def get_all_channel_videos_api(self, channel_id):
        self.calls.append("api")
        return self.api


ARGS = SimpleNamespace(use_cache=False, re_fetch=False, ignore_quota_warning=False)


def test_incremental_mode_merges_rss_into_cache_even_with_auto_confirm():
    storage = StorageManager(SimpleNamespace())
    storage.update_channel_videos_cache([video("old", "2023")], "UC1")
    youtube = FakeYouTube(rss=[video("old", "2023"), video("new", "2024")])
    result = main._select_source_videos(
        ARGS, make_config(initial_full_backup=False), storage, youtube, set(), False
    )
    videos, full = result
    assert [v["id"] for v in videos] == ["old", "new"]
    assert full is False
    assert [v["id"] for v in storage.get_cached_videos("UC1")] == ["old", "new"]


def test_cache_from_another_channel_is_not_reused():
    storage = StorageManager(SimpleNamespace())
    storage.update_channel_videos_cache([video("foreign", "2023")], "OTHER")
    youtube = FakeYouTube(rss=[video("new", "2024")])
    videos, _ = main._select_source_videos(
        ARGS, make_config(initial_full_backup=False), storage, youtube, set(), False
    )
    assert [v["id"] for v in videos] == ["new"]


def test_unfinished_full_backup_resumes_from_cache_and_stays_full():
    storage = StorageManager(SimpleNamespace())
    storage.update_channel_videos_cache([video("a", "2023"), video("b", "2024")], "UC1")
    youtube = FakeYouTube()
    videos, full = main._select_source_videos(ARGS, make_config(), storage, youtube, set(), True)
    assert len(videos) == 2
    assert full is True
    assert youtube.calls == []


def test_re_fetch_clears_cache_and_uses_api():
    storage = StorageManager(SimpleNamespace())
    storage.update_channel_videos_cache([video("a", "2023")], "UC1")
    youtube = FakeYouTube(api=[video("a", "2023"), video("b", "2024")])
    args = SimpleNamespace(use_cache=False, re_fetch=True, ignore_quota_warning=False)
    videos, full = main._select_source_videos(args, make_config(), storage, youtube, set(), True)
    assert youtube.calls == ["api"]
    assert full is True
    assert len(storage.get_cached_videos("UC1")) == 2


def test_full_backup_cancelled_when_quota_short_and_user_declines(monkeypatch):
    storage = StorageManager(SimpleNamespace())
    youtube = FakeYouTube()
    youtube.quota_today = main.QUOTA_DAILY_LIMIT
    feed_input(monkeypatch, ["n"])
    assert main._select_source_videos(ARGS, make_config(), storage, youtube, set(), True) is None
    assert youtube.calls == []


def make_video_data(tmp_path):
    video_file = tmp_path / "v.mp4"
    thumb = tmp_path / "v.jpg"
    video_file.write_bytes(b"v")
    thumb.write_bytes(b"t")
    return {"video_file": str(video_file), "thumbnail_file": str(thumb), "info": {"channel": "Chan"}}


def test_record_success_dry_run_leaves_no_trace(paths, tmp_path):
    storage = StorageManager(SimpleNamespace())
    logger = SimpleNamespace(log_backed_up_video=lambda *a: pytest.fail("logged in dry run"))
    result = main._record_success(
        storage, logger, make_config(dry_run=True), video("a", "2024"),
        make_video_data(tmp_path), "DRY_RUN_VIDEO_ID",
    )
    assert result is None
    assert storage.load_archive() == set()


def test_record_success_archives_and_preserves_quota_state(paths, tmp_path):
    storage = StorageManager(SimpleNamespace())
    storage.save_state({"total_videos_backed_up": 2, "quota_used_today": 1650,
                        "quota_reset_date": "2024-05-01"})
    logged = []
    logger = SimpleNamespace(log_backed_up_video=lambda *a: logged.append(a))
    data = make_video_data(tmp_path)
    state = main._record_success(
        storage, logger, make_config(delete_after_upload=True), video("a", "2024"), data, "new1",
    )
    assert storage.load_archive() == {"a"}
    assert logged == [("a", "a", "Chan", "new1")]
    assert state["total_videos_backed_up"] == 3
    assert state["quota_used_today"] == 1650
    assert not (tmp_path / "v.mp4").exists() and not (tmp_path / "v.jpg").exists()


def test_first_run_setup_runs_before_validation(monkeypatch):
    order = []
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(main, "first_run_setup", lambda: order.append("setup") or False)
    monkeypatch.setattr(main, "validate_configuration", lambda: order.append("validate"))
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1
    assert order == ["setup"]


class FakeDownloader:
    def __init__(self, config, logger):
        pass

    def download(self, url, output_dir):
        return {"success": True, "video_file": "f.mp4", "thumbnail_file": None,
                "info": {"channel": "Chan", "title": "T"}}


def run_main(monkeypatch, config, rss=(), api=(), uploaded=None, channel_id="UC2"):
    """Run main() with every external collaborator replaced by a fake."""
    uploaded = uploaded if uploaded is not None else []
    holder = {}

    def make_youtube(cfg, storage):
        fake = FakeYouTube(storage, rss=rss, api=api)
        fake.authenticate = lambda: None
        fake.get_authenticated_channel_id = lambda: channel_id
        fake.show_quota_status = lambda: None
        holder["youtube"] = fake
        return fake

    def fake_upload(service, data, cfg, youtube):
        uploaded.append(data)
        # The real client persists its quota counters right before uploading
        youtube.storage.update_state(quota_used_today=1650, quota_reset_date="2024-05-01")
        return "DRY_RUN_VIDEO_ID" if cfg.dry_run else "new1"

    monkeypatch.setattr(sys, "argv", ["main.py", "--auto-confirm"])
    monkeypatch.setattr(main, "first_run_setup", lambda: True)
    monkeypatch.setattr(main, "validate_configuration", lambda: None)
    monkeypatch.setattr(main, "Config", SimpleNamespace(load=lambda: config))
    monkeypatch.setattr(main, "YouTubeClient", make_youtube)
    monkeypatch.setattr(main, "VideoDownloader", FakeDownloader)
    monkeypatch.setattr(main, "upload_video", fake_upload)
    main.main()
    return uploaded


def test_full_run_records_progress_without_clobbering_quota(monkeypatch, paths):
    api = [video("a", "2023-01-01T00:00:00Z"), video("b", "2024-01-01T00:00:00Z")]
    uploaded = run_main(monkeypatch, make_config(), api=api)
    storage = StorageManager(SimpleNamespace())
    state = storage.load_state()
    assert len(uploaded) == 2
    assert storage.load_archive() == {"a", "b"}
    assert state["full_backup_completed"] is True
    assert state["total_videos_backed_up"] == 2
    assert state["quota_used_today"] == 1650  # not reset by the main loop's own saves


def test_dry_run_does_not_archive_or_complete_full_backup(monkeypatch, paths):
    api = [video("a", "2023-01-01T00:00:00Z")]
    run_main(monkeypatch, make_config(dry_run=True), api=api)
    storage = StorageManager(SimpleNamespace())
    assert storage.load_archive() == set()
    assert storage.load_state()["full_backup_completed"] is False


def test_incremental_run_finds_new_video_despite_cache(monkeypatch, paths):
    storage = StorageManager(SimpleNamespace())
    storage.update_channel_videos_cache([video("a", "2023-01-01T00:00:00Z")], "UC1")
    storage.save_to_archive("a")
    storage.save_state({"full_backup_completed": True, "total_videos_backed_up": 1})
    rss = [video("a", "2023-01-01T00:00:00Z"), video("b", "2024-01-01T00:00:00Z")]
    uploaded = run_main(monkeypatch, make_config(initial_full_backup=False), rss=rss)
    assert len(uploaded) == 1
    assert storage.load_archive() == {"a", "b"}


def test_verify_backup_channel_accepts_matching_channel():
    youtube = SimpleNamespace(get_authenticated_channel_id=lambda: "UC2")
    main.verify_backup_channel(youtube, make_config())


def test_verify_backup_channel_rejects_mismatch(capsys):
    youtube = SimpleNamespace(get_authenticated_channel_id=lambda: "UCother")
    with pytest.raises(SystemExit) as exc:
        main.verify_backup_channel(youtube, make_config())
    assert exc.value.code == 1
    assert "does not match" in capsys.readouterr().out


def test_verify_backup_channel_rejects_missing_channel(capsys):
    youtube = SimpleNamespace(get_authenticated_channel_id=lambda: None)
    with pytest.raises(SystemExit) as exc:
        main.verify_backup_channel(youtube, make_config())
    assert exc.value.code == 1
    assert "no YouTube channel" in capsys.readouterr().out


@pytest.mark.parametrize("dry_run", [False, True])
def test_channel_mismatch_aborts_before_any_download_or_upload(monkeypatch, paths, dry_run):
    uploaded = []
    api = [video("a", "2023-01-01T00:00:00Z")]
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, make_config(dry_run=dry_run), api=api,
                 uploaded=uploaded, channel_id="UCother")
    assert exc.value.code == 1
    assert uploaded == []
    assert StorageManager(SimpleNamespace()).load_archive() == set()
