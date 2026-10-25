#!/usr/bin/env python3
"""
YouTube Unlisted Finder - Report the unlisted videos saved in your playlists.

Scans your own playlists (Watch Later included), or only the playlists given
with --playlist and/or your liked videos, and writes a report of the videos whose
privacy status is "unlisted". Unlisted videos can vanish when the uploader makes
them private, so the report is a record of what to save.

Usage:
    python main.py
    python main.py --playlist PLxxxxxxxx --format csv
    python main.py --liked --no-watch-later --output my_report.md
    python main.py --cookies-file cookies.txt

Notes:
    - Watch Later is not exposed by the Data API: it is read through yt-dlp with
      browser cookies (Chrome must be closed) or an exported cookies.txt.
    - Videos the API does not return (private or deleted) are counted as skipped.
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError

from config import (
    COOKIES_FILE, COOKIES_FROM_BROWSER, DEFAULT_FORMAT, INCLUDE_WATCH_LATER,
    LIKED_TITLE, SUPPORTED_BROWSERS, VALID_FORMATS, WATCH_LATER_ID,
    WATCH_LATER_TITLE, first_run_setup,
)
from report import default_report_path, write_report
from utils import Logger, UnlistedVideo
from watch_later import (
    WATCH_LATER_HINT, WatchLaterError, describe_cookie_source,
    fetch_watch_later_ids,
)
from youtube_client import (
    YouTubeClient, extract_playlist_id, is_unlisted, to_unlisted_video,
)

EXIT_OK = 0
EXIT_ERROR = 1


@dataclass
class ScanResult:
    """Video ids found per source, plus liked-video resources already fetched."""

    sources: dict[str, list[str]] = field(default_factory=dict)
    known: dict[str, dict[str, Any]] = field(default_factory=dict)
    playlists_scanned: int = 0


def _playlist_arg(value: str) -> str:
    """argparse type: a playlist id or URL, with a readable error otherwise."""
    try:
        return extract_playlist_id(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"{error} (expected a playlist id like PLxxxx, WL, or a URL with ?list=)"
        ) from error


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Report the unlisted videos found in your YouTube playlists."
    )
    parser.add_argument(
        "--playlist", "-p", action="append", type=_playlist_arg, default=[],
        metavar="ID_OR_URL",
        help="Scan only this playlist (repeatable). 'WL' is Watch Later.",
    )
    parser.add_argument(
        "--liked", "-l", action="store_true",
        help="Scan the liked videos (combinable with --playlist).",
    )
    parser.add_argument(
        "--no-watch-later", action="store_true",
        help="Skip Watch Later in the default scan.",
    )
    parser.add_argument(
        "--format", "-f", choices=VALID_FORMATS, default=DEFAULT_FORMAT,
        help="Report format (default: %(default)s).",
    )
    parser.add_argument(
        "--output", "-o", metavar="PATH",
        help="Report path (default: reports/unlisted_<date>_<time>.<format>).",
    )
    parser.add_argument(
        "--browser", choices=SUPPORTED_BROWSERS,
        help="Browser whose cookies yt-dlp uses for Watch Later.",
    )
    parser.add_argument(
        "--cookies-file", metavar="PATH",
        help="Exported cookies.txt for Watch Later (overrides --browser).",
    )
    return parser.parse_args(argv)


def _add_source(sources: dict[str, list[str]], video_id: str, title: str) -> None:
    """Record that video_id belongs to the source titled title (deduplicated)."""
    titles = sources.setdefault(video_id, [])
    if title not in titles:
        titles.append(title)


def _scan_playlist(
    client: YouTubeClient, logger: Logger, scan: ScanResult, playlist_id: str,
    title: str | None = None,
) -> None:
    """
    Add a playlist's video ids to the scan; an API error skips that playlist.

    The title is looked up when not given; the lookup is guarded like the rest.
    """
    try:
        title = title or client.get_playlist_title(playlist_id)
        ids = client.list_playlist_video_ids(playlist_id)
    except HttpError as error:
        logger.log_error(f"Could not read playlist '{title or playlist_id}': {error}")
        return
    for video_id in ids:
        _add_source(scan.sources, video_id, title)
    scan.playlists_scanned += 1
    logger.log_info(f"  {title}: {len(ids)} videos")


def _scan_watch_later(
    args: argparse.Namespace, logger: Logger, scan: ScanResult
) -> None:
    """Add Watch Later ids via yt-dlp; a failure logs a warning and moves on."""
    browser = args.browser or COOKIES_FROM_BROWSER
    cookies_file = args.cookies_file or COOKIES_FILE
    try:
        ids = fetch_watch_later_ids(browser, cookies_file)
    except WatchLaterError as error:
        logger.log_warning(f"Watch Later skipped: {error}. Hint: {WATCH_LATER_HINT}.")
        return
    if not ids:
        source = describe_cookie_source(browser, cookies_file)
        logger.log_warning(
            f"Watch Later returned no videos using {source}: the login cookies "
            f"are probably expired or missing."
        )
    for video_id in ids:
        _add_source(scan.sources, video_id, WATCH_LATER_TITLE)
    scan.playlists_scanned += 1
    logger.log_info(f"  {WATCH_LATER_TITLE}: {len(ids)} videos")


def collect_sources(
    args: argparse.Namespace, client: YouTubeClient, logger: Logger
) -> ScanResult:
    """
    Gather video ids from the requested sources.

    Without --playlist or --liked, scans every own playlist and (unless
    disabled) Watch Later. With either flag, only those sources are scanned.
    """
    scan = ScanResult()
    explicit = bool(args.playlist) or args.liked
    logger.log_info("Collecting videos...")

    if explicit:
        for playlist_id in dict.fromkeys(args.playlist):
            if playlist_id == WATCH_LATER_ID:
                _scan_watch_later(args, logger, scan)
            else:
                _scan_playlist(client, logger, scan, playlist_id)
    else:
        for playlist_id, title in client.list_own_playlists():
            _scan_playlist(client, logger, scan, playlist_id, title)
        if INCLUDE_WATCH_LATER and not args.no_watch_later:
            _scan_watch_later(args, logger, scan)

    if args.liked:
        _scan_liked(client, logger, scan)
    return scan


def _scan_liked(client: YouTubeClient, logger: Logger, scan: ScanResult) -> None:
    """Add the liked videos to the scan; an API error skips them with a log."""
    try:
        resources = client.list_liked_videos()
    except HttpError as error:
        logger.log_error(f"Could not read liked videos: {error}")
        return
    for resource in resources:
        scan.known[resource["id"]] = resource
        _add_source(scan.sources, resource["id"], LIKED_TITLE)
    scan.playlists_scanned += 1
    logger.log_info(f"  {LIKED_TITLE}: {len(resources)} videos")


def find_unlisted(
    client: YouTubeClient, scan: ScanResult
) -> tuple[list[UnlistedVideo], int]:
    """Classify the scanned videos; return (unlisted videos, skipped count)."""
    ids = list(scan.sources)
    resources = client.fetch_videos(ids, known=scan.known)
    unlisted = [
        to_unlisted_video(resources[video_id], scan.sources[video_id])
        for video_id in ids
        if video_id in resources and is_unlisted(resources[video_id])
    ]
    return unlisted, len(ids) - len(resources)


def _run(args: argparse.Namespace, logger: Logger) -> int:
    """Authenticate, scan, classify and write the report."""
    client = YouTubeClient(logger)
    try:
        client.authenticate()
    except (ValueError, KeyError, OSError, TransportError) as error:
        logger.log_error(
            f"Authentication failed ({type(error).__name__}: {error}). Check that "
            f"client_secret.json is the JSON downloaded for a Desktop app OAuth "
            f"client, and that the network is reachable."
        )
        return EXIT_ERROR
    scan = collect_sources(args, client, logger)
    logger.log_info(f"Classifying {len(scan.sources)} videos...")
    unlisted, skipped = find_unlisted(client, scan)

    path = args.output or default_report_path(args.format)
    try:
        write_report(unlisted, args.format, path)
    except OSError as error:
        logger.log_error(
            f"Could not write the report to '{path}': "
            f"{error.strerror or error}"
        )
        return EXIT_ERROR

    logger.log_info("\nSummary")
    logger.log_info(f"  Sources scanned: {scan.playlists_scanned}")
    logger.log_info(f"  Videos checked: {len(scan.sources)}")
    logger.log_info(f"  Unlisted found: {len(unlisted)}")
    logger.log_info(f"  Skipped (private or deleted): {skipped}")
    logger.log_info(f"  API quota used: {client.quota_used} units")
    logger.log_info(f"  Report: {path}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run the tool and return the process exit code."""
    args = _parse_args(argv)
    logger = Logger()
    if not first_run_setup():
        return EXIT_ERROR
    try:
        return _run(args, logger)
    except HttpError as error:
        logger.log_error(f"YouTube API request failed: {error}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        logger.log_info("\nInterrupted by user.")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
