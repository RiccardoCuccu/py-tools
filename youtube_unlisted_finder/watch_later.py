#!/usr/bin/env python3
"""
Watch Later listing through yt-dlp, since the Data API cannot read that playlist.
"""

import os
from typing import Any, cast

import yt_dlp
from yt_dlp.utils import YoutubeDLError

WATCH_LATER_URL = ":ytwatchlater"
WATCH_LATER_HINT = (
    "close Chrome and retry, or use --cookies-file with an exported cookies.txt, "
    "or --browser firefox"
)


class WatchLaterError(Exception):
    """Raised when Watch Later cannot be read."""


class _SilentLogger:
    """yt-dlp logger that drops everything; failures surface as exceptions."""

    def debug(self, msg: str) -> None:
        """Ignore debug output."""

    def info(self, msg: str) -> None:
        """Ignore informational output."""

    def warning(self, msg: str) -> None:
        """Ignore warnings."""

    def error(self, msg: str) -> None:
        """Ignore error lines; the raised exception carries the cause."""


def build_options(browser: str, cookies_file: str) -> dict[str, Any]:
    """
    Build yt-dlp options for a flat Watch Later listing.

    A cookies file takes precedence over browser cookies. Raises WatchLaterError
    when neither cookie source is set or the file does not exist.
    """
    options: dict[str, Any] = {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
    }
    if cookies_file:
        if not os.path.isfile(cookies_file):
            raise WatchLaterError(f"cookies file not found: {cookies_file}")
        options["cookiefile"] = cookies_file
    elif browser:
        options["cookiesfrombrowser"] = (browser, None, None, None)
    else:
        raise WatchLaterError("no cookie source configured (browser or cookies file)")
    return options


def fetch_watch_later_ids(browser: str, cookies_file: str) -> list[str]:
    """
    Return the video ids in the account's Watch Later playlist.

    Raises WatchLaterError on any failure (locked cookie database, expired
    session, network error) so the caller can continue without Watch Later.
    """
    options = build_options(browser, cookies_file)
    try:
        with yt_dlp.YoutubeDL(cast(Any, options)) as ydl:
            info = ydl.extract_info(WATCH_LATER_URL, download=False)
    except (YoutubeDLError, OSError) as error:
        raise WatchLaterError(str(error)) from error
    entries = (info or {}).get("entries") or []
    return [entry["id"] for entry in entries if entry and entry.get("id")]


def describe_cookie_source(browser: str, cookies_file: str) -> str:
    """Return a human-readable name of the cookie source used for Watch Later."""
    if cookies_file:
        return f"cookies file {cookies_file}"
    if browser:
        return f"{browser} browser cookies"
    return "no cookie source"
