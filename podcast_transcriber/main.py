#!/usr/bin/env python3
"""
Podcast Transcriber - Download and transcribe Apple Podcasts episodes using Vosk.

Prompts for an Apple Podcasts episode URL, downloads the audio, and produces
a plain-text transcript using a local Vosk speech recognition model.

Usage:
    python main.py

Notes:
    - Download a Vosk model from https://alphacephei.com/vosk/models and place it in models/
"""

from podcast_info_util import podcast_info
from episode_link_util import episode_link
from download_audio_util import download_audio
from model_path_util import model_path
from transcribe_audio_util import transcribe_audio
from cleanup_util import cleanup

MODEL_DIR = "models"
AUDIO_DIR = "audios"
TRANSCRIPT_DIR = "transcripts"


def main(podcast_url):
    """Download a podcast episode and produce a text transcript."""
    try:
        podcast_id, episode_title_parsed, episode_title_real = podcast_info(podcast_url)
        print(f"Podcast info fetched successfully.")
        print(f"-- Podcast title: {episode_title_real} ({episode_title_parsed})")
        print(f"-- Podcast ID: {podcast_id}")

        # Get the RSS feed URL from the iTunes API and find the original episode link
        episode_fetched = episode_link(podcast_id, episode_title_parsed, episode_title_real)
        print("Episode link fetched successfully.")
        print(f"-- Episode link: {episode_fetched}")

        # Download the audio for the specified episode
        audio_file = download_audio(episode_fetched, AUDIO_DIR)
        print("Audio downloaded successfully.")
        print(f"-- Audio file: {audio_file}")

        # Get the model path from the model selector
        model_directory = model_path(MODEL_DIR)
        print("Model selected successfully.")
        print(f"-- Model selected: {model_directory.split('model\\')[-1]}")

        # Transcribe the audio file using Vosk with the selected model
        transcript_file = transcribe_audio(audio_file, model_directory, AUDIO_DIR, TRANSCRIPT_DIR)
        print("Audio transcription completed successfully.")
        print(f"-- Transcript file: {transcript_file}")

        # Perform cleanup of cache files
        cleanup()
        print("Cleanup completed successfully.")

    except KeyboardInterrupt:
        print("\nAborted.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    podcast_url = input("Enter the Apple Podcasts episode URL: ")
    main(podcast_url)
