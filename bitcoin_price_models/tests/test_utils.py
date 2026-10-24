"""Tests for utils: Logger, capped download, validated atomic write, prompt, fail.

Every file lives in tmp_path and HTTP is faked; the real log and data are untouched.
"""

import json
import os

import pytest

import utils
from helpers import FakeResponse, TruncatedResponse, failing_urlopen, write_json


class TestLogger:
    def test_info_goes_to_stdout_and_not_to_the_log(self, paths, capsys):
        utils.Logger().log_info("hello")
        captured = capsys.readouterr()
        assert captured.out == "hello\n"
        assert not paths.log_file.exists()

    def test_warning_goes_to_stderr_and_the_log(self, paths, capsys):
        utils.Logger().log_warning("careful")
        assert capsys.readouterr().err == "Warning: careful\n"
        assert "WARNING: careful" in paths.log_file.read_text(encoding="utf-8")

    def test_error_goes_to_stderr_and_the_log(self, paths, capsys):
        utils.Logger().log_error("broken")
        assert capsys.readouterr().err == "Error: broken\n"
        assert "ERROR: broken" in paths.log_file.read_text(encoding="utf-8")

    def test_log_entries_are_appended(self, paths):
        log = utils.Logger()
        log.log_warning("one")
        log.log_error("two")
        lines = paths.log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_log_folder_is_created_when_missing(self, tmp_path, monkeypatch):
        target = tmp_path / "new" / "log.txt"
        monkeypatch.setattr(utils, "LOG_FILE", str(target))
        utils.Logger().log_error("x")
        assert target.exists()


    def test_unwritable_log_path_does_not_raise(self, tmp_path, monkeypatch, capsys):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file, not a folder", encoding="utf-8")
        monkeypatch.setattr(utils, "LOG_FILE", str(blocker / "log.txt"))
        utils.Logger().log_warning("still shown")
        assert capsys.readouterr().err == "Warning: still shown\n"


class TestFail:
    def test_logs_the_error_and_exits_with_failure_code(self, paths, capsys):
        with pytest.raises(SystemExit) as info:
            utils.fail("boom")
        assert info.value.code == 1
        assert "Error: boom" in capsys.readouterr().err
        assert "ERROR: boom" in paths.log_file.read_text(encoding="utf-8")


class TestAskYesNo:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [("y", True), ("YES", True), (" y ", True), ("n", False), ("", False)],
    )
    def test_answers(self, monkeypatch, answer, expected):
        monkeypatch.setattr("builtins.input", lambda *_a: answer)
        assert utils.ask_yes_no("?") is expected

    @pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
    def test_eof_and_interrupt_count_as_no(self, monkeypatch, error):
        def raise_error(*_a):
            raise error

        monkeypatch.setattr("builtins.input", raise_error)
        assert utils.ask_yes_no("?") is False


class TestFetchBytes:
    URL = "https://example.invalid/data"

    def test_returns_the_body(self, monkeypatch):
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"abc")
        )
        assert utils.fetch_bytes(self.URL) == b"abc"

    def test_network_error_becomes_connection_error(self, monkeypatch):
        monkeypatch.setattr(utils.urllib.request, "urlopen", failing_urlopen)
        with pytest.raises(ConnectionError, match="could not download .*: "):
            utils.fetch_bytes(self.URL)

    def test_incomplete_read_becomes_connection_error(self, monkeypatch):
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: TruncatedResponse(b"")
        )
        with pytest.raises(ConnectionError):
            utils.fetch_bytes(self.URL)

    def test_oversized_response_rejected(self, monkeypatch):
        body = b"x" * 10
        monkeypatch.setattr(utils, "MAX_DOWNLOAD_BYTES", len(body) - 1)
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)
        )
        with pytest.raises(ValueError, match="exceeds"):
            utils.fetch_bytes(self.URL)

    def test_response_at_size_cap_accepted(self, monkeypatch):
        body = b"x" * 10
        monkeypatch.setattr(utils, "MAX_DOWNLOAD_BYTES", len(body))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)
        )
        assert utils.fetch_bytes(self.URL) == body


def accept(_path):
    """Validator that accepts any file."""


def reject(_path):
    """Validator that rejects any file."""
    raise ValueError("no usable prices")


class TestWriteValidated:
    PAYLOAD = {"market-price": [{"x": 1, "y": 2.0}]}

    def test_writes_the_file_atomically(self, tmp_path):
        target = tmp_path / "out.json"
        utils.write_validated(self.PAYLOAD, str(target), accept)
        assert json.loads(target.read_text(encoding="utf-8")) == self.PAYLOAD
        assert list(tmp_path.iterdir()) == [target]

    def test_creates_the_missing_folder(self, tmp_path):
        target = tmp_path / "nested" / "out.json"
        utils.write_validated(self.PAYLOAD, str(target), accept)
        assert target.exists()

    def test_validator_receives_a_readable_temp_file(self, tmp_path):
        seen = []

        def validate(path):
            seen.append(json.loads(open(path, encoding="utf-8").read()))

        utils.write_validated(self.PAYLOAD, str(tmp_path / "out.json"), validate)
        assert seen == [self.PAYLOAD]

    def test_rejected_data_keeps_existing_file(self, tmp_path):
        target = write_json(tmp_path / "out.json", {"old": True})
        before = target.read_text(encoding="utf-8")
        with pytest.raises(ValueError, match="unusable"):
            utils.write_validated(self.PAYLOAD, str(target), reject)
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    def test_fdopen_failure_closes_descriptor_and_cleans_up(
        self, tmp_path, monkeypatch
    ):
        closed: list[int] = []
        real_close = os.close

        def boom(*_a, **_k):
            raise MemoryError("no handle")

        def tracking_close(fd):
            closed.append(fd)
            real_close(fd)

        monkeypatch.setattr(utils.os, "fdopen", boom)
        monkeypatch.setattr(utils.os, "close", tracking_close)
        with pytest.raises(MemoryError):
            utils.write_validated(self.PAYLOAD, str(tmp_path / "out.json"), accept)
        assert len(closed) == 1
        assert list(tmp_path.iterdir()) == []

    def test_cleanup_failure_does_not_mask_original_error(self, tmp_path, monkeypatch):
        def locked(*_a, **_k):
            raise PermissionError("locked")

        monkeypatch.setattr(utils.os, "replace", locked)
        real_remove = os.remove

        def remove_fails(path):
            real_remove(path)
            raise PermissionError("remove failed")

        monkeypatch.setattr(utils.os, "remove", remove_fails)
        with pytest.raises(PermissionError, match="locked"):
            utils.write_validated(self.PAYLOAD, str(tmp_path / "out.json"), accept)

    def test_write_failure_cleans_temp_file(self, tmp_path, monkeypatch):
        target = write_json(tmp_path / "out.json", {"old": True})

        def boom(*_a, **_k):
            raise PermissionError("locked")

        monkeypatch.setattr(utils.os, "replace", boom)
        with pytest.raises(PermissionError):
            utils.write_validated(self.PAYLOAD, str(target), accept)
        assert list(tmp_path.iterdir()) == [target]
