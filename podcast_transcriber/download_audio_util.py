#!/usr/bin/env python3
"""
download_audio_util.py - Download a podcast episode audio file and convert it to mono 16kHz WAV.
"""

import hashlib
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

# Download settings
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_SIZE = 8192

# Audio conversion settings
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS_MONO = 1

# File naming settings
DOWNLOAD_SUFFIX = ".download"
WAV_SUFFIX = ".wav"
MAX_FILENAME_STEM_LENGTH = 100
FALLBACK_STEM_PREFIX = "episode"
URL_HASH_LENGTH = 8
# Windows device names cannot be used as file names, with or without an extension
WINDOWS_RESERVED_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)]
)

# Temp file removal retries (ffmpeg may briefly hold the handle on Windows)
REMOVE_RETRIES = 3
REMOVE_RETRY_DELAY_SECONDS = 0.5

_ffmpeg_configured = False


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
    """Locate ffmpeg/ffprobe and configure pydub once. Raises RuntimeError if not found."""
    global _ffmpeg_configured
    if _ffmpeg_configured:
        return

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

    _ffmpeg_configured = True


def _remove_file(path):
    """Delete a file if present, retrying briefly because Windows may still hold the handle."""
    for attempt in range(REMOVE_RETRIES):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except OSError:
            if attempt < REMOVE_RETRIES - 1:
                time.sleep(REMOVE_RETRY_DELAY_SECONDS)
            else:
                print(f"Warning: could not delete temporary file {path}", file=sys.stderr)


def _download_audio_file(url, dest_path):
    """Stream an audio file from url and write it to dest_path."""
    with requests.get(
        url, stream=True, allow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS
    ) as response:
        response.raise_for_status()

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)


def _convert_to_wav(source_path, wav_path):
    """Convert any ffmpeg-readable audio file (mp3, m4a, ...) to mono 16kHz WAV using pydub."""
    audio = AudioSegment.from_file(source_path)
    audio = audio.set_channels(AUDIO_CHANNELS_MONO).set_frame_rate(AUDIO_SAMPLE_RATE)
    audio.export(wav_path, format="wav")


def _safe_filename_from_url(url):
    """Derive a sanitized filename stem from the audio URL.

    Strips percent-encoding, accented characters, emojis, and illegal
    filename characters, then replaces spaces and hyphens with underscores.
    Falls back to a stem based on a hash of the URL when nothing usable is left
    or the name is a reserved Windows device name.
    """
    # Parse before decoding so an encoded "?" or "#" cannot be mistaken for a delimiter
    raw = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0]
    # Normalize accents to their ASCII base letters
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    # Replace spaces and hyphens with underscores, strip everything else illegal
    cleaned = re.sub(r"[^\w\s-]", "", ascii_only)
    stem = re.sub(r"[\s-]+", "_", cleaned).strip("_")[:MAX_FILENAME_STEM_LENGTH].strip("_")

    if not stem or stem.lower() in WINDOWS_RESERVED_NAMES:
        url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:URL_HASH_LENGTH]
        return f"{FALLBACK_STEM_PREFIX}_{url_hash}"

    return stem


def download_audio(episode_url, audio_dir):
    """Download episode audio and convert to mono 16kHz WAV for transcription."""
    _configure_ffmpeg()
    safe_filename = _safe_filename_from_url(episode_url)

    os.makedirs(audio_dir, exist_ok=True)

    # Neutral extension: the real container (mp3, m4a, ...) is detected by ffmpeg
    download_path = os.path.join(audio_dir, f"{safe_filename}{DOWNLOAD_SUFFIX}")
    wav_path = os.path.join(audio_dir, f"{safe_filename}{WAV_SUFFIX}")

    try:
        _download_audio_file(episode_url, download_path)

        if not os.path.exists(download_path) or os.path.getsize(download_path) == 0:
            raise RuntimeError(f"Downloaded file {download_path} is invalid or empty.")

        try:
            _convert_to_wav(download_path, wav_path)
        except Exception as e:
            # Never leave a truncated WAV that a later run could mistake for a good one
            _remove_file(wav_path)
            raise RuntimeError(f"Audio conversion failed: {e}") from e
    finally:
        _remove_file(download_path)

    return f"{safe_filename}{WAV_SUFFIX}"
