import yt_dlp
import subprocess
import os

def download_audio(episode_link, episode_title_parsed, audio_dir):
    # Replace hyphens with underscores in the episode title for file naming
    safe_filename = episode_title_parsed.replace("-", "_")
    
    # Create the specified 'audio_dir' if it doesn't exist
    if not os.path.exists(audio_dir):
        os.makedirs(audio_dir)

    # Download the audio using yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(audio_dir, f'{safe_filename}.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }]
    }

    # Use yt-dlp to download the audio
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([episode_link])

    # Check if the downloaded file exists and is valid
    input_wav = os.path.join(audio_dir, f"{safe_filename}.wav")
    temp_wav = os.path.join(audio_dir, f"{safe_filename}_temp.wav")
    
    if not os.path.exists(input_wav) or os.path.getsize(input_wav) == 0:
        raise Exception(f"Downloaded WAV file {input_wav} is invalid or empty.")

    try:
        # Use ffmpeg to convert the intermediate WAV to the final format
        command = [
            'ffmpeg', '-y', '-i', input_wav,
            '-ac', '1',  # Set to mono
            '-ar', '16000',  # Set to 16000 Hz sample rate
            temp_wav
        ]

        # Run the ffmpeg command
        result = subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if result.returncode != 0:
            raise Exception(f"ffmpeg failed to convert the file: {temp_wav}")

        os.remove(input_wav)
        os.rename(temp_wav, input_wav)

        # Return only the name of the final WAV file (without path)
        return f"{safe_filename}.wav"

    except Exception as e:
        print(f"Error during processing: {e}")
        raise
