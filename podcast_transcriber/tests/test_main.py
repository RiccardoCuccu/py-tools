"""Tests for main: pipeline wiring, path anchoring and error handling (all stages faked)."""

import os
from pathlib import Path

import pytest

import main as app


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace every pipeline stage with a fake and record the calls in order."""
    calls: list[tuple] = []

    def record(name: str, result: object):
        def fake(*args: object) -> object:
            calls.append((name, *args))
            return result

        return fake

    monkeypatch.setattr(app, "podcast_info", record("info", ("42", "slug title", "Real Title")))
    monkeypatch.setattr(app, "episode_link", record("link", "https://cdn.example/a.mp3"))
    monkeypatch.setattr(app, "download_audio", record("download", "a.wav"))
    monkeypatch.setattr(app, "model_path", record("model", os.path.join("models", "vosk-it")))
    monkeypatch.setattr(app, "transcribe_audio", record("transcribe", "a.txt"))
    monkeypatch.setattr(app, "cleanup", record("cleanup", None))
    return calls


def test_folders_are_anchored_to_the_script_directory() -> None:
    """Models, audio and transcripts live beside main.py, not in the working directory."""
    script_dir = Path(app.__file__).resolve().parent
    for folder, name in ((app.MODEL_DIR, "models"), (app.AUDIO_DIR, "audios"), (app.TRANSCRIPT_DIR, "transcripts")):
        assert Path(folder).resolve() == script_dir / name


def test_success_runs_every_stage_in_order_and_returns_zero(
    pipeline: list[tuple], capsys: pytest.CaptureFixture[str]
) -> None:
    """Stages are chained with each other's output and the exit code is 0."""
    code = app.main("https://podcasts.apple.com/us/podcast/x/id42")

    assert code == 0
    assert [c[0] for c in pipeline] == ["info", "link", "download", "model", "transcribe", "cleanup"]
    assert pipeline[1][1:] == ("42", "slug title", "Real Title")
    assert pipeline[2][1:] == ("https://cdn.example/a.mp3", app.AUDIO_DIR)
    assert pipeline[4][1:] == ("a.wav", os.path.join("models", "vosk-it"), app.AUDIO_DIR, app.TRANSCRIPT_DIR)
    out = capsys.readouterr().out
    assert "-- Model selected: vosk-it" in out
    assert "-- Transcript file: a.txt" in out


def test_failure_reports_on_stderr_returns_one_and_still_cleans_up(
    pipeline: list[tuple], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stage error stops the pipeline, goes to stderr, exits 1 and cleanup still runs."""

    def failing(*args: object) -> None:
        raise LookupError("Episode not found in the RSS feed.")

    monkeypatch.setattr(app, "episode_link", failing)

    code = app.main("https://podcasts.apple.com/us/podcast/x/id42")

    captured = capsys.readouterr()
    assert code == 1
    assert "Episode not found" in captured.err
    assert [c[0] for c in pipeline] == ["info", "cleanup"]


def test_keyboard_interrupt_aborts_with_nonzero_exit(
    pipeline: list[tuple], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl+C prints 'Aborted.' and returns 1."""

    def interrupted(*args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "download_audio", interrupted)

    assert app.main("https://podcasts.apple.com/us/podcast/x/id42") == 1
    assert "Aborted." in capsys.readouterr().out
