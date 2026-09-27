"""Tests for config.get_contact_email: contact_email loading from config.json."""

import json
from pathlib import Path

import pytest

import config
from config import DEFAULT_CONTACT_EMAIL, get_contact_email


@pytest.fixture(autouse=True)
def isolated_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config.CONFIG_PATH at a tmp_path file, never the real tool-folder config.json."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    return config_path


def test_get_contact_email_missing_file_returns_default() -> None:
    """No config.json at all returns the default fallback email, without warning."""
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL


def test_get_contact_email_reads_valid_value(isolated_config_path: Path) -> None:
    """A well-formed config.json with a valid contact_email is returned verbatim."""
    isolated_config_path.write_text(json.dumps({"contact_email": "me@example.com"}))
    assert get_contact_email() == "me@example.com"


def test_get_contact_email_invalid_json_returns_default(
    isolated_config_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Invalid JSON in an existing config.json falls back to the default, with a warning."""
    isolated_config_path.write_text("{not valid json")
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL
    assert "Failed to read" in caplog.text


def test_get_contact_email_empty_field_returns_default(
    isolated_config_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty contact_email field falls back to the default, with a warning."""
    isolated_config_path.write_text(json.dumps({"contact_email": ""}))
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL
    assert "invalid" in caplog.text.lower()


def test_get_contact_email_missing_field_returns_default(
    isolated_config_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A config.json without a contact_email field falls back to the default, with a warning."""
    isolated_config_path.write_text(json.dumps({"other": "value"}))
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL
    assert "invalid" in caplog.text.lower()


def test_get_contact_email_value_without_at_sign_returns_default(
    isolated_config_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A contact_email value without '@' fails minimal validation and falls back."""
    isolated_config_path.write_text(json.dumps({"contact_email": "not-an-email"}))
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL
    assert "invalid" in caplog.text.lower()


def test_get_contact_email_non_dict_json_returns_default(isolated_config_path: Path) -> None:
    """A config.json whose top-level value is not an object falls back to the default."""
    isolated_config_path.write_text(json.dumps(["not", "a", "dict"]))
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL


def test_get_contact_email_non_string_field_returns_default(isolated_config_path: Path) -> None:
    """A contact_email field that is not a string falls back to the default."""
    isolated_config_path.write_text(json.dumps({"contact_email": 12345}))
    assert get_contact_email() == DEFAULT_CONTACT_EMAIL
