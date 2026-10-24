"""Tests for the suite-wide guards defined in conftest.py."""

import socket
from pathlib import Path

import pytest

import conftest


def test_network_access_is_blocked() -> None:
    """Any DNS lookup or connection attempt fails loudly instead of leaving the machine."""
    with pytest.raises(AssertionError, match="network"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("93.184.216.34", 80), timeout=1)


@pytest.mark.parametrize(
    "name", [".serpapi_config", "config.json", ".plagiarism_cache", "Thesis_plagiarism_report.txt"]
)
def test_real_user_data_cannot_be_read_or_written(name: str) -> None:
    """Credentials, config, cache and reports in the tool folder are off limits, even for reads."""
    target = conftest.TOOL_DIR / name
    with pytest.raises(AssertionError, match="real user data"):
        open(target, "r", encoding="utf-8")
    with pytest.raises(AssertionError, match="real user data"):
        target.write_text("x", encoding="utf-8")


def test_source_tree_writes_are_blocked() -> None:
    """Creating files elsewhere inside the tool folder is rejected."""
    with pytest.raises(AssertionError, match="source tree"):
        (conftest.TOOL_DIR / "stray_output.txt").write_text("x", encoding="utf-8")


def test_tmp_path_remains_writable(tmp_path: Path) -> None:
    """Locations outside the tool folder are unaffected by the guard."""
    target = tmp_path / "ok.txt"
    target.write_text("ok", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "ok"
