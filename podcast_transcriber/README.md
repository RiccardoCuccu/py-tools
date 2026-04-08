# Podcast Transcriber

**Purpose:** `podcast_transcriber` downloads and transcribes Apple Podcasts episodes by fetching the audio via yt-dlp and converting it to text using a local Vosk speech recognition model.

## How it Works

- Extracts the podcast ID and episode title from the Apple Podcasts URL using the iTunes API and fetches the RSS feed.
- Parses the RSS feed to find the direct audio link matching the requested episode.
- Downloads the audio with yt-dlp and converts it to a mono 16kHz WAV using ffmpeg.
- If multiple Vosk models are present in `models/`, prompts the user to pick one; otherwise selects the only available model automatically.
- Transcribes the audio frame by frame with Vosk's KaldiRecognizer and saves the result as a text file in `transcripts/`.
- Deletes the `__pycache__` directory after the run.

## Usage
```
python main.py
```

Provide the Apple Podcasts episode URL when prompted.

## Installation

```
pip install requests feedparser beautifulsoup4 pydub vosk
```

`pydub` requires `ffmpeg` for MP3 decoding. Install it and make sure it is available on PATH. See the [official FFmpeg installation guide](https://ffmpeg.org/download.html).

Download a Vosk speech recognition model from https://alphacephei.com/vosk/models and place the model folder inside the `models/` directory.
