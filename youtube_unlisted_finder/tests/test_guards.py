"""Tests that the conftest guards fail loudly on forbidden side effects."""

import os
import socket
import subprocess
import sys

import pytest

from conftest import TOOL_DIR


def test_network_access_is_blocked():
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_writes_inside_tool_dir_are_blocked():
    with pytest.raises(AssertionError, match="source tree"):
        open(TOOL_DIR / "config" / "guard_probe.txt", "w", encoding="utf-8")


def test_directory_creation_inside_tool_dir_is_blocked():
    with pytest.raises(AssertionError, match="source tree"):
        (TOOL_DIR / "reports_guard_probe").mkdir()


def test_writes_inside_tmp_path_are_allowed(tmp_path):
    probe = tmp_path / "probe.txt"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"


def test_production_paths_point_to_tmp(paths):
    import config
    import report
    import utils
    import youtube_client

    assert str(TOOL_DIR) not in config.TOKEN_FILE
    assert str(TOOL_DIR) not in config.CLIENT_SECRET_FILE
    assert str(TOOL_DIR) not in utils.LOG_FILE
    assert str(TOOL_DIR) not in report.REPORTS_DIR
    assert youtube_client.TOKEN_FILE == config.TOKEN_FILE


def test_replace_into_tool_dir_is_blocked(tmp_path):
    source = tmp_path / "src.txt"
    source.write_text("x", encoding="utf-8")
    with pytest.raises(AssertionError, match="source tree"):
        os.replace(source, TOOL_DIR / "replaced_guard_probe.txt")


def test_rename_into_tool_dir_is_blocked(tmp_path):
    source = tmp_path / "src.txt"
    source.write_text("x", encoding="utf-8")
    with pytest.raises(AssertionError, match="source tree"):
        os.rename(source, TOOL_DIR / "renamed_guard_probe.txt")


def test_remove_inside_tool_dir_is_blocked():
    with pytest.raises(AssertionError, match="source tree"):
        os.remove(TOOL_DIR / "main.py.guard_probe")


def test_subprocess_is_blocked():
    with pytest.raises(AssertionError, match="process"):
        subprocess.Popen([sys.executable, "-c", "pass"])


def test_os_system_is_blocked():
    with pytest.raises(AssertionError, match="process"):
        os.system("echo guard")
