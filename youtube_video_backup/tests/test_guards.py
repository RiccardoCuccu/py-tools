"""Tests that the conftest guards fail loudly on forbidden side effects."""

import socket

import pytest

from conftest import TOOL_DIR


def test_network_access_is_blocked():
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_writes_inside_tool_dir_are_blocked():
    with pytest.raises(AssertionError, match="source tree"):
        open(TOOL_DIR / "config" / "guard_probe.txt", "w", encoding="utf-8")


def test_production_paths_point_to_tmp(paths):
    import config
    import utils

    assert str(TOOL_DIR) not in config.ARCHIVE_FILE
    assert str(TOOL_DIR) not in utils.LOG_FILE
