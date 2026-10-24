#!/usr/bin/env python3
"""
Logger and generic helpers: capped download, validated atomic write, prompt and exit.
"""

import contextlib
import datetime as dt
import http.client
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, NoReturn

from config import (
    BYTES_PER_MB,
    DOWNLOAD_TIMEOUT_SECONDS,
    EXIT_FAILURE,
    LOG_FILE,
    LOG_TIMESTAMP_FORMAT,
    MAX_DOWNLOAD_BYTES,
    TEMP_FILE_SUFFIX,
    USER_AGENT,
    YES_ANSWERS,
)

# Path argument accepted by the file helpers
PathArg = str | os.PathLike[str]


class Logger:
    """Console output with warnings and errors also appended to the log file."""

    def log_info(self, message: str) -> None:
        """Print an informational message to the console."""
        print(message)

    def log_warning(self, message: str) -> None:
        """Print a warning to stderr and append it to the log file."""
        self._append("WARNING", message)
        print(f"Warning: {message}", file=sys.stderr)

    def log_error(self, message: str) -> None:
        """Print an error to stderr and append it to the log file."""
        self._append("ERROR", message)
        print(f"Error: {message}", file=sys.stderr)

    def _append(self, level: str, message: str) -> None:
        """
        Append a timestamped entry to LOG_FILE, creating its folder if needed.

        An unwritable log is ignored: logging must never break the caller.
        """
        timestamp = dt.datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {level}: {message}\n")


logger = Logger()


def fetch_bytes(url: str) -> bytes:
    """
    Fetch url and return the body, reading at most MAX_DOWNLOAD_BYTES.

    Raises:
        ConnectionError: the request failed (network, timeout, HTTP or protocol error).
        ValueError: the body exceeds MAX_DOWNLOAD_BYTES.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            # One extra byte tells an oversized body from one exactly at the cap
            raw = resp.read(MAX_DOWNLOAD_BYTES + 1)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise ConnectionError(f"could not download {url}: {exc}") from exc
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"the server response exceeds {MAX_DOWNLOAD_BYTES // BYTES_PER_MB} MB"
        )
    return raw


def write_validated(
    converted: dict[str, Any] | str,
    json_file: PathArg,
    validate: Callable[[str], object],
) -> None:
    """
    Write converted (JSON for a dict, verbatim for a str) to a temp file, check it
    with validate, then atomically replace json_file. The temp file is removed on any
    failure.

    validate receives the temp file path and raises ValueError for unusable data.

    Raises:
        ValueError: validate rejected the data.
    """
    folder = os.path.dirname(os.path.abspath(json_file))
    os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=folder, suffix=TEMP_FILE_SUFFIX)
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8", newline="")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            if isinstance(converted, str):
                handle.write(converted)
            else:
                json.dump(converted, handle)
        try:
            validate(temp_path)
        except ValueError as exc:
            raise ValueError(f"the downloaded data is unusable: {exc}") from exc
        os.replace(temp_path, json_file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(temp_path)
        raise


def ask_yes_no(question: str) -> bool:
    """Ask a yes/no question on the console; default is No (also on EOF or Ctrl+C)."""
    try:
        answer = input(question)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in YES_ANSWERS


def fail(message: str) -> NoReturn:
    """Log message as an error and exit with a failure code (no traceback)."""
    logger.log_error(message)
    raise SystemExit(EXIT_FAILURE)
