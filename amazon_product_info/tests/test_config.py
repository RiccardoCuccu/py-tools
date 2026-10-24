"""Tests for config.py: credential loading and configuration validation."""

import json
import logging

import pytest

import config
from config import load_api_credentials, validate_configuration


def _write(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_credentials_valid(tmp_path):
    """Keys and the optional partner tag are returned."""
    path = _write(
        tmp_path,
        json.dumps({"access_key": "AK", "secret_key": "SK", "partner_tag": "t-21"}),
    )
    assert load_api_credentials(path) == {
        "access_key": "AK",
        "secret_key": "SK",
        "partner_tag": "t-21",
    }


def test_load_credentials_partner_tag_optional(tmp_path):
    """A missing partner tag defaults to an empty string."""
    path = _write(tmp_path, json.dumps({"access_key": "AK", "secret_key": "SK"}))
    credentials = load_api_credentials(path)
    assert credentials is not None
    assert credentials["partner_tag"] == ""


def test_load_credentials_missing_file(tmp_path):
    """A missing file means no credentials."""
    assert load_api_credentials(tmp_path / "absent.json") is None


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '"text"',
        json.dumps({"access_key": "AK"}),
        json.dumps({"access_key": "", "secret_key": "SK"}),
        json.dumps({"access_key": 1, "secret_key": "SK"}),
        json.dumps({"access_key": "AK", "secret_key": "SK", "partner_tag": 5}),
    ],
)
def test_load_credentials_invalid(tmp_path, content):
    """Malformed or incomplete files yield None instead of raising."""
    assert load_api_credentials(_write(tmp_path, content)) is None


def test_load_credentials_never_logs_secrets(tmp_path, caplog):
    """Warnings never echo file content."""
    path = _write(tmp_path, '{"access_key": "SUPERSECRET", ')
    with caplog.at_level(logging.WARNING):
        load_api_credentials(path)
    assert "SUPERSECRET" not in caplog.text


def test_default_configuration_is_valid():
    """The shipped defaults pass validation."""
    assert validate_configuration() is True


@pytest.mark.parametrize(
    "overrides, message",
    [
        (
            {
                "ENABLE_FETCHER_API": False,
                "ENABLE_FETCHER_HTML": False,
                "ENABLE_FETCHER_BROWSER": False,
                "FETCHER_ORDER": [],
            },
            "No fetchers enabled",
        ),
        ({"FETCHER_ORDER": ["api", "bogus"]}, "Invalid fetchers"),
        ({"ENABLE_FETCHER_HTML": False}, "disabled fetchers"),
        ({"MIN_VALID_PRICE": 10, "MAX_VALID_PRICE": 5}, "MIN_VALID_PRICE"),
        ({"BROWSER_TYPE": "opera"}, "BROWSER_TYPE"),
        ({"REQUEST_DELAY": -1}, "REQUEST_DELAY"),
        ({"RETRY_DELAY_MIN": 9, "RETRY_DELAY_MAX": 1}, "RETRY_DELAY_MIN"),
        ({"API_BATCH_SIZE": 11}, "API_BATCH_SIZE"),
        ({"API_BATCH_SIZE": 0}, "API_BATCH_SIZE"),
    ],
)
def test_validate_configuration_errors(monkeypatch, overrides, message):
    """Each invalid setting is reported in the raised error."""
    for name, value in overrides.items():
        monkeypatch.setattr(config, name, value)
    with pytest.raises(ValueError, match=message):
        validate_configuration()


def test_batch_size_ignored_when_batching_disabled(monkeypatch):
    """An out-of-range batch size does not matter if batching is off."""
    monkeypatch.setattr(config, "ENABLE_API_BATCH_REQUESTS", False)
    monkeypatch.setattr(config, "API_BATCH_SIZE", 99)
    assert validate_configuration() is True


def test_missing_credentials_only_warn(monkeypatch, caplog):
    """Enabled PA-API without credentials is a warning, not an error."""
    monkeypatch.setattr(config, "PA_API_ACCESS_KEY", None)
    with caplog.at_level(logging.WARNING):
        assert validate_configuration() is True
    assert "credentials missing" in caplog.text
