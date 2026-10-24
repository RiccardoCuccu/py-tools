"""Tests for model_path_util: model discovery and interactive selection (temp folders only)."""

from pathlib import Path

import pytest

import model_path_util as mp


def make_models(root: Path, *names: str) -> Path:
    """Create empty model folders (and one stray file) under root and return root."""
    root.mkdir()
    for name in names:
        (root / name).mkdir()
    (root / "readme.txt").write_text("not a model", encoding="utf-8")
    return root


def feed_inputs(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    """Make input() return the given answers in order."""
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(iterator))


def test_missing_models_folder_raises_clear_error(tmp_path: Path) -> None:
    """A missing folder names itself in the error instead of a bare listdir failure."""
    with pytest.raises(FileNotFoundError, match="does not exist"):
        mp.model_path(str(tmp_path / "models"))


def test_empty_models_folder_raises(tmp_path: Path) -> None:
    """A folder without model directories points the user to the download page."""
    root = make_models(tmp_path / "models")

    with pytest.raises(FileNotFoundError, match="No models found"):
        mp.model_path(str(root))


def test_single_model_is_selected_without_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exactly one model is returned directly; files are not counted as models."""
    root = make_models(tmp_path / "models", "vosk-model-small")
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not prompt"))

    assert Path(mp.model_path(str(root))).name == "vosk-model-small"


def test_multiple_models_list_is_sorted(tmp_path: Path) -> None:
    """Model names come back in a stable, sorted order."""
    root = make_models(tmp_path / "models", "b-model", "a-model", "c-model")
    assert mp.list_model_names(str(root)) == ["a-model", "b-model", "c-model"]


def test_multiple_models_prompt_selects_by_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The chosen number maps onto the sorted list."""
    root = make_models(tmp_path / "models", "b-model", "a-model")
    feed_inputs(monkeypatch, "2")

    assert Path(mp.model_path(str(root))).name == "b-model"


def test_invalid_answers_are_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-numbers and out-of-range numbers re-prompt until a valid choice arrives."""
    root = make_models(tmp_path / "models", "a-model", "b-model")
    feed_inputs(monkeypatch, "abc", "0", "3", "-1", "1")

    assert Path(mp.model_path(str(root))).name == "a-model"
    out = capsys.readouterr().out
    assert "Please enter a number" in out
    assert out.count("Invalid selection") == 3
