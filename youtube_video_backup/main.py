#!/usr/bin/env python3
"""
YouTube Video Backup Script - Main Entry Point
Downloads videos from a YouTube channel and re-uploads them to a secondary channel as private
"""

import os
import sys
import time
from datetime import datetime
from config import Config, first_run_setup, DOWNLOAD_DIR
from youtube_client import YouTubeClient, QUOTA_DAILY_LIMIT  # type: ignore
from video_handler import VideoDownloader, upload_video, QUOTA_VIDEO_UPLOAD, QUOTA_THUMBNAIL_UPLOAD
from utils import StorageManager, Logger, safe_remove_files

# Video processing constants
VIDEOS_PER_API_PAGE = 50
ESTIMATED_COST_PER_VIDEO = QUOTA_VIDEO_UPLOAD + QUOTA_THUMBNAIL_UPLOAD  # Upload + thumbnail


def print_backup_summary(videos_backed_up, total_videos, state, quota_used, quota_today, 
                         use_full_backup=False, source_videos_count=0, interruption_reason=None):
    """Print unified backup summary - handles both success and interruption cases"""
    remaining = total_videos - videos_backed_up
    quota_remaining = QUOTA_DAILY_LIMIT - quota_today
    
    # Header - same for all interruptions
    print(f"\n{'='*60}")
    if interruption_reason:
        print(f"⚠️  BACKUP INTERRUPTED")
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
            print(f"\n   ⚠️  WARNING: High quota usage!")
    
    # Interruption-specific information
    if interruption_reason:
        print(f"\n⚠️  Reason: {interruption_reason}")
        
        if "upload limit" in interruption_reason.lower():
            print(f"\n📋 Why this happened:")
            print(f"   YouTube limits daily uploads to ~10-15 videos for")
            print(f"   non-verified accounts (~50-100 for verified accounts).")
            print(f"\n💡 What to do next:")
            print(f"   1. Wait 24 hours for limit reset")
            print(f"   2. Verify your account: https://www.youtube.com/verify")
            print(f"   3. Run this script again - it will resume automatically")
        else:
            print(f"   → Run the script again to continue from where you left off")
        
        print(f"\n💡 All videos are saved in queue.json - no progress lost!")
    
    print(f"{'='*60}\n")


def confirm_backup(video, auto_confirm=False):
    """Ask user confirmation for backing up a video"""
    if auto_confirm:
        return True
    
    response = input(f"\n✓ Proceed with backing up this video? (y/n/q to quit): ").lower()
    
    if response == 'q':
        print("\n👋 Operation interrupted by user.")
        sys.exit(0)
    
    return response == 'y'


def ask_retry_download(auto_confirm=False):
    """Ask user if they want to retry a failed download"""
    if auto_confirm:
        return False  # In auto mode, don't retry infinitely
    
    print(f"\n{'─'*60}")
    print("⚠️  Download failed!")
    print(f"{'─'*60}")
    print("\nOptions:")
    print("  r - Retry downloading this video")
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


