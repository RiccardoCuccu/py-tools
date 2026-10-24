"""Tests for main: argument parsing and the orchestration of price loading, repair and
charting, with prompts, HTTP, the chart library and the browser faked. Every file lives
in tmp_path.
"""

import datetime as dt

import pytest

import halvings
import main
import price_data
import utils
from halvings import HalvingInfo
from helpers import (
    api_payload,
    failing_urlopen,
    fake_urlopen,
    mempool_fetcher,
    series,
    set_mtime,
    write_json,
)


class _Calls(list):
    """Ordered (stage, argument) calls, plus the halving infos given to the payload."""

    def __init__(self):
        super().__init__()
        self.shown: list[HalvingInfo] = []


@pytest.fixture
def chart(monkeypatch):
    """Fake the chart stages; return the ordered calls as (name, argument) pairs."""
    calls = _Calls()

    def fake_payload(_df, info, mode):
        calls.shown.append(info)
        calls.append(("payload", (info, mode)))
        return {"fake": True}

    def fake_render(payload, template, script, lib):
        calls.append(("render", (payload, template, script, lib)))
        return "<html>"

    monkeypatch.setattr(
        main, "ensure_chart_library", lambda p: calls.append(("library", p))
    )
    monkeypatch.setattr(main, "build_payload", fake_payload)
    monkeypatch.setattr(main, "render_chart", fake_render)
    monkeypatch.setattr(
        main, "write_chart", lambda page, p: calls.append(("write", (page, p)))
    )

    def fake_open(p):
        calls.append(("open", p))
        return True

    monkeypatch.setattr(main, "open_chart", fake_open)
    return calls



@pytest.fixture
def shown(chart):
    """Halving infos that reached the payload builder, one per run."""
    return chart.shown


