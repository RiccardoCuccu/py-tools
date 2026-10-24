#!/usr/bin/env python3
"""
Chart page: fill the HTML template, write the page atomically and open it in the browser.
"""

import html
import json
import webbrowser
from pathlib import Path
from string import Template
from typing import Any

from config import (
    CHART_TITLE,
    SCRIPT_CLOSE_ESCAPED,
    SCRIPT_CLOSE_TAG,
    SCRIPT_COMMENT_ESCAPED,
    SCRIPT_COMMENT_OPEN,
    TEMPLATE_APP_KEY,
    TEMPLATE_LIB_KEY,
    TEMPLATE_PAYLOAD_KEY,
    TEMPLATE_TITLE_KEY,
)
from utils import PathArg, write_validated


def _read_text(path: PathArg) -> str:
    """Return the UTF-8 text of path."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _escape_script(text: str) -> str:
    """
    Make text safe inside an inline script.

    Closing-tag openers cannot end the script, and comment openers cannot start
    the HTML "script data escaped" state.
    """
    return text.replace(SCRIPT_CLOSE_TAG, SCRIPT_CLOSE_ESCAPED).replace(
        SCRIPT_COMMENT_OPEN, SCRIPT_COMMENT_ESCAPED
    )


def render_chart(
    payload: dict[str, Any],
    template_path: PathArg,
    script_path: PathArg,
    lib_path: PathArg,
) -> str:
    """
    Return the chart page: the template filled with title, library, app script and data.

    The payload is serialised without NaN. The payload, the library and the app
    script are escaped for inline <script> use before substitution.

    Raises:
        OSError: a template, script or library file cannot be read.
        ValueError: the payload holds NaN or infinity, or the template is malformed.
    """
    payload_json = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    values = {
        TEMPLATE_TITLE_KEY: html.escape(CHART_TITLE),
        TEMPLATE_LIB_KEY: _escape_script(_read_text(lib_path)),
        TEMPLATE_APP_KEY: _escape_script(_read_text(script_path)),
        TEMPLATE_PAYLOAD_KEY: _escape_script(payload_json),
    }
    try:
        return Template(_read_text(template_path)).substitute(values)
    except KeyError as exc:
        raise ValueError(f"the template uses an unknown placeholder: {exc}") from exc


def write_chart(page: str, path: PathArg) -> None:
    """Write page to path atomically, creating the output folder if needed."""
    write_validated(page, path, lambda _temp_path: None)


def open_chart(path: PathArg) -> bool:
    """Open the chart file in the default browser; return False if none could be opened."""
    return webbrowser.open(Path(path).resolve().as_uri())
