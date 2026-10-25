#!/usr/bin/env python3
"""
Report writers: Markdown, CSV and JSON renderings of the unlisted videos found.
"""

import csv
import io
import json
import os
import re
from dataclasses import asdict
from datetime import datetime

from config import REPORTS_DIR
from utils import UnlistedVideo, atomic_write_text

FILENAME_TEMPLATE = "unlisted_{stamp}.{ext}"
STAMP_FORMAT = "%Y-%m-%d_%H%M"
CSV_COLUMNS = ("title", "channel", "url", "video_id", "playlists")
CSV_ENCODING = "utf-8-sig"  # BOM so Excel reads accented characters
PLAYLIST_SEPARATOR = "; "
MARKDOWN_SPECIAL_PATTERN = re.compile(r"([\\\[\]()])")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def default_report_path(fmt: str, now: datetime | None = None) -> str:
    """Return reports/unlisted_YYYY-MM-DD_HHMM.<fmt> inside the reports folder."""
    stamp = (now or datetime.now()).strftime(STAMP_FORMAT)
    return os.path.join(REPORTS_DIR, FILENAME_TEMPLATE.format(stamp=stamp, ext=fmt))


def _escape_markdown(text: str) -> str:
    """Collapse whitespace and escape characters that break Markdown links."""
    return MARKDOWN_SPECIAL_PATTERN.sub(r"\\\1", " ".join(text.split()))


def _neutralize_formula(cell: str) -> str:
    """Prefix a quote to cells a spreadsheet would run as a formula."""
    if cell.startswith(FORMULA_PREFIXES):
        return "'" + cell
    return cell


def render_markdown(videos: list[UnlistedVideo]) -> str:
    """Render videos grouped by playlist; multi-playlist videos repeat per section."""
    lines = ["# Unlisted videos", ""]
    if not videos:
        lines.append("No unlisted videos found.")
        return "\n".join(lines) + "\n"
    groups: dict[str, list[UnlistedVideo]] = {}
    for video in videos:
        for playlist in video.playlists:
            groups.setdefault(playlist, []).append(video)
    for playlist, members in groups.items():
        lines.append(f"## {_escape_markdown(playlist)}")
        lines.append("")
        for video in members:
            title = _escape_markdown(video.title)
            channel = _escape_markdown(video.channel)
            lines.append(f"- [{title}]({video.url}) - {channel}")
        lines.append("")
    return "\n".join(lines)


def render_csv(videos: list[UnlistedVideo]) -> str:
    """Render one CSV row per video, playlists joined with '; '."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for video in videos:
        cells = [
            video.title, video.channel, video.url, video.video_id,
            PLAYLIST_SEPARATOR.join(video.playlists),
        ]
        writer.writerow([_neutralize_formula(cell) for cell in cells])
    return buffer.getvalue()


def render_json(videos: list[UnlistedVideo]) -> str:
    """Render the videos as a JSON list of objects."""
    return json.dumps([asdict(v) for v in videos], indent=2, ensure_ascii=False) + "\n"


def write_report(videos: list[UnlistedVideo], fmt: str, path: str) -> None:
    """Write the report in the requested format (md, csv or json) to path."""
    if fmt == "md":
        atomic_write_text(path, render_markdown(videos))
    elif fmt == "csv":
        atomic_write_text(path, render_csv(videos), encoding=CSV_ENCODING)
    elif fmt == "json":
        atomic_write_text(path, render_json(videos))
    else:
        raise ValueError(f"unsupported report format: {fmt}")
