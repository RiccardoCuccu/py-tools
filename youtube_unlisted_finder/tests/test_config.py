"""Tests for config.first_run_setup and configuration invariants."""

import config


def test_setup_without_client_secret_prints_steps_and_returns_false(
    paths, capsys
):
    assert config.first_run_setup() is False
    out = capsys.readouterr().out
    assert "client_secret.json" in out
    assert str(paths.client_secret_file) in out
    assert str(paths.config_dir) in out
    for step in range(1, 6):
        assert f"STEP {step} - " in out
    assert "{" not in out


def test_setup_with_client_secret_returns_true(paths):
    paths.client_secret_file.write_text("{}", encoding="utf-8")
    assert config.first_run_setup() is True


def test_setup_creates_missing_config_dir(paths, tmp_path, monkeypatch):
    missing = tmp_path / "new_config"
    monkeypatch.setattr(config, "CONFIG_DIR", str(missing))
    monkeypatch.setattr(config, "CLIENT_SECRET_FILE", str(missing / "c.json"))
    config.first_run_setup()
    assert missing.is_dir()


def test_default_format_is_valid():
    assert config.DEFAULT_FORMAT in config.VALID_FORMATS


def test_scope_is_read_only():
    assert config.SCOPES == ["https://www.googleapis.com/auth/youtube.readonly"]