class TestMain:
    @pytest.fixture(autouse=True)
    def mempool(self, monkeypatch):
        """Serve the halvings from a fake mempool.space; return the requested URLs."""
        requested: list[str] = []
        monkeypatch.setattr(
            halvings, "fetch_bytes", mempool_fetcher(850_000, requested)
        )
        return requested

    @pytest.fixture
    def prompts(self, monkeypatch):
        """Make input() fail the test unless a test installs its own answer."""
        asked: list[str] = []

        def unexpected(question=""):
            asked.append(question)
            raise AssertionError("unexpected prompt")

        monkeypatch.setattr("builtins.input", unexpected)
        return asked

    def answer(self, monkeypatch, reply: str) -> list[str]:
        """Install a canned input() reply and return the list of questions asked."""
        asked: list[str] = []

        def fake_input(question=""):
            asked.append(question)
            return reply

        monkeypatch.setattr("builtins.input", fake_input)
        return asked

    def test_missing_file_decline_exits_with_instructions(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        monkeypatch.setattr(main, "JSON_FILE", str(tmp_path / "market-price.json"))
        self.answer(monkeypatch, "n")
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "market-price.json" in err
        assert "blockchain.com" in err
        assert shown == []

    def test_missing_file_accept_downloads_then_plots(
        self, tmp_path, monkeypatch, shown
    ):
        target = tmp_path / "market-price.json"
        monkeypatch.setattr(main, "JSON_FILE", str(target))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(1.0, 10.0))
        )
        self.answer(monkeypatch, "y")
        main.main([])
        assert target.exists()
        assert len(shown) == 1

    def test_missing_file_download_failure_exits_with_instructions(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        monkeypatch.setattr(main, "JSON_FILE", str(tmp_path / "market-price.json"))
        monkeypatch.setattr(utils.urllib.request, "urlopen", failing_urlopen)
        self.answer(monkeypatch, "y")
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "could not download" in err
        assert "blockchain.com" in err
        assert shown == []

    def test_stale_file_decline_plots_old_data(self, tmp_path, monkeypatch, shown):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        asked = self.answer(monkeypatch, "n")
        main.main([])
        assert len(asked) == 1
        assert len(shown) == 1

    def test_stale_file_download_failure_warns_and_plots(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        monkeypatch.setattr(utils.urllib.request, "urlopen", failing_urlopen)
        self.answer(monkeypatch, "y")
        main.main([])
        assert "Warning" in capsys.readouterr().err
        assert len(shown) == 1

    def test_current_file_never_prompts(self, tmp_path, monkeypatch, shown, prompts):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        main.main([])
        assert prompts == []
        assert len(shown) == 1

    def test_stale_file_accept_replaces_it(self, tmp_path, monkeypatch, shown):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(5.0, 9.0))
        )
        self.answer(monkeypatch, "y")
        main.main([])
        assert price_data.load_price_data(data)["Close"].tolist() == [5.0, 9.0]
        assert price_data.is_data_current(str(data))
        assert len(shown) == 1

    def test_stale_file_unusable_download_keeps_old_data(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        before = data.read_text(encoding="utf-8")
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(0, 0))
        )
        self.answer(monkeypatch, "y")
        main.main([])
        assert data.read_text(encoding="utf-8") == before
        assert "Warning" in capsys.readouterr().err
        assert len(shown) == 1

    def test_eof_at_prompt_with_missing_file_exits(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        monkeypatch.setattr(main, "JSON_FILE", str(tmp_path / "market-price.json"))

        def raise_eof(*_a):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        assert "blockchain.com" in capsys.readouterr().err
        assert shown == []

    def test_corrupt_file_decline_exits_with_hint(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(main, "JSON_FILE", str(bad))
        asked = self.answer(monkeypatch, "n")
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "not valid JSON" in err
        assert "Delete or replace" in err
        assert len(asked) == 1
        assert shown == []

    def test_empty_file_decline_exits_with_hint(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("", encoding="utf-8")
        monkeypatch.setattr(main, "JSON_FILE", str(bad))
        self.answer(monkeypatch, "n")
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        assert "Delete or replace" in capsys.readouterr().err

    def test_corrupt_file_download_failure_exits_with_hint(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(main, "JSON_FILE", str(bad))
        monkeypatch.setattr(utils.urllib.request, "urlopen", failing_urlopen)
        self.answer(monkeypatch, "y")
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "could not download" in err
        assert "Delete or replace" in err
        assert shown == []

    def test_corrupt_file_download_success_plots(
        self, tmp_path, monkeypatch, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(main, "JSON_FILE", str(bad))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(3.0, 4.0))
        )
        self.answer(monkeypatch, "y")
        main.main([])
        assert price_data.load_price_data(bad)["Close"].tolist() == [3.0, 4.0]
        assert len(shown) == 1


    def test_missing_halvings_download_without_asking_and_reach_the_chart(
        self, tmp_path, paths, monkeypatch, capsys, shown, prompts, mempool
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        main.main([])
        assert prompts == []
        assert "Downloading halvings" in capsys.readouterr().out
        assert paths.halvings_file.exists()
        assert len(shown) == 1
        assert len(shown[0].past) == 4
        assert shown[0].next_estimate is not None

    def test_current_data_and_cached_halvings_make_no_halving_request(
        self, tmp_path, monkeypatch, shown, prompts, mempool
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        main.main([])
        mempool.clear()
        main.main([])
        assert mempool == []
        assert len(shown) == 2

    def test_yes_answer_refreshes_halvings_too(
        self, tmp_path, monkeypatch, shown, mempool
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        main.main([])
        mempool.clear()

        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(1.0, 2.0))
        )
        self.answer(monkeypatch, "y")
        main.main([])
        assert mempool != []

    def test_no_answer_keeps_cached_halvings_untouched(
        self, tmp_path, monkeypatch, shown, mempool
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        main.main([])
        mempool.clear()

        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        self.answer(monkeypatch, "n")
        main.main([])
        assert mempool == []

    def test_halvings_failure_without_cache_still_draws_the_chart(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        def offline(_url):
            raise ConnectionError("could not download: offline")

        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(data))
        monkeypatch.setattr(halvings, "fetch_bytes", offline)
        main.main([])
        assert "without halving lines" in capsys.readouterr().err
        assert shown == [HalvingInfo(past=[], next_estimate=None)]


class TestChartFlow:
    @pytest.fixture(autouse=True)
    def mempool(self, monkeypatch):
        monkeypatch.setattr(halvings, "fetch_bytes", mempool_fetcher(850_000))

    @pytest.fixture
    def data(self, tmp_path, monkeypatch):
        path = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(main, "JSON_FILE", str(path))
        return path

    def test_stages_run_in_order_and_the_path_is_logged(
        self, data, paths, monkeypatch, capsys, chart
    ):
        monkeypatch.setattr(main, "OPEN_BROWSER", True)
        main.main(["--mode", "powerlaw"])
        assert [name for name, _ in chart] == [
            "library",
            "payload",
            "render",
            "write",
            "open",
        ]
        assert chart[0][1] == str(paths.lwc_file)
        assert chart[1][1][1] == "powerlaw"
        assert chart[3] == ("write", ("<html>", str(paths.chart_file)))
        assert chart[4] == ("open", str(paths.chart_file))
        assert f"Chart written to: {paths.chart_file}" in capsys.readouterr().out

    def test_default_mode_comes_from_config(self, data, monkeypatch, chart):
        monkeypatch.setattr(main, "DEFAULT_MODE", "powerlaw")
        assert main.parse_args([]).mode == "powerlaw"

    def test_no_open_skips_the_browser(self, data, monkeypatch, chart):
        monkeypatch.setattr(main, "OPEN_BROWSER", True)
        main.main(["--no-open"])
        assert "open" not in [name for name, _ in chart]
        assert "write" in [name for name, _ in chart]

    def test_open_browser_off_skips_the_browser(self, data, monkeypatch, chart):
        monkeypatch.setattr(main, "OPEN_BROWSER", False)
        main.main([])
        assert "open" not in [name for name, _ in chart]

    def test_unopenable_browser_warns(self, data, monkeypatch, capsys, chart):
        monkeypatch.setattr(main, "OPEN_BROWSER", True)
        monkeypatch.setattr(main, "open_chart", lambda _p: False)
        main.main([])
        assert "No web browser" in capsys.readouterr().err

    def test_render_error_exits_without_writing(self, data, monkeypatch, capsys, chart):
        def broken(*_args):
            raise ValueError("bad template")

        monkeypatch.setattr(main, "render_chart", broken)
        with pytest.raises(SystemExit) as info:
            main.main([])
        assert info.value.code == 1
        assert "bad template" in capsys.readouterr().err
        assert "write" not in [name for name, _ in chart]


class TestParseArgs:
    def test_defaults(self):
        args = main.parse_args([])
        assert args.mode == main.DEFAULT_MODE
        assert args.no_open is False

    @pytest.mark.parametrize("mode", ["golden", "powerlaw"])
    def test_mode_choices(self, mode):
        assert main.parse_args(["--mode", mode]).mode == mode

    def test_invalid_mode_exits_with_usage_error(self):
        with pytest.raises(SystemExit) as info:
            main.parse_args(["--mode", "rainbow"])
        assert info.value.code == 2

    def test_no_open_flag(self):
        assert main.parse_args(["--no-open"]).no_open is True

    def test_unknown_option_exits_with_usage_error(self, capsys):
        with pytest.raises(SystemExit) as info:
            main.parse_args(["--nope"])
        assert info.value.code == 2
