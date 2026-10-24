"""Tests for lib_cache: cached library, download, validation and failure handling."""

import pytest

import lib_cache

GOOD_BODY = b"/* lib */ var LightweightCharts = {};"


def _serve(monkeypatch, body: bytes, requested: list[str] | None = None) -> None:
    """Fake fetch_bytes in lib_cache to return body."""

    def fake(url: str) -> bytes:
        if requested is not None:
            requested.append(url)
        return body

    monkeypatch.setattr(lib_cache, "fetch_bytes", fake)


class TestEnsureChartLibrary:
    def test_present_file_is_not_downloaded(self, paths, monkeypatch):
        cached = "/* cached */ var LightweightCharts = {};"
        paths.lwc_file.write_text(cached, encoding="utf-8")
        requested: list[str] = []
        _serve(monkeypatch, GOOD_BODY, requested)
        lib_cache.ensure_chart_library(str(paths.lwc_file))
        assert requested == []
        assert paths.lwc_file.read_text(encoding="utf-8") == cached

    @pytest.mark.parametrize("bad", [b"", b"var other = 1;", b"\xff\xfe\x00"])
    def test_invalid_cached_file_is_downloaded_again(
        self, paths, monkeypatch, capsys, bad
    ):
        paths.lwc_file.write_bytes(bad)
        requested: list[str] = []
        _serve(monkeypatch, GOOD_BODY, requested)
        lib_cache.ensure_chart_library(str(paths.lwc_file))
        assert requested == [lib_cache.LWC_URL]
        assert paths.lwc_file.read_bytes() == GOOD_BODY
        assert "unusable" in capsys.readouterr().err

    def test_failed_redownload_of_invalid_cache_calls_fail(
        self, paths, monkeypatch, capsys
    ):
        paths.lwc_file.write_bytes(b"")

        def offline(_url: str) -> bytes:
            raise ConnectionError("offline")

        monkeypatch.setattr(lib_cache, "fetch_bytes", offline)
        with pytest.raises(SystemExit) as info:
            lib_cache.ensure_chart_library(str(paths.lwc_file))
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert lib_cache.LWC_URL in err
        assert str(paths.lwc_file) in err

    def test_missing_file_is_downloaded_and_saved(self, paths, monkeypatch, capsys):
        requested: list[str] = []
        _serve(monkeypatch, GOOD_BODY, requested)
        lib_cache.ensure_chart_library(str(paths.lwc_file))
        assert requested == [lib_cache.LWC_URL]
        assert paths.lwc_file.read_bytes() == GOOD_BODY
        assert "Downloading the chart library" in capsys.readouterr().out

    def test_invalid_body_is_rejected_and_not_saved(self, paths, monkeypatch, capsys):
        _serve(monkeypatch, b"<html>404</html>")
        with pytest.raises(SystemExit) as info:
            lib_cache.ensure_chart_library(str(paths.lwc_file))
        assert info.value.code == 1
        assert not paths.lwc_file.exists()
        assert list(paths.data_dir.glob("*.tmp")) == []

    def test_download_failure_exits_with_manual_instructions(
        self, paths, monkeypatch, capsys
    ):
        def offline(_url: str) -> bytes:
            raise ConnectionError("could not download: offline")

        monkeypatch.setattr(lib_cache, "fetch_bytes", offline)
        with pytest.raises(SystemExit) as info:
            lib_cache.ensure_chart_library(str(paths.lwc_file))
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert lib_cache.LWC_URL in err
        assert str(paths.lwc_file) in err
        assert not paths.lwc_file.exists()


class TestValidateLibrary:
    def test_accepts_a_build_with_the_marker(self, tmp_path):
        path = tmp_path / "lib.js"
        path.write_bytes(GOOD_BODY)
        lib_cache.validate_library(path)

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (b"", "empty"),
            (b"  \n", "empty"),
            (b"var other = 1;", "LightweightCharts"),
            (b"\xff\xfe\x00", "UTF-8"),
        ],
    )
    def test_rejects_unusable_files(self, tmp_path, body, message):
        path = tmp_path / "lib.js"
        path.write_bytes(body)
        with pytest.raises(ValueError, match=message):
            lib_cache.validate_library(path)


class TestDownloadLibrary:
    def test_non_utf8_body_is_rejected(self, paths, monkeypatch):
        _serve(monkeypatch, b"\xff\xfe\x00")
        with pytest.raises(ValueError, match="UTF-8"):
            lib_cache.download_library(str(paths.lwc_file))
        assert not paths.lwc_file.exists()

    def test_invalid_download_keeps_an_existing_file(self, paths, monkeypatch):
        paths.lwc_file.write_text("var LightweightCharts;", encoding="utf-8")
        _serve(monkeypatch, b"nope")
        with pytest.raises(ValueError):
            lib_cache.download_library(str(paths.lwc_file))
        assert paths.lwc_file.read_text(encoding="utf-8") == "var LightweightCharts;"
