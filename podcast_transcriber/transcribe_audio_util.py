#!/usr/bin/env python3
"""
transcribe_audio_util.py - Transcribe a WAV audio file to text using Vosk.
"""

import json
import os
import wave

from vosk import Model, KaldiRecognizer

AUDIO_FRAME_SIZE = 4000
REQUIRED_CHANNELS = 1
REQUIRED_SAMPLE_WIDTH_BYTES = 2
TRANSCRIPT_SUFFIX = ".txt"


def transcribe_audio(audio_file, model_path, audio_dir, transcript_dir):
    """Transcribe audio_file to text using a Vosk model and save a .txt transcript.

    The audio must be mono 16-bit PCM WAV (what download_audio produces). Raises
    ValueError otherwise, since Vosk would silently return garbage.
    """
    audio_file_path = os.path.join(audio_dir, os.path.basename(audio_file))

    with wave.open(audio_file_path, "rb") as wf:
        if wf.getnchannels() != REQUIRED_CHANNELS or wf.getsampwidth() != REQUIRED_SAMPLE_WIDTH_BYTES:
            raise ValueError(f"{audio_file} must be a mono 16-bit PCM WAV file")

        model = Model(model_path)
        rec = KaldiRecognizer(model, wf.getframerate())

        segments = []
        while True:
            data = wf.readframes(AUDIO_FRAME_SIZE)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                segments.append(json.loads(rec.Result()).get("text", ""))

        segments.append(json.loads(rec.FinalResult()).get("text", ""))

    # Drop empty segments produced by silence
    transcript = "\n".join(s for s in segments if s)

    os.makedirs(transcript_dir, exist_ok=True)

    txt_file_name = os.path.splitext(os.path.basename(audio_file))[0] + TRANSCRIPT_SUFFIX
    txt_file_path = os.path.join(transcript_dir, txt_file_name)
    with open(txt_file_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    return txt_file_name
