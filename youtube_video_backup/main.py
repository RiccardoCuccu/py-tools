#!/usr/bin/env python3
"""
YouTube Video Backup - Download videos from a YouTube channel and re-upload them to a backup channel.

Fetches the source channel's video list, downloads each video via yt-dlp, and
re-uploads to a secondary channel as private. Resumes from the last checkpoint.

Usage:
    python main.py
    python main.py --auto-confirm
    python main.py --use-cache
    python main.py --re-fetch
    python main.py --ignore-quota-warning

    # Fully automated run - no prompts, use cached data, ignore quota warnings
    python main.py --auto-confirm --use-cache --ignore-quota-warning

    # Automated run that forces a fresh channel fetch
    python main.py --auto-confirm --re-fetch --ignore-quota-warning

Notes:
    - --use-cache and --re-fetch are mutually exclusive.
    - --auto-confirm skips the per-video backup confirmation prompt.
    - --ignore-quota-warning skips the quota-insufficient warning prompt.
    - The cache only matters while a full backup is unfinished; incremental runs
      always read the RSS feed and merge it into the cache.
"""

import argparse
import os
import sys
import time
from datetime import datetime

from config import Config, first_run_setup, validate_configuration, DOWNLOAD_DIR
from youtube_client import YouTubeClient, QUOTA_DAILY_LIMIT  # type: ignore
from video_handler import (
    VideoDownloader, upload_video, fatal_upload_reason,
    QUOTA_VIDEO_UPLOAD, QUOTA_THUMBNAIL_UPLOAD,
)
from utils import StorageManager, Logger, safe_remove_files, merge_videos

# Video processing constants
VIDEOS_PER_API_PAGE = 50
ESTIMATED_COST_PER_VIDEO = QUOTA_VIDEO_UPLOAD + QUOTA_THUMBNAIL_UPLOAD  # Upload + thumbnail


def _parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Download videos from a YouTube channel and re-upload them to a backup channel."
        )
    )
    parser.add_argument(
        "--auto-confirm", "-y",
        action="store_true",
        help="Skip the per-video backup confirmation prompt and always proceed.",
    )
    parser.add_argument(
        "--ignore-quota-warning",
        action="store_true",
        default=False,
        help=(
            "Automatically continue when daily API quota may be insufficient, "
            "skipping the 'Continue anyway?' prompt."
        ),
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--use-cache",
        action="store_true",
        default=False,
        help="Use cached channel data when resuming an unfinished full backup (no API cost).",
    )
    cache_group.add_argument(
        "--re-fetch",
        action="store_true",
        default=False,
        help="Ignore cached channel data and re-fetch from the channel.",
    )
    return parser.parse_args()


def _run_download(downloader, video, config, logger, last_upload_time):
    """Attempt to download a video, prompting for retry on failure.

    Returns the video_data dict on success, or None to signal the caller to
    skip this video. Raises SystemExit if the user chooses to quit.
    """
    while True:
        # Apply post-upload delay before the next download
        if last_upload_time is not None and config.download_delay > 0:
            elapsed = time.time() - last_upload_time
            remaining_delay = config.download_delay - elapsed
            if remaining_delay > 0:
                print(f"\n⏳ Waiting {remaining_delay:.1f} more seconds before next download...")
                time.sleep(remaining_delay)
            else:
                print(f"\n✓ Delay already satisfied ({elapsed:.1f}s elapsed since last upload)")

        try:
            video_data = downloader.download(video['url'], DOWNLOAD_DIR)
        except Exception as e:
            logger.log_error(f"Error during download: {e}")
            if ask_retry_operation("download", config.auto_confirm):
                print("\n🔄 Retrying download...")
                continue
            print("⏭️ Skipping this video.")
            return None

        if not video_data['success'] or not video_data['video_file']:
            logger.log_warning("Video file not found after download")
            if ask_retry_operation("download", config.auto_confirm):
                print("\n🔄 Retrying download...")
                continue
            print("⏭️ Skipping this video.")
            return None

        return video_data


