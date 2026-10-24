"""Tests for video_handler.py: error classification, download reuse, upload retries."""

from types import SimpleNamespace

import httplib2
import pytest
from googleapiclient.errors import HttpError

import video_handler
from video_handler import VideoDownloader, fatal_upload_reason, upload_video


def http_error(status, reason="backendError"):
    content = (
        '{"error": {"code": %d, "message": "%s", "errors": [{"reason": "%s"}]}}'
        % (status, reason, reason)
    ).encode()
    return HttpError(httplib2.Response({"status": status}), content)


def make_config(**overrides):
    values = dict(
        auto_confirm=True, dry_run=False, require_native_quality=True,
        socket_timeout=1, download_retries=1, fragment_retries=1,
        http_chunk_size=1024, cookies_from_browser="",
        get_privacy_status=lambda: "private", get_chunk_size_bytes=lambda: 1024,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fatal_upload_reason_classifies_run_stopping_errors():
    assert fatal_upload_reason(http_error(400, "uploadLimitExceeded")) == "Upload limit exceeded"
    assert fatal_upload_reason(http_error(403, "quotaExceeded")) == "API quota exceeded"
    assert fatal_upload_reason(http_error(500)) is None
    assert fatal_upload_reason(ValueError("anything")) is None


def test_progress_hook_handles_unknown_totals(capsys):
    video_handler._progress_hook({"status": "downloading", "downloaded_bytes": 10})
    video_handler._progress_hook({"status": "finished"})
    assert "..." in capsys.readouterr().out


def test_find_file_and_file_size_helpers(tmp_path):
    (tmp_path / "abc.webm").write_bytes(b"x" * 2048)
    found = VideoDownloader._find_file_with_extensions(str(tmp_path / "abc"), ["mp4", "webm"])
    assert found.endswith("abc.webm")
    assert VideoDownloader._find_file_with_extensions(str(tmp_path / "zzz"), ["mp4"]) is None
    assert VideoDownloader._get_file_size(found) == "2.0KB"
    assert VideoDownloader._get_file_size(None) is None


def test_load_info_json_tolerates_corrupt_file(tmp_path):
    (tmp_path / "v.info.json").write_text("{broken", encoding="utf-8")
    downloader = VideoDownloader(make_config(), None)
    assert downloader._load_info_json("v", str(tmp_path)) == {}
    assert downloader._load_info_json("missing", str(tmp_path)) == {}


class FakeYoutubeDL:
    """yt-dlp stand-in that records calls and optionally writes the output files."""

    calls = []
    raise_error = None
    output_dir = None

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        FakeYoutubeDL.calls.append(url)
        if FakeYoutubeDL.raise_error:
            raise FakeYoutubeDL.raise_error
        video_id = url.split("watch?v=")[-1]
        base = f"{FakeYoutubeDL.output_dir}/{video_id}"
        with open(base + ".mp4", "wb") as f:
            f.write(b"video")
        with open(base + ".info.json", "w", encoding="utf-8") as f:
            f.write('{"title": "T"}')
        return {"id": video_id, "title": "T"}


@pytest.fixture
def fake_ydl(monkeypatch, tmp_path):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.raise_error = None
    FakeYoutubeDL.output_dir = str(tmp_path / "downloads")
    monkeypatch.setattr(video_handler.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


def no_input(*args, **kwargs):
    raise AssertionError("unexpected prompt")


def test_download_reuses_existing_file_with_metadata(fake_ydl, paths, monkeypatch):
    out = paths.download_dir
    (out / "vid.mp4").write_bytes(b"v")
    (out / "vid.info.json").write_text('{"title": "Kept"}', encoding="utf-8")
    monkeypatch.setattr("builtins.input", no_input)
    result = VideoDownloader(make_config(), None).download(
        "https://www.youtube.com/watch?v=vid", str(out)
    )
    assert result["success"] and result["info"] == {"title": "Kept"}
    assert fake_ydl.calls == []


def test_download_redownloads_when_metadata_is_missing(fake_ydl, paths):
    out = paths.download_dir
    (out / "vid.mp4").write_bytes(b"stale")
    result = VideoDownloader(make_config(), None).download(
        "https://www.youtube.com/watch?v=vid", str(out)
    )
    assert fake_ydl.calls == ["https://www.youtube.com/watch?v=vid"]
    assert result["success"] and result["info"]["id"] == "vid"


def test_download_failure_returns_unsuccessful_result(fake_ydl, paths):
    fake_ydl.raise_error = RuntimeError("ERROR: ERROR: network down")
    logger = SimpleNamespace(log_error=lambda msg: logged.append(msg))
    logged = []
    result = VideoDownloader(make_config(), logger).download(
        "https://www.youtube.com/watch?v=vid", str(paths.download_dir)
    )
    assert not result["success"]
    assert logged == ["Download failed: network down"]


def test_unavailable_format_does_not_prompt_in_auto_confirm(fake_ydl, paths, monkeypatch):
    fake_ydl.raise_error = RuntimeError("Requested format is not available")
    monkeypatch.setattr("builtins.input", no_input)
    logger = SimpleNamespace(log_error=lambda msg: None)
    result = VideoDownloader(make_config(), logger).download(
        "https://www.youtube.com/watch?v=vid", str(paths.download_dir)
    )
    assert not result["success"]
    assert fake_ydl.calls == ["https://www.youtube.com/watch?v=vid"]


class FakeUploadRequest:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def next_chunk(self):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeService:
    def __init__(self, outcomes, thumbnail_error=None):
        self.request = FakeUploadRequest(outcomes)
        self.thumbnail_error = thumbnail_error
        self.thumbnail_calls = 0
        self.body = None

    def videos(self):
        def insert(part, body, media_body):
            self.body = body
            return self.request
        return SimpleNamespace(insert=insert)

    def thumbnails(self):
        def set_thumbnail(videoId, media_body):
            def execute():
                self.thumbnail_calls += 1
                if self.thumbnail_error:
                    raise self.thumbnail_error
            return SimpleNamespace(execute=execute)
        return SimpleNamespace(set=set_thumbnail)


class FakeQuotaClient:
    def __init__(self):
        self.costs = []
        self.saved = 0

    def add_quota_cost(self, cost):
        self.costs.append(cost)

    def save_quota_state(self):
        self.saved += 1


@pytest.fixture
def upload_env(monkeypatch):
    monkeypatch.setattr(video_handler, "MediaFileUpload", lambda *a, **kw: object())
    sleeps = []
    monkeypatch.setattr(video_handler.time, "sleep", sleeps.append)
    return sleeps


def video_data(thumbnail=None, info=None):
    return {
        "video_file": "video.mp4", "thumbnail_file": thumbnail,
        "info": info if info is not None else {"title": "T", "tags": None},
    }


def test_dry_run_upload_makes_no_api_calls():
    result = upload_video(None, video_data(), make_config(dry_run=True), None)
    assert result == "DRY_RUN_VIDEO_ID"


def test_upload_retries_transient_errors_then_succeeds(upload_env):
    service = FakeService([http_error(503), ConnectionResetError("reset"), (None, {"id": "new1"})])
    quota = FakeQuotaClient()
    assert upload_video(service, video_data(), make_config(), quota) == "new1"
    assert upload_env == [2, 4]
    assert quota.costs == [video_handler.QUOTA_VIDEO_UPLOAD]
    assert service.body["snippet"]["tags"] == []


def test_upload_backoff_doubles_on_consecutive_failures(upload_env):
    service = FakeService([http_error(500), http_error(500), http_error(502), (None, {"id": "x"})])
    upload_video(service, video_data(), make_config(), FakeQuotaClient())
    assert upload_env == [2, 4, 8]


def test_upload_does_not_retry_permanent_errors(upload_env):
    service = FakeService([http_error(403, "forbidden")])
    with pytest.raises(HttpError):
        upload_video(service, video_data(), make_config(), FakeQuotaClient())
    assert upload_env == []


def test_upload_gives_up_after_max_retries(upload_env):
    errors = [http_error(503)] * (video_handler.UPLOAD_MAX_RETRIES + 1)
    with pytest.raises(HttpError):
        upload_video(FakeService(errors), video_data(), make_config(), FakeQuotaClient())
    assert len(upload_env) == video_handler.UPLOAD_MAX_RETRIES


def test_thumbnail_failure_does_not_fail_upload(upload_env, tmp_path):
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"jpg")
    service = FakeService([(None, {"id": "new1"})], thumbnail_error=RuntimeError("bad image"))
    quota = FakeQuotaClient()
    assert upload_video(service, video_data(str(thumb)), make_config(), quota) == "new1"
    assert service.thumbnail_calls == 1
    assert quota.costs == [video_handler.QUOTA_VIDEO_UPLOAD, video_handler.QUOTA_THUMBNAIL_UPLOAD]


def test_webp_thumbnail_is_converted_and_temp_removed(upload_env, tmp_path):
    PIL_Image = pytest.importorskip("PIL.Image")
    thumb = tmp_path / "t.webp"
    try:
        PIL_Image.new("RGB", (4, 4), "red").save(thumb, "WEBP")
    except (OSError, KeyError):
        pytest.skip("Pillow built without WebP support")
    service = FakeService([(None, {"id": "new1"})])
    upload_video(service, video_data(str(thumb)), make_config(), FakeQuotaClient())
    assert service.thumbnail_calls == 1
    assert not (tmp_path / "t_thumb.jpg").exists()
