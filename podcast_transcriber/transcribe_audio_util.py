import wave
import json
from pydub import AudioSegment
from vosk import Model, KaldiRecognizer
import os

def transcribe_audio(audio_file, model_path, audio_dir, transcript_dir):
    # Construct the full path to the audio file in the audio directory
    audio_file_path = os.path.join(audio_dir, audio_file)

    # Load the selected Vosk model using the passed model path
    model = Model(model_path)

    # Open the audio file using wave
    wf = wave.open(audio_file_path, "rb")

    # Initialize KaldiRecognizer
    rec = KaldiRecognizer(model, wf.getframerate())

    # Transcribe audio
    transcript = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            transcript += result['text'] + "\n"

    # Process the final part of the transcription
    result = json.loads(rec.FinalResult())
    transcript += result['text']

    # Ensure the transcript directory exists
    if not os.path.exists(transcript_dir):
        os.makedirs(transcript_dir)

    # Save the transcript to a .txt file in the specified transcript directory
    txt_file_name = os.path.splitext(os.path.basename(audio_file))[0] + ".txt"
    txt_file_path = os.path.join(transcript_dir, txt_file_name)
    with open(txt_file_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    # Return only the name of the .txt file, not the full path
    return txt_file_name
