"""Tests for chart_html: template filling, script escaping, atomic write, browser."""

import pytest

import chart_html

TEMPLATE = (
    "<title>${title}</title><script>${lib_js}</script>"
    "<script>window.CHART_PAYLOAD = ${payload_json};</script>"
    "<script>${app_js}</script>"
)


@pytest.fixture
def files(tmp_path):
    """Write a tiny template, app script and library; return their paths."""
    template = tmp_path / "chart.html"
    script = tmp_path / "chart.js"
    lib = tmp_path / "lib.js"
    template.write_text(TEMPLATE, encoding="utf-8")
    script.write_text("var app = 1; // cost $5", encoding="utf-8")
    lib.write_text("var LightweightCharts = {};", encoding="utf-8")
    return template, script, lib


class TestRenderChart:
    def test_placeholders_are_substituted(self, files):
        page = chart_html.render_chart({"a": 1}, *files)
        assert "${" not in page
        assert "<title>Bitcoin Price Models</title>" in page
        assert "<script>var LightweightCharts = {};</script>" in page
        assert 'window.CHART_PAYLOAD = {"a":1};' in page
        assert "<script>var app = 1; // cost $5</script>" in page

    def test_closing_script_tags_are_escaped_everywhere(self, files):
        template, script, lib = files
        script.write_text('var s = "</script>";', encoding="utf-8")
        lib.write_text('var LightweightCharts = "</script>";', encoding="utf-8")
        page = chart_html.render_chart({"label": "</script><b>"}, *files)
        assert page.count("</script>") == 3
        assert page.count("<\\/script>") == 3

    def test_comment_openers_are_escaped_everywhere(self, files):
        template, script, lib = files
        script.write_text('var s = "<!--";', encoding="utf-8")
        lib.write_text('var LightweightCharts = "<!--";', encoding="utf-8")
        page = chart_html.render_chart({"label": "<!-- x"}, *files)
        assert "<!--" not in page
        assert page.count("<\\!--") == 3

    def test_nan_payload_is_rejected(self, files):
        with pytest.raises(ValueError):
            chart_html.render_chart({"v": float("nan")}, *files)

    def test_unknown_placeholder_is_a_value_error(self, files):
        template, script, lib = files
        template.write_text("${nope}", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown placeholder"):
            chart_html.render_chart({}, template, script, lib)

    def test_missing_file_raises_os_error(self, files, tmp_path):
        template, script, _lib = files
        with pytest.raises(OSError):
            chart_html.render_chart({}, template, script, tmp_path / "absent.js")


class TestWriteChart:
    def test_writes_to_the_redirected_output_path(self, paths):
        chart_html.write_chart("<html>\n</html>", paths.chart_file)
        assert paths.chart_file.read_text(encoding="utf-8") == "<html>\n</html>"

    def test_creates_the_output_folder_and_leaves_no_temp_file(self, paths):
        assert not paths.output_dir.exists()
        chart_html.write_chart("x", paths.chart_file)
        assert [p.name for p in paths.output_dir.iterdir()] == ["chart.html"]

    def test_overwrites_an_existing_page(self, paths):
        chart_html.write_chart("old", paths.chart_file)
        chart_html.write_chart("new", paths.chart_file)
        assert paths.chart_file.read_text(encoding="utf-8") == "new"


class TestOpenChart:
    def test_opens_the_file_uri(self, tmp_path, monkeypatch):
        opened: list[str] = []

        def fake_open(url):
            opened.append(url)
            return True

        monkeypatch.setattr(chart_html.webbrowser, "open", fake_open)
        page = tmp_path / "chart.html"
        assert chart_html.open_chart(page) is True
        assert opened == [page.resolve().as_uri()]
        assert opened[0].startswith("file:///")

    def test_reports_a_missing_browser(self, tmp_path, monkeypatch):
        monkeypatch.setattr(chart_html.webbrowser, "open", lambda _url: False)
        assert chart_html.open_chart(tmp_path / "chart.html") is False
