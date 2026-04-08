#!/usr/bin/env python3
"""
download_audio_util.py - Download a podcast episode audio file and convert it to mono 16kHz WAV.
"""

import os
import re
import shutil
import sys
import time
import unicodedata
import warnings
from urllib.parse import unquote, urlparse

# Suppress pydub's ffmpeg/ffprobe detection warnings before import - we configure
# the paths ourselves, so the warnings fire before we can set AudioSegment.converter
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pydub")

import requests
import pydub.utils
from pydub import AudioSegment


def _find_ffmpeg_binary(name):
    """Return the path to a ffmpeg-suite binary, or None if not found."""
    path = shutil.which(name)
    if path:
        return path

    # Fallback: common Windows install locations when PATH is not yet updated
    if sys.platform == "win32":
        candidates = [
            rf"C:\Program Files\FFmpeg\bin\{name}.exe",
            rf"C:\ffmpeg\bin\{name}.exe",
            rf"C:\tools\ffmpeg\bin\{name}.exe",
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

    return None


def _configure_ffmpeg():
    """Locate ffmpeg/ffprobe and configure pydub. Raises RuntimeError if not found."""
    ffmpeg_path = _find_ffmpeg_binary("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg and add its bin directory to "
            "your Windows System PATH.\n"
            "Download: https://www.gyan.dev/ffmpeg/builds/ (ffmpeg-release-essentials.zip)\n"
            "Then add the bin folder (e.g. C:\\Program Files\\FFmpeg\\bin) to "
            "System PATH via: Start > Edit the system environment variables > "
            "Environment Variables > System variables > Path."
        )
    AudioSegment.converter = ffmpeg_path

    # Monkey-patch pydub's prober lookup so ffprobe warnings are also suppressed
    ffprobe_path = _find_ffmpeg_binary("ffprobe")
    if ffprobe_path:
        pydub.utils.get_prober_name = lambda: ffprobe_path


_configure_ffmpeg()

# Download settings
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_SIZE = 8192

# Audio conversion settings
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS_MONO = 1


def _download_mp3(url, dest_path):
    """Stream an audio file from url and write it to dest_path."""
    response = requests.get(url, stream=True, allow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            f.write(chunk)


def _convert_to_wav(mp3_path, wav_path):
    """Convert an MP3 file to mono 16kHz WAV using pydub."""
    audio = AudioSegment.from_mp3(mp3_path)
    audio = audio.set_channels(AUDIO_CHANNELS_MONO).set_frame_rate(AUDIO_SAMPLE_RATE)
    audio.export(wav_path, format="wav")


def _safe_filename_from_url(url):
    """Derive a sanitized filename stem from the MP3 URL.

    Strips percent-encoding, accented characters, emojis, and illegal
    filename characters, then replaces spaces and hyphens with underscores.
    """
    raw = os.path.splitext(os.path.basename(urlparse(unquote(url)).path))[0]
    # Normalize accents to their ASCII base letters
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    # Replace spaces and hyphens with underscores, strip everything else illegal
    cleaned = re.sub(r"[^\w\s-]", "", ascii_only)
    return re.sub(r"[\s-]+", "_", cleaned).strip("_")


def download_audio(episode_url, audio_dir):
    """Download episode audio and convert to mono 16kHz WAV for transcription."""
    safe_filename = _safe_filename_from_url(episode_url)

    if not os.path.exists(audio_dir):
        os.makedirs(audio_dir)

    mp3_path = os.path.join(audio_dir, f"{safe_filename}.mp3")
    wav_path = os.path.join(audio_dir, f"{safe_filename}.wav")

    try:
        _download_mp3(episode_url, mp3_path)
    except KeyboardInterrupt:
        raise

    if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
        raise Exception(f"Downloaded file {mp3_path} is invalid or empty.")

    try:
        _convert_to_wav(mp3_path, wav_path)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        raise Exception(f"Audio conversion failed: {e}") from e
    finally:
        # Retry deletion - on Windows, ffmpeg may briefly hold the file handle
        # after the subprocess exits, causing WinError 32
        for attempt in range(3):
            try:
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)
                break
            except OSError:
                if attempt < 2:
                    time.sleep(0.5)
                else:
                    raise

    return f"{safe_filename}.wav"
