"""Tests for podcast_info_util: Apple URL parsing and episode title extraction."""

import pytest
from bs4 import BeautifulSoup

import podcast_info_util as pi


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


# --- parse_podcast_url ---


def test_parse_standard_url_with_episode_query() -> None:
    """Show id and a human-readable slug come out of a normal episode URL."""
    url = "https://podcasts.apple.com/us/podcast/my-great-episode/id1234567890?i=1000700000000"
    assert pi.parse_podcast_url(url) == ("1234567890", "my great episode")


def test_parse_percent_encoded_slug() -> None:
    """Encoded characters in the slug are decoded."""
    url = "https://podcasts.apple.com/it/podcast/produttivit%C3%A0-con-adc/id42"
    assert pi.parse_podcast_url(url) == ("42", "produttività con adc")


def test_parse_url_without_country_or_slug() -> None:
    """Both the country prefix and the slug are optional."""
    assert pi.parse_podcast_url("https://podcasts.apple.com/podcast/id99") == ("99", "")


def test_parse_slug_starting_with_id_is_not_confused_with_the_id() -> None:
    """A slug such as 'identity-crisis' must not be mistaken for the id segment."""
    url = "https://podcasts.apple.com/us/podcast/identity-crisis/id777?i=1"
    assert pi.parse_podcast_url(url) == ("777", "identity crisis")


def test_parse_ignores_surrounding_whitespace() -> None:
    """Pasted URLs with stray whitespace still parse."""
    assert pi.parse_podcast_url("  https://podcasts.apple.com/us/podcast/x/id5  \n")[0] == "5"


@pytest.mark.parametrize(
    "url",
    [
        "",
        None,
        "not a url",
        "https://example.com/us/podcast/x/id5",
        "https://podcasts.apple.com/us/podcast/x/idabc",
        "https://podcasts.apple.com.evil.example/us/podcast/x/id5",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_parse_rejects_non_apple_or_malformed_urls(url: str | None) -> None:
    """Anything that is not an Apple Podcasts show URL raises ValueError before any request."""
    with pytest.raises(ValueError):
        pi.parse_podcast_url(url)


# --- extract_real_title ---


def test_title_prefers_h1() -> None:
    """The first h1 wins over meta and title tags."""
    soup = BeautifulSoup(
        "<html><head><title>T - Apple</title><meta property='og:title' content='M'></head>"
        "<body><h1> Real Title </h1></body></html>",
        "html.parser",
    )
    assert pi.extract_real_title(soup) == "Real Title"


def test_title_falls_back_to_og_title() -> None:
    """Without an h1 the og:title meta is used."""
    soup = BeautifulSoup("<meta property='og:title' content=' Meta Title '>", "html.parser")
    assert pi.extract_real_title(soup) == "Meta Title"


def test_title_falls_back_to_title_tag_before_separator() -> None:
    """Without h1 and meta the page title is cut at the first ' - '."""
    soup = BeautifulSoup("<title>Episode - Show - Apple Podcasts</title>", "html.parser")
    assert pi.extract_real_title(soup) == "Episode"


def test_title_empty_when_page_has_nothing() -> None:
    """A page without any title source yields an empty string."""
    assert pi.extract_real_title(BeautifulSoup("<p>hi</p>", "html.parser")) == ""


# --- podcast_info ---


def test_podcast_info_fetches_page_with_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The page is requested once, with a timeout, and the three values are returned."""
    seen: dict = {}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        seen.update(kwargs, url=url)
        return FakeResponse(200, b"<h1>Real Title</h1>")

    monkeypatch.setattr(pi.requests, "get", fake_get)
    url = "https://podcasts.apple.com/us/podcast/some-slug/id10?i=2"

    assert pi.podcast_info(url) == ("10", "some slug", "Real Title")
    assert seen["url"] == url
    assert seen["timeout"] == pi.REQUEST_TIMEOUT_SECONDS


def test_podcast_info_http_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-200 page response is an error carrying the status code."""
    monkeypatch.setattr(pi.requests, "get", lambda *a, **k: FakeResponse(503))

    with pytest.raises(RuntimeError, match="503"):
        pi.podcast_info("https://podcasts.apple.com/us/podcast/x/id10")


def test_podcast_info_invalid_url_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad URL is rejected before any network call."""

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("requests.get must not be called")

    monkeypatch.setattr(pi.requests, "get", fail)

    with pytest.raises(ValueError):
        pi.podcast_info("https://example.com/x")
