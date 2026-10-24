"""Tests for config.py: validation, derived settings and config loading."""

import json

import pytest

import config


def write_config(paths, data):
    with open(paths.config_file, "w", encoding="utf-8") as f:
        json.dump(data, f)


VALID = {"source_channel_id": "UC1", "backup_channel_id": "UC2"}


def test_validate_accepts_valid_configuration(paths):
    write_config(paths, VALID)
    config.validate_configuration()


def test_validate_reports_missing_config_file(paths):
    with pytest.raises(ValueError, match="config.json not found"):
        config.validate_configuration()


def test_validate_reports_all_problems_at_once(paths, monkeypatch):
    write_config(paths, {"source_channel_id": "YOUR_SOURCE_CHANNEL_ID_HERE", "backup_channel_id": ""})
    monkeypatch.setattr(config, "VIDEO_PRIVACY_STATUS", "secret")
    monkeypatch.setattr(config, "UPLOAD_CHUNK_SIZE_MB", 0)
    monkeypatch.setattr(config, "HTTP_CHUNK_SIZE_MB", 50)
    with pytest.raises(ValueError) as exc:
        config.validate_configuration()
    message = str(exc.value)
    for fragment in ("source_channel_id", "backup_channel_id", "VIDEO_PRIVACY_STATUS",
                     "UPLOAD_CHUNK_SIZE_MB", "HTTP_CHUNK_SIZE_MB"):
        assert fragment in message


def test_load_reads_channel_ids_and_derives_chunk_bytes(paths):
    write_config(paths, VALID)
    loaded = config.Config.load()
    assert (loaded.source_channel_id, loaded.backup_channel_id) == ("UC1", "UC2")
    assert loaded.http_chunk_size == config.HTTP_CHUNK_SIZE_MB * 1024 * 1024


def test_should_do_full_backup_depends_on_state(paths):
    write_config(paths, VALID)
    loaded = config.Config.load()
    loaded.initial_full_backup = True
    assert loaded.should_do_full_backup({}) is True
    assert loaded.should_do_full_backup({"full_backup_completed": True}) is False
    loaded.initial_full_backup = False
    assert loaded.should_do_full_backup({}) is False


def test_chunk_size_and_privacy_normalisation(paths):
    write_config(paths, VALID)
    loaded = config.Config.load()
    loaded.upload_chunk_size_mb = -1
    assert loaded.get_chunk_size_bytes() == -1
    loaded.upload_chunk_size_mb = 2
    assert loaded.get_chunk_size_bytes() == 2 * 1024 * 1024
    loaded.video_privacy_status = "PUBLIC"
    assert loaded.get_privacy_status() == "public"
    loaded.video_privacy_status = "bogus"
    assert loaded.get_privacy_status() == "unlisted"


def test_create_default_config_writes_placeholders(paths):
    created = config.create_default_config()
    with open(paths.config_file, encoding="utf-8") as f:
        assert json.load(f) == created
    assert created["source_channel_id"].startswith("YOUR_")
