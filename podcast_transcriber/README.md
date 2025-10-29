# Podcast Transcriber

**Purpose:** `podcast_transcriber` is a tool designed to download and transcribe audio from podcast episodes available on Apple Podcasts. It automates the entire process of retrieving podcast metadata, downloading the episode audio, and converting it into a text transcript using the Vosk speech recognition engine.

## How it Works

- The script first extracts the podcast ID and episode title from an Apple Podcast URL using the iTunes API. It fetches relevant metadata, including the podcast's RSS feed, which contains the necessary details about the episode.
- Once the metadata is obtained, the script identifies the direct link to the original episode audio by parsing the RSS feed and searching for the closest match to the episode title.
- After the episode link is found, the script downloads the audio using `yt-dlp` and converts it to a WAV file. The audio is processed using `FFmpeg`, converting it to a mono 16kHz WAV format for better compatibility with the transcription engine.
- The Vosk model is used for transcription. If multiple Vosk models are available in the local directory, the script prompts the user to choose one. If only one model is present, it is automatically selected.
- The audio file is transcribed using the Vosk engine. The KaldiRecognizer is initialized with the selected model, and the audio is processed frame by frame to generate the transcript. The final transcript is saved as a text file in a specified directory.
- After the transcription, the script performs cleanup operations deleting the `__pycache__` directory.

## Installation

To use `podcast_transcriber`, you'll need to install the following Python libraries:
```
pip install yt-dlp requests feedparser beautifulsoup4 vosk pydub
```
Additionally, `ffmpeg` must be installed on your system and accessible via the command line. Follow the [official FFmpeg installation guide](https://ffmpeg.org/download.html) for your operating system.

Moreover, it is necessary to download a Vosk speech recognition model. You can find and download the appropriate model from [https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models), then place the downloaded model in the `models` directory where the script will locate it.

Once everything is installed, you can run the main script and provide the link to the Apple Podcasts episode you wish to transcribe, and the script will handle the rest.