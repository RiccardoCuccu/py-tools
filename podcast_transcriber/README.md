# Podcast Transcriber

**Purpose:** `podcast_transcriber` downloads and transcribes Apple Podcasts episodes by resolving the audio link through the iTunes lookup API and the show's RSS feed, then converting the audio to text with a local Vosk speech recognition model.

## How it Works

- Validates the Apple Podcasts URL and extracts the podcast ID and episode title from it and from the episode page.
- Looks up the show's RSS feed through the iTunes API and picks the episode whose title is most similar, preferring an audio enclosure.
- Downloads the audio with `requests` (with timeouts, any ffmpeg-readable format) and converts it to a mono 16kHz WAV with ffmpeg through pydub, removing the temporary download even on failure.
- If multiple Vosk models are present in `models/`, prompts the user to pick one; otherwise selects the only available model automatically.
- Transcribes the audio frame by frame with Vosk's KaldiRecognizer and saves the result as a text file in `transcripts/`.
- Deletes the tool's own `__pycache__` directory after the run and exits with code 1 if any step fails.
- Resolves `models/`, `audios/` and `transcripts/` next to the script, so it can be started from any working directory.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

`pydub` requires `ffmpeg` for audio decoding. Install it and make sure it is available on PATH. See the [official FFmpeg installation guide](https://ffmpeg.org/download.html).

Download a Vosk speech recognition model from https://alphacephei.com/vosk/models and place the model folder inside the `models/` directory.

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python main.py
```

Provide the Apple Podcasts episode URL when prompted (for example `https://podcasts.apple.com/us/podcast/episode-title/id123456789?i=1000000000`).

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```
