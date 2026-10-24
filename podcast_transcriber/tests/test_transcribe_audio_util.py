"""Tests for transcribe_audio_util with a fake Vosk model (no real model is ever loaded)."""

import json
import wave
from pathlib import Path

import pytest

import transcribe_audio_util as ta

SAMPLE_RATE = 16000


class FakeModel:
    """Stand-in for vosk.Model that records the path it was given."""

    loaded: list[str] = []

    def __init__(self, path: str) -> None:
        FakeModel.loaded.append(path)


class FakeRecognizer:
    """Recognizer that accepts every second frame and yields scripted texts."""

    def __init__(self, model: FakeModel, rate: int) -> None:
        self.rate = rate
        self.calls = 0
        self.texts = ["first sentence", "", "third sentence"]

    def AcceptWaveform(self, data: bytes) -> bool:
        self.calls += 1
        return self.calls % 2 == 1

    def Result(self) -> str:
        return json.dumps({"text": self.texts.pop(0)})

    def FinalResult(self) -> str:
        return json.dumps({"text": "final words"})


@pytest.fixture(autouse=True)
def _fake_vosk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the Vosk classes so no model file is needed."""
    FakeModel.loaded = []
    monkeypatch.setattr(ta, "Model", FakeModel)
    monkeypatch.setattr(ta, "KaldiRecognizer", FakeRecognizer)


def write_wav(path: Path, frames: int, channels: int = 1, width: int = 2) -> None:
    """Write a silent PCM WAV file with the given shape."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"\x00" * frames * channels * width)


def test_transcribe_writes_transcript_without_empty_segments(tmp_path: Path) -> None:
    """Segments are joined by newlines and empty ones (silence) are dropped."""
    audio_dir, out_dir = tmp_path / "audios", tmp_path / "transcripts"
    audio_dir.mkdir()
    write_wav(audio_dir / "ep.wav", frames=ta.AUDIO_FRAME_SIZE * 5)

    name = ta.transcribe_audio("ep.wav", "model-dir", str(audio_dir), str(out_dir))

    assert name == "ep.txt"
    text = (out_dir / "ep.txt").read_text(encoding="utf-8")
    assert text == "first sentence\nthird sentence\nfinal words"
    assert FakeModel.loaded == ["model-dir"]


def test_transcribe_creates_transcript_dir_and_handles_empty_audio(tmp_path: Path) -> None:
    """A WAV with no frames produces a transcript holding only the final result."""
    audio_dir, out_dir = tmp_path / "audios", tmp_path / "nested" / "transcripts"
    audio_dir.mkdir()
    write_wav(audio_dir / "empty.wav", frames=0)

    ta.transcribe_audio("empty.wav", "m", str(audio_dir), str(out_dir))

    assert (out_dir / "empty.txt").read_text(encoding="utf-8") == "final words"


@pytest.mark.parametrize(("channels", "width"), [(2, 2), (1, 1), (1, 4)])
def test_transcribe_rejects_non_mono_16bit_audio(tmp_path: Path, channels: int, width: int) -> None:
    """Stereo or non-16-bit audio is refused before a model is loaded or anything is written."""
    audio_dir, out_dir = tmp_path / "audios", tmp_path / "transcripts"
    audio_dir.mkdir()
    write_wav(audio_dir / "bad.wav", frames=100, channels=channels, width=width)

    with pytest.raises(ValueError, match="mono 16-bit"):
        ta.transcribe_audio("bad.wav", "m", str(audio_dir), str(out_dir))

    assert FakeModel.loaded == []
    assert not out_dir.exists()


def test_transcribe_missing_audio_file_raises(tmp_path: Path) -> None:
    """A missing WAV raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        ta.transcribe_audio("nope.wav", "m", str(tmp_path), str(tmp_path / "out"))


def test_transcribe_audio_name_cannot_escape_audio_dir(tmp_path: Path) -> None:
    """Only the base name of the audio file is used, so a path in it cannot leave audio_dir."""
    audio_dir = tmp_path / "audios"
    audio_dir.mkdir()
    write_wav(tmp_path / "outside.wav", frames=10)

    with pytest.raises(FileNotFoundError):
        ta.transcribe_audio("../outside.wav", "m", str(audio_dir), str(tmp_path / "out"))


def test_wav_file_is_closed_after_transcription(tmp_path: Path) -> None:
    """The WAV handle is released, so the file can be deleted right away (matters on Windows)."""
    audio_dir = tmp_path / "audios"
    audio_dir.mkdir()
    wav_path = audio_dir / "ep.wav"
    write_wav(wav_path, frames=10)

    ta.transcribe_audio("ep.wav", "m", str(audio_dir), str(tmp_path / "out"))

    wav_path.unlink()
    assert not wav_path.exists()