def main():
    """Main execution function"""
    
    print("╔═══════════════════════════════════════╗")
    print("║    YouTube Automatic Backup Script    ║")
    print("╚═══════════════════════════════════════╝\n")
    
    # First run setup
    if not first_run_setup():
        sys.exit(1)
    
    # Load configuration
    config = Config.load()
    
    # Initialize components (StorageManager first!)
    storage = StorageManager(config)
    logger = Logger(config)
    youtube = YouTubeClient(config, storage)  # Pass storage to YouTubeClient
    downloader = VideoDownloader(config)
    # Note: upload_video is now a function, not a class
    
    # Authenticate
    print("🔐 Authenticating...")
    youtube.authenticate()
    print("✓ Authentication completed")
    
    # Show quota status
    youtube.show_quota_status()
    
    # Load state and archive
    state = storage.load_state()
    archive = storage.load_archive()
    print(f"✓ Archive loaded ({len(archive)} videos already backed up)")
    
    # Determine backup mode
    use_full_backup = config.should_do_full_backup(state)
    
    # Check if we have videos in cache from previous runs
    cached_videos = storage.get_cached_videos()
    
    # Initialize source_videos
    source_videos = []
    
    if cached_videos:
        cache_info = storage.load_channel_videos()
        print(f"\n{'='*60}")
        print(f"📋 CACHED CHANNEL DATA FOUND")
        print(f"{'='*60}")
        print(f"Found {len(cached_videos)} videos in cache from previous run")
        print(f"Last updated: {cache_info.get('last_updated', 'Unknown')}")
        print(f"\nOptions:")
        print(f"  1. Use cached data (recommended - no API cost)")
        print(f"  2. Re-fetch videos from channel (costs API quota if using full backup)")
        
        if not config.auto_confirm:
            response = input("\nUse cache? (1/2): ").strip()
            use_cache = response == '1'
        else:
            use_cache = True
            print("\n✓ Auto-using cache (AUTO_CONFIRM enabled)")
        
        if use_cache:
            print(f"\n✓ Using {len(cached_videos)} videos from cache")
            source_videos = cached_videos
            use_full_backup = False  # Don't do full backup if using cache
        else:
            print(f"\n⚠️  Clearing cache and re-fetching...")
            storage.clear_channel_videos_cache()
            cached_videos = []
    
    # Only fetch new videos if we don't have any from cache
    if not source_videos:
        # Estimate quota cost
        if use_full_backup:
            estimated_cost = 1 + (len(archive) // VIDEOS_PER_API_PAGE + 1)  # Channel list + backup check
            print(f"\n💰 Estimated quota cost for this run:")
            print(f"   • Full backup mode: ~{estimated_cost} units (video discovery)")
            print(f"   • Plus: {QUOTA_VIDEO_UPLOAD} units per video uploaded")
            print(f"   • Plus: {QUOTA_THUMBNAIL_UPLOAD} units per thumbnail uploaded")
            
            remaining = QUOTA_DAILY_LIMIT - youtube.get_quota_today()
            
            if estimated_cost > remaining:
                print(f"\n   ⚠️  WARNING: Not enough quota remaining!")
                print(f"   Need ~{estimated_cost} units, have {remaining} units")
                print(f"   Quota resets at midnight Pacific Time")
                
                response = input("\n   Continue anyway? (y/n): ").lower()
                if response != 'y':
                    print("Operation cancelled by user")
                    return
        
        if use_full_backup:
            print(f"\n{'='*60}")
            print(f"📹 FULL BACKUP MODE - First time complete backup")
            print(f"{'='*60}")
            print(f"This will retrieve ALL videos from the source channel via API")
            print(f"Using API key (no OAuth needed for public source channel)")
            print(f"Estimated quota cost: ~1 unit per {VIDEOS_PER_API_PAGE} videos")
            print(f"After completion, future runs will use RSS (free)\n")
            
            if not config.auto_confirm:
                response = input("Proceed with full backup? (y/n): ").lower()
                if response != 'y':
                    print("Full backup cancelled. Set INITIAL_FULL_BACKUP = False to use RSS mode.")
                    return
            
            # Get ALL videos via API
            source_videos = youtube.get_all_channel_videos_api(config.source_channel_id)
            
            # Cache the complete list
            storage.update_channel_videos_cache(source_videos, config.source_channel_id)
        else:
            print(f"\n{'='*60}")
            print(f"📹 INCREMENTAL MODE - Checking recent videos via RSS")
            print(f"{'='*60}")
            print(f"Checking for new videos (last ~15 from RSS feed)")
            print(f"No API quota will be used for video discovery\n")
            
            # Get recent videos via RSS
            source_videos = youtube.get_channel_videos_rss(config.source_channel_id)
            
            # Cache the list
            storage.update_channel_videos_cache(source_videos, config.source_channel_id)
    
    print(f"\n{'='*60}")
    print(f"📹 Found {len(source_videos)} total videos")
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
        if use_full_backup:
            state["full_backup_completed"] = True
            state["last_backup_date"] = datetime.now().isoformat()
            storage.save_state(state)
            print("\n✓ Full backup marked as completed!")
            print("   Future runs will use RSS for incremental updates.")
        
        return
    
    print(f"{'='*60}")
    print(f"📹 Videos to backup: {len(videos_to_backup)}/{len(source_videos)}")
    print(f"{'='*60}\n")
    
    # Note: We don't need to add to queue anymore, cache already has everything
    
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
            print(f"\n   ⚠️  WARNING: Not enough quota for this video!")
            print(f"   Quota resets at midnight Pacific Time")
        
        # Ask for confirmation
        if not confirm_backup(video, config.auto_confirm):
            print("⏭️ Video skipped.")
            continue
        
        # Retry loop for downloads
        download_success = False
        while not download_success:
            try:
                # Apply delay BEFORE download if needed
                if last_upload_time is not None and config.download_delay > 0:
                    elapsed = time.time() - last_upload_time
                    remaining_delay = config.download_delay - elapsed
                    
                    if remaining_delay > 0:
                        print(f"\n⏳ Waiting {remaining_delay:.1f} more seconds before next download...")
                        time.sleep(remaining_delay)
                    else:
                        print(f"\n✓ Delay already satisfied ({elapsed:.1f}s elapsed since last upload)")
                
                # Download video
                video_data = downloader.download(video['url'], DOWNLOAD_DIR)
                
                if not video_data['success'] or not video_data['video_file']:
                    logger.log_warning("Error: video file not found after download")
                    
                    # Ask if user wants to retry
                    if ask_retry_download(config.auto_confirm):
                        print("\n🔄 Retrying download...")
                        continue
                    else:
                        print("⏭️ Skipping this video.")
                        break
                
                # If we get here, download was successful
                download_success = True
                
                # Upload video
                uploaded_video_id = upload_video(youtube.service, video_data, config, youtube)
                
                # Record upload completion time
                last_upload_time = time.time()
                
                # Save to archive
                storage.save_to_archive(video['id'])
                
                # Log the backup
                logger.log_backed_up_video(
                    video['id'],
                    video['title'],
                    video_data['info'].get('channel', 'Unknown Channel'),
                    uploaded_video_id
                )
                
                # Cleanup temporary files (if enabled)
                if config.delete_after_upload:  # type: ignore
                    print("\n🧹 Cleaning up temporary files...")
                    safe_remove_files(
                        video_data.get('video_file'),
                        video_data.get('thumbnail_file')
                    )
                else:
                    print(f"\n💾 Files kept in: {DOWNLOAD_DIR}")
                    print(f"   Video: {os.path.basename(video_data['video_file'])}")
                    if video_data.get('thumbnail_file'):
                        print(f"   Thumbnail: {os.path.basename(video_data['thumbnail_file'])}")
                
                print(f"\n✅ Backup completed successfully!")
                videos_backed_up += 1
                
                # Update state
                state["total_videos_backed_up"] = state.get("total_videos_backed_up", 0) + 1
                state["last_backup_date"] = datetime.now().isoformat()
                storage.save_state(state)
                
            except Exception as e:
                error_str = str(e)
                logger.log_error(f"Error during backup: {e}")
                
                # Check for specific YouTube errors
                if "uploadLimitExceeded" in error_str:
                    interruption_reason = "Upload limit exceeded"
                    break
                
                if not config.auto_confirm:
                    response = input("Continue with the next video? (y/n): ").lower()
                    if response != 'y':
                        interruption_reason = "User stopped backup"
                        break
                else:
                    print("Auto-continuing to next video...")
                
                # Break the retry loop
                break
    
    # Mark full backup as completed if we processed all videos
    if use_full_backup and videos_backed_up == len(videos_to_backup):
        state["full_backup_completed"] = True
        storage.save_state(state)
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