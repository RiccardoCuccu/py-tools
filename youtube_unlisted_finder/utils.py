#!/usr/bin/env python3
"""
Shared helpers: console/file logger, atomic text writer and data classes.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import LOG_FILE

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class UnlistedVideo:
    """An unlisted video found in one or more of the scanned sources."""

    video_id: str
    title: str
    channel: str
    url: str
    playlists: list[str] = field(default_factory=list)


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """Write text to path via a temp file so a crash never leaves a partial file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(target.name + ".tmp")
    # newline="" keeps the line endings the caller built (csv relies on it)
    try:
        with open(tmp_path, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        os.replace(tmp_path, target)
    except BaseException:
        # Do not leave a stray .tmp file behind when the write or replace fails
        tmp_path.unlink(missing_ok=True)
        raise


class Logger:
    """Console output; warnings and errors are also appended to the log file."""

    def log_info(self, message: str) -> None:
        """Print an informational message."""
        print(message)

    def log_warning(self, message: str) -> None:
        """Print a warning and append it to the log file."""
        self._append("WARNING", message)
        print(f"WARNING: {message}")

    def log_error(self, message: str) -> None:
        """Print an error and append it to the log file."""
        self._append("ERROR", message)
        print(f"ERROR: {message}")

    def _append(self, level: str, message: str) -> None:
        """Append one timestamped line to the log file, creating its folder."""
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {level}: {message}\n")
