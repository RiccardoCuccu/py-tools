#!/usr/bin/env python3
"""Configuration file - contact email used for CrossRef and Unpaywall API requests."""

import json
import logging
from pathlib import Path
from typing import Optional

# User-editable constants

# Fallback contact email sent to CrossRef and Unpaywall when config.json is
# missing, invalid, or does not contain a usable contact_email value.
DEFAULT_CONTACT_EMAIL = "user@example.com"

# Loader

# Path to the personal config file, kept next to this module and gitignored.
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def get_contact_email() -> str:
    """Return the contact email to send to CrossRef and Unpaywall.

    Reads the `contact_email` field from `config.json` in this module's
    directory. Falls back to `DEFAULT_CONTACT_EMAIL` if the file is missing,
    contains invalid JSON, the field is absent or empty, or the value does
    not look like an email address (must contain "@"). A warning is printed
    only when the file exists but its content is invalid, not when it is
    simply missing.

    Returns:
        The configured contact email, or `DEFAULT_CONTACT_EMAIL` as fallback.
    """
    if not CONFIG_PATH.exists():
        return DEFAULT_CONTACT_EMAIL

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(f"[Config] Failed to read {CONFIG_PATH.name}: {e}")
        return DEFAULT_CONTACT_EMAIL

    email: Optional[object] = data.get("contact_email") if isinstance(data, dict) else None

    if not email or not isinstance(email, str) or "@" not in email:
        logging.warning(
            f"[Config] {CONFIG_PATH.name} exists but contact_email is missing, empty, or invalid"
        )
        return DEFAULT_CONTACT_EMAIL

    return email
