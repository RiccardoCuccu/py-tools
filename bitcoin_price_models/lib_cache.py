#!/usr/bin/env python3
"""
Chart library cache: download the Lightweight Charts build once and keep it in data/.
"""

import os

from config import LWC_MARKER, LWC_URL
from utils import PathArg, fail, fetch_bytes, logger, write_validated


def validate_library(path: PathArg) -> None:
    """
    Check that path holds a usable Lightweight Charts build.

    Raises:
        ValueError: the file is empty, not UTF-8 text, or lacks LWC_MARKER.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError as exc:
        raise ValueError(f"the library is not valid UTF-8 text: {exc}") from exc
    if not text.strip():
        raise ValueError("the library file is empty")
    if LWC_MARKER not in text:
        raise ValueError(f"the file does not look like the library ({LWC_MARKER} missing)")


def download_library(path: PathArg, url: str = LWC_URL) -> None:
    """
    Download the library and write it to path atomically.

    The file replaces path only when validate_library accepts it, so a failed or
    wrong download never leaves a broken cache.

    Raises:
        ConnectionError: the request failed (network, timeout or HTTP error).
        ValueError: the response is too large or is not the library.
    """
    raw = fetch_bytes(url)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"the server response is not valid UTF-8 text: {exc}") from exc
    write_validated(text, path, validate_library)


def manual_library_instructions(path: PathArg) -> str:
    """Return the text explaining how to obtain the library by hand."""
    return (
        "\nTo draw the chart the Lightweight Charts library is needed:\n"
        f"1. Download: {LWC_URL}\n"
        "2. Save the file at this exact path:\n"
        f"   {path}\n"
        "Then re-run the script."
    )


def ensure_chart_library(path: PathArg) -> None:
    """
    Make sure a valid library is cached at path, downloading it when needed.

    An existing file that passes validate_library is kept. A missing or invalid
    file is downloaded; a failed download ends the program with the manual
    instructions.
    """
    if os.path.exists(path):
        try:
            validate_library(path)
            return
        except ValueError as exc:
            logger.log_warning(
                f"The cached chart library is unusable ({exc}); downloading it again."
            )
    try:
        logger.log_info(f"Downloading the chart library to: {path}")
        download_library(path)
    except (ConnectionError, ValueError, OSError) as exc:
        fail(f"{exc}\n{manual_library_instructions(path)}")