def _run_upload(youtube, video_data, config, logger):
    """Attempt to upload a video, prompting for retry on failure.

    Returns the uploaded video ID string on success, or None to signal the
    caller to skip this video. Re-raises the exception if the upload limit or
    API quota is exhausted so the caller can abort the entire run.
    """
    while True:
        try:
            return upload_video(youtube.service, video_data, config, youtube)
        except Exception as e:
            if fatal_upload_reason(e):
                raise
            logger.log_error(f"Error during upload: {e}")
            if ask_retry_operation("upload", config.auto_confirm):
                print("\n🔄 Retrying upload...")
                continue
            print("⏭️ Skipping this video.")
            return None


def _select_source_videos(args, config, storage, youtube, archive, use_full_backup):
    """Decide where the source video list comes from and return it.

    Returns (source_videos, use_full_backup), or None if the user cancelled.
    A cached full list is only reused to resume an unfinished full backup; in
    incremental mode the RSS feed is always read and merged into the cache so
    newly published videos are never hidden by a stale cache.
    """
    cached_videos = storage.get_cached_videos(config.source_channel_id)

    if cached_videos and use_full_backup:
        cache_info = storage.load_channel_videos()
        print(f"\n{'='*60}")
        print("CACHED CHANNEL DATA FOUND")
        print(f"{'='*60}")
        print(f"Found {len(cached_videos)} videos in cache from previous run")
        print(f"Last updated: {cache_info.get('last_updated', 'Unknown')}")
        print("\nOptions:")
        print("  1. Use cached data (recommended - no API cost)")
        print("  2. Re-fetch videos from channel (costs API quota if using full backup)")

        if args.use_cache:
            use_cache = True
            print("\nUsing cached data (--use-cache flag)")
        elif args.re_fetch:
            use_cache = False
            print("\nRe-fetching from channel (--re-fetch flag)")
        elif not config.auto_confirm:
            use_cache = input("\nUse cache? (1/2): ").strip() == '1'
        else:
            use_cache = True
            print("\nAuto-using cache (AUTO_CONFIRM enabled)")

        if use_cache:
            print(f"\nUsing {len(cached_videos)} videos from cache")
            # Still a full backup: completion must be recorded once it finishes
            return cached_videos, True

        print("\nClearing cache and re-fetching...")
        storage.clear_channel_videos_cache()
        cached_videos = []
    elif cached_videos and args.re_fetch:
        print("\nClearing cache and re-fetching...")
        storage.clear_channel_videos_cache()
        cached_videos = []

    if not use_full_backup:
        print(f"\n{'='*60}")
        print("INCREMENTAL MODE - Checking recent videos via RSS")
        print(f"{'='*60}")
        print("Checking for new videos (last ~15 from RSS feed)")
        print("No API quota will be used for video discovery\n")

        source_videos = merge_videos(
            cached_videos, youtube.get_channel_videos_rss(config.source_channel_id)
        )
        storage.update_channel_videos_cache(source_videos, config.source_channel_id)
        return source_videos, False

    # Full backup: estimate quota cost
    estimated_cost = 1 + (len(archive) // VIDEOS_PER_API_PAGE + 1)  # Channel list + backup check
    print("\nEstimated quota cost for this run:")
    print(f"   - Full backup mode: ~{estimated_cost} units (video discovery)")
    print(f"   - Plus: {QUOTA_VIDEO_UPLOAD} units per video uploaded")
    print(f"   - Plus: {QUOTA_THUMBNAIL_UPLOAD} units per thumbnail uploaded")

    remaining = QUOTA_DAILY_LIMIT - youtube.get_quota_today()

    if estimated_cost > remaining:
        print("\n   WARNING: Not enough quota remaining!")
        print(f"   Need ~{estimated_cost} units, have {remaining} units")
        print("   Quota resets at midnight Pacific Time")

        if not args.ignore_quota_warning:
            response = input("\n   Continue anyway? (y/n): ").lower()
            if response != 'y':
                print("Operation cancelled by user")
                return None
        else:
            print("\nContinuing despite quota warning (--ignore-quota-warning)")

    print(f"\n{'='*60}")
    print("FULL BACKUP MODE - First time complete backup")
    print(f"{'='*60}")
    print("This will retrieve ALL videos from the source channel via API")
    print("Using API key (no OAuth needed for public source channel)")
    print(f"Estimated quota cost: ~1 unit per {VIDEOS_PER_API_PAGE} videos")
    print("After completion, future runs will use RSS (free)\n")

    if not config.auto_confirm:
        response = input("Proceed with full backup? (y/n): ").lower()
        if response != 'y':
            print("Full backup cancelled. Set INITIAL_FULL_BACKUP = False to use RSS mode.")
            return None

    source_videos = youtube.get_all_channel_videos_api(config.source_channel_id)
    storage.update_channel_videos_cache(source_videos, config.source_channel_id)
    return source_videos, True


def _record_success(storage, logger, config, video, video_data, uploaded_video_id):
    """Persist the outcome of one successful backup.

    A dry run uploads nothing, so it must not touch the archive, log or counters:
    otherwise the video would be skipped as "backed up" on every real run.
    Returns the updated state dict, or None for a dry run.
    """
    if config.dry_run:
        print(f"\n[DRY RUN] Nothing recorded; {video['id']} stays pending.")
        return None

    storage.save_to_archive(video['id'])
    logger.log_backed_up_video(
        video['id'],
        video['title'],
        video_data['info'].get('channel', 'Unknown Channel'),
        uploaded_video_id
    )

    if config.delete_after_upload:
        print("\nCleaning up temporary files...")
        safe_remove_files(
            video_data.get('video_file'),
            video_data.get('thumbnail_file')
        )
    else:
        print(f"\nFiles kept in: {DOWNLOAD_DIR}")
        print(f"   Video: {os.path.basename(video_data['video_file'])}")
        if video_data.get('thumbnail_file'):
            print(f"   Thumbnail: {os.path.basename(video_data['thumbnail_file'])}")

    print("\nBackup completed successfully!")

    # Reload from disk: the quota counters are written there by the YouTube client
    previous = storage.load_state()
    return storage.update_state(
        total_videos_backed_up=previous.get("total_videos_backed_up", 0) + 1,
        last_backup_date=datetime.now().isoformat(),
    )


def print_backup_summary(videos_backed_up, total_videos, state, quota_used, quota_today, 
                         use_full_backup=False, source_videos_count=0, interruption_reason=None):
    """Print unified backup summary - handles both success and interruption cases"""
    remaining = total_videos - videos_backed_up
    quota_remaining = QUOTA_DAILY_LIMIT - quota_today
    
    # Header - same for all interruptions
    print(f"\n{'='*60}")
    if interruption_reason:
        print(f"BACKUP INTERRUPTED")
    else:
        print(f"🎉 Backup operation completed!")
    print(f"{'='*60}")
    
    # Session results
    print(f"Session Results:")
    if interruption_reason:
        print(f"   • Videos backed up: {videos_backed_up} / {total_videos}")
        print(f"   • Still in queue: {remaining}")
    else:
        print(f"   • Videos backed up this run: {videos_backed_up}")
        print(f"   • Total videos backed up (all time): {state.get('total_videos_backed_up', 0)}")
    
    # Quota breakdown (only if quota was used)
    if quota_used > 0:
        print(f"\n💰 API Quota Usage:")
        print(f"   • Used this session: {quota_used:,} units")
        
        # Show breakdown only if not interrupted or completed successfully
        if not interruption_reason or videos_backed_up > 0:
            if use_full_backup:
                pages = (source_videos_count // VIDEOS_PER_API_PAGE) + 1
                print(f"     - Video discovery: ~{pages} units (API)")
            else:
                print(f"     - Video discovery: 0 units (RSS)")
            
            if videos_backed_up > 0:
                print(f"     - Video uploads: {videos_backed_up * QUOTA_VIDEO_UPLOAD:,} units")
                print(f"     - Thumbnail uploads: {videos_backed_up * QUOTA_THUMBNAIL_UPLOAD:,} units")
        
        print(f"\n   📊 Daily quota summary:")
        print(f"   • Total used today: {quota_today:,} / {QUOTA_DAILY_LIMIT:,} units")
        print(f"   • Remaining: {quota_remaining:,} units")
        
        if quota_today > 8000:
            print(f"\n   WARNING: High quota usage!")
    
    # Interruption-specific information
    if interruption_reason:
        print(f"\nReason: {interruption_reason}")
        
        if "upload limit" in interruption_reason.lower():
            print(f"\n📋 Why this happened:")
            print(f"   YouTube limits daily uploads to ~10-15 videos for")
            print(f"   non-verified accounts (~50-100 for verified accounts).")
            print(f"\n💡 What to do next:")
            print(f"   1. Wait 24 hours for limit reset")
            print(f"   2. Verify your account: https://www.youtube.com/verify")
            print(f"   3. Run this script again - it will resume automatically")
        else:
            print(f"   - Run the script again to continue from where you left off")
        
        print(f"\n💡 Progress is saved in archive.txt - no progress lost!")
    
    print(f"{'='*60}\n")


def confirm_backup(auto_confirm=False):
    """Ask user confirmation for backing up a video."""
    if auto_confirm:
        return True
    
    response = input(f"\n✓ Proceed with backing up this video? (y/n/q to quit): ").lower()
    
    if response == 'q':
        print("\n👋 Operation interrupted by user.")
        sys.exit(0)
    
    return response == 'y'


def ask_retry_operation(operation_type="operation", auto_confirm=False):
    """Ask user if they want to retry a failed operation (download or upload)"""
    if auto_confirm:
        return False  # In auto mode, don't retry infinitely
    
    print(f"\n{'─'*60}")
    print(f"{operation_type.capitalize()} failed!")
    print(f"{'─'*60}")
    print("\nOptions:")
    print(f"  r - Retry {operation_type}")
    print("  s - Skip this video and continue with next")
    print("  q - Quit script")
    
    while True:
        response = input("\nWhat would you like to do? (r/s/q): ").lower().strip()
        
        if response == 'r':
            return True
        elif response == 's':
            return False
        elif response == 'q':
            print("\n👋 Operation interrupted by user.")
            sys.exit(0)
        else:
            print("Invalid option. Please enter 'r', 's', or 'q'")


def verify_backup_channel(youtube, config):
    """
    Abort the run unless the authenticated channel is the configured backup channel.

    Uploads go to the OAuth account's channel, so a mismatch would publish to the wrong channel.
    """
    authenticated_id = youtube.get_authenticated_channel_id()
    if not authenticated_id:
        print("\nERROR: The authenticated account has no YouTube channel.")
        sys.exit(1)
    if authenticated_id != config.backup_channel_id:
        print("\nERROR: The authenticated channel does not match backup_channel_id in config.json.")
        print(f"  • Authenticated channel: {authenticated_id}")
        print(f"  • Configured backup channel: {config.backup_channel_id}")
        print("  Fix backup_channel_id or re-authenticate with the correct account.")
        sys.exit(1)
    print(f"Backup channel verified ({authenticated_id})")


def main():
    """Main execution function"""
    args = _parse_args()

    print("╔═══════════════════════════════════════╗")
    print("║    YouTube Automatic Backup Script    ║")
    print("╚═══════════════════════════════════════╝\n")

    # The wizard creates config.json, so it must run before validation
    if not first_run_setup():
        sys.exit(1)

    validate_configuration()

    # Load configuration
    config = Config.load()

    # CLI flags override config.py values
    if args.auto_confirm:
        config.auto_confirm = True

    # Initialize components (StorageManager first!)
    storage = StorageManager(config)
    logger = Logger(config)
    youtube = YouTubeClient(config, storage)  # Pass storage to YouTubeClient
    downloader = VideoDownloader(config, logger)

    # Authenticate
    print("Authenticating...")
    youtube.authenticate()
    print("Authentication completed")
    verify_backup_channel(youtube, config)

    # Show quota status
    youtube.show_quota_status()

    # Load state and archive
    state = storage.load_state()
    archive = storage.load_archive()
    print(f"Archive loaded ({len(archive)} videos already backed up)")

    # Determine backup mode
    use_full_backup = config.should_do_full_backup(state)

    selection = _select_source_videos(args, config, storage, youtube, archive, use_full_backup)
    if selection is None:
        return
    source_videos, use_full_backup = selection

    print(f"\n{'='*60}")
    print(f"Found {len(source_videos)} total videos")
    print(f"{'='*60}\n")

    # Filter videos to backup
    videos_to_backup = []
    for video in source_videos:
        if video['id'] not in archive:
            videos_to_backup.append(video)
    
    # Calculate already backed up count
    already_backed_up_count = len(source_videos) - len(videos_to_backup)
    
    # Show already backed up videos if any
    if already_backed_up_count > 0:
        print(f"{'='*60}")
        print(f"✅ Videos already backed up: {already_backed_up_count}/{len(source_videos)}")
        print(f"{'='*60}\n")
        
        # Get and sort already backed up videos
        backed_up_videos = [v for v in source_videos if v['id'] in archive]
        backed_up_videos.sort(key=lambda x: x['published'])
        
        for idx, video in enumerate(backed_up_videos, 1):
            print(f"{idx}/{len(source_videos)}. ✓ {video['title']}")
            print(f"   URL: {video['url']}")
            print(f"   Published: {video['published']}\n")
    
    if not videos_to_backup:
        print("\n✓ All videos have already been backed up!")
        print("   No action needed.")
        
        # Mark full backup as completed if in full backup mode
        if use_full_backup and not config.dry_run:
            state = storage.update_state(
                full_backup_completed=True,
                last_backup_date=datetime.now().isoformat(),
            )
            print("\n✓ Full backup marked as completed!")
            print("   Future runs will use RSS for incremental updates.")
        
        return
    
    print(f"{'='*60}")
    print(f"📹 Videos to backup: {len(videos_to_backup)}/{len(source_videos)}")
    print(f"{'='*60}\n")
    
    # Always sort by publish date - oldest first (chronological order)
    videos_to_backup.sort(key=lambda x: x['published'])
    print("Backing up in chronological order (oldest first)...\n")
    
    # Display videos to backup with progressive numbering
    start_num = already_backed_up_count + 1
    for idx, video in enumerate(videos_to_backup, start_num):
        print(f"{idx}/{len(source_videos)}. {video['title']}")
        print(f"   URL: {video['url']}")
        print(f"   Published: {video['published']}\n")
    
    # Process each video
    videos_backed_up = 0
    interruption_reason = None
    last_upload_time = None  # Track when last upload finished

    for idx, video in enumerate(videos_to_backup, start_num):
        print(f"\n{'─'*60}")
        print(f"📹 Video {idx}/{len(source_videos)}: {video['title']}")
        print(f"{'─'*60}")

        # Show current quota status before asking
        current_used = youtube.get_quota_today()
        remaining = QUOTA_DAILY_LIMIT - current_used
        remaining_after = remaining - ESTIMATED_COST_PER_VIDEO

        print(f"\n💰 Quota status:")
        print(f"   • Currently used today: {current_used:,} / {QUOTA_DAILY_LIMIT:,} units")
        print(f"   • Remaining: {remaining:,} units")
        print(f"   • This video will cost: ~{ESTIMATED_COST_PER_VIDEO} units (upload + thumbnail)")
        print(f"   • After upload: ~{remaining_after:,} units remaining")

        if remaining < ESTIMATED_COST_PER_VIDEO:
            print(f"\n   WARNING: Not enough quota for this video!")
            print(f"   Quota resets at midnight Pacific Time")

        # Ask for confirmation
        if not confirm_backup(config.auto_confirm):
            print("⏭️ Video skipped.")
            continue

        # Download phase
        video_data = _run_download(downloader, video, config, logger, last_upload_time)
        if video_data is None:
            continue

        # Upload phase
        try:
            uploaded_video_id = _run_upload(youtube, video_data, config, logger)
        except Exception as e:
            fatal_reason = fatal_upload_reason(e)
            if fatal_reason:
                interruption_reason = fatal_reason
                break
            logger.log_error(f"Unexpected error during upload: {e}")
            break

        if uploaded_video_id is None:
            continue

        last_upload_time = time.time()
        new_state = _record_success(storage, logger, config, video, video_data, uploaded_video_id)
        if new_state is not None:
            state = new_state
        videos_backed_up += 1

    # Mark full backup as completed if we processed all videos
    if use_full_backup and not config.dry_run and videos_backed_up == len(videos_to_backup):
        state = storage.update_state(full_backup_completed=True)
        print(f"\n{'='*60}")
        print("🎉 FULL BACKUP COMPLETED!")
        print(f"{'='*60}")
        print(f"✓ All {videos_backed_up} videos have been backed up")
        print(f"✓ Future runs will use RSS for incremental updates (no quota)")
        print(f"✓ To force another full backup, delete: state.json")
    
    # Print unified summary
    print_backup_summary(
        videos_backed_up=videos_backed_up,
        total_videos=len(videos_to_backup),
        state=state,
        quota_used=youtube.get_quota_usage(),
        quota_today=youtube.get_quota_today(),
        use_full_backup=use_full_backup,
        source_videos_count=len(source_videos),
        interruption_reason=interruption_reason
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Operation interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)