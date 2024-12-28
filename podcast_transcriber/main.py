from podcast_info_util import podcast_info
from episode_link_util import episode_link
from download_audio_util import download_audio
from model_path_util import model_path
from transcribe_audio_util import transcribe_audio
from cleanup_util import cleanup

def main(podcast_url):
    try:

        # Define folder paths
        model_dir = "models"
        audio_dir = "audios"
        transcript_dir = "transcripts"

        # Get the podcast title from the Apple Podcast URL
        podcast_id, episode_title_parsed, episode_title_real = podcast_info(podcast_url)
        print(f"Podcast info fetched successfully.")
        print(f"-- Podcast title: {episode_title_real} ({episode_title_parsed})")
        print(f"-- Podcast ID: {podcast_id}")

        # Get the RSS feed URL from the iTunes API and find the original episode link
        episode_fetched = episode_link(podcast_id, episode_title_parsed, episode_title_real)
        print("Episode link fetched successfully.")
        print(f"-- Episode link: {episode_fetched}")

        # Download the audio for the specified episode
        audio_file = download_audio(episode_fetched, episode_title_parsed, audio_dir)
        print("Audio downloaded successfully.")
        print(f"-- Audio file: {audio_file}")

        # Get the model path from the model selector
        model_directory = model_path(model_dir)
        print("Model selected successfully.")
        print(f"-- Model selected: {model_directory.split("model\\")[-1]}")

        # Transcribe the audio file using Vosk with the selected model
        transcript_file = transcribe_audio(audio_file, model_directory, audio_dir, transcript_dir)
        print("Audio transcription completed successfully.")
        print(f"-- Transcript file: {transcript_file}")

        # Perform cleanup
        cleanup()
        print("Cleanup completed successfully.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Ask the user to input the Apple Podcasts episode URL
    podcast_url = input("Enter the Apple Podcasts episode URL: ")
    main(podcast_url)
