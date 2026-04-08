#!/usr/bin/env python3
"""
transcribe_audio_util.py - Transcribe a WAV audio file to text using Vosk.
"""

import json
import os
import wave

from vosk import Model, KaldiRecognizer

AUDIO_FRAME_SIZE = 4000


def transcribe_audio(audio_file, model_path, audio_dir, transcript_dir):
    """Transcribe audio_file to text using a Vosk model and save a .txt transcript."""
    audio_file_path = os.path.join(audio_dir, audio_file)

    model = Model(model_path)

    wf = wave.open(audio_file_path, "rb")

    rec = KaldiRecognizer(model, wf.getframerate())

    transcript = ""
    while True:
        data = wf.readframes(AUDIO_FRAME_SIZE)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            transcript += result['text'] + "\n"

    result = json.loads(rec.FinalResult())
    transcript += result['text']

    if not os.path.exists(transcript_dir):
        os.makedirs(transcript_dir)

    txt_file_name = os.path.splitext(os.path.basename(audio_file))[0] + ".txt"
    txt_file_path = os.path.join(transcript_dir, txt_file_name)
    with open(txt_file_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    return txt_file_name
