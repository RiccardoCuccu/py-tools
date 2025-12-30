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
from video_handler import VideoDownloader, VideoUploader, QUOTA_VIDEO_UPLOAD, QUOTA_THUMBNAIL_UPLOAD
from utils import StorageManager, Logger

# Video processing constants
VIDEOS_PER_API_PAGE = 50
ESTIMATED_COST_PER_VIDEO = QUOTA_VIDEO_UPLOAD + QUOTA_THUMBNAIL_UPLOAD  # Upload + thumbnail

def confirm_backup(video, auto_confirm=False):
    """Ask user confirmation for backing up a video"""
    if auto_confirm:
        return True
    
    response = input(f"\n✓ Proceed with backing up this video? (y/n/q to quit): ").lower()
    
    if response == 'q':
        print("\n👋 Operation interrupted by user.")
        sys.exit(0)
    
    return response == 'y'

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
    
    # Initialize components
    storage = StorageManager(config)
    logger = Logger(config)
    youtube = YouTubeClient(config, storage)  # Pass storage to YouTubeClient
    downloader = VideoDownloader(config)
    uploader = VideoUploader(config, youtube)  # Pass youtube_client for quota tracking
    
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
    
    # Check if we have videos in queue from previous runs
    queue_videos = storage.get_queue_videos()
    
    # Initialize source_videos
    source_videos = []
    
    if queue_videos:
        print(f"\n{'='*60}")
        print(f"📋 RESUMING FROM QUEUE")
        print(f"{'='*60}")
        print(f"Found {len(queue_videos)} videos in queue from previous run")
        print(f"These videos were discovered but not yet backed up.")
        print(f"\nOptions:")
        print(f"  1. Continue with queue (recommended - saves quota)")
        print(f"  2. Re-fetch videos from channel (costs API quota)")
        
        if not config.auto_confirm:
            response = input("\nUse queue? (1/2): ").strip()
            use_queue = response == '1'
        else:
            use_queue = True
            print("\n✓ Auto-using queue (AUTO_CONFIRM enabled)")
        
        if use_queue:
            print(f"\n✓ Using {len(queue_videos)} videos from queue")
            source_videos = queue_videos
            use_full_backup = False  # Don't do full backup if using queue
        else:
            print(f"\n⚠️  Clearing queue and re-fetching...")
            storage.clear_queue()
            queue_videos = []
    
    # Only fetch new videos if we don't have any from queue
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
        else:
            print(f"\n{'='*60}")
            print(f"📹 INCREMENTAL MODE - Checking recent videos via RSS")
            print(f"{'='*60}")
            print(f"Checking for new videos (last ~15 from RSS feed)")
            print(f"No API quota will be used for video discovery\n")
            
            # Get recent videos via RSS
            source_videos = youtube.get_channel_videos_rss(config.source_channel_id)
    
    print(f"\n{'='*60}")
    print(f"📹 Found {len(source_videos)} total videos")
    print(f"{'='*60}\n")
    
    # Filter videos to backup
    videos_to_backup = []
    for video in source_videos:
        if video['id'] not in archive:
            videos_to_backup.append(video)
    
    if not videos_to_backup:
        print("\n✓ All videos have already been backed up!")
        print("   No action needed.")
        
        # Clear queue if it was used
        if queue_videos:
            storage.clear_queue()
            print("   Queue cleared.")
        
        # Mark full backup as completed if in full backup mode
        if use_full_backup:
            state["full_backup_completed"] = True
            state["last_backup_date"] = datetime.now().isoformat()
            storage.save_state(state)
            print("\n✓ Full backup marked as completed!")
            print("   Future runs will use RSS for incremental updates.")
        
        return
    
    print(f"\n{'='*60}")
    print(f"📹 Found {len(videos_to_backup)} videos to backup")
    print(f"{'='*60}\n")
    
    # Add videos to persistent queue (if not already from queue)
    if not queue_videos:
        added = storage.add_to_queue(videos_to_backup, config.source_channel_id)
        print(f"✓ Added {added} new videos to persistent queue")
        print(f"  Queue will be used if backup is interrupted\n")
    
    # Always sort by publish date - oldest first (chronological order)
    videos_to_backup.sort(key=lambda x: x['published'])
    print("Backing up in chronological order (oldest first)...\n")
    
    # Display videos to backup
    for idx, video in enumerate(videos_to_backup, 1):
        print(f"{idx}/{len(videos_to_backup)}. {video['title']}")
        print(f"   URL: {video['url']}")
        print(f"   Published: {video['published']}\n")
    
    # Process each video
    videos_backed_up = 0
    
    for idx, video in enumerate(videos_to_backup, 1):
        print(f"\n{'─'*60}")
        print(f"📹 Video {idx}/{len(videos_to_backup)}: {video['title']}")
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
            print("⏭️  Video skipped.")
            continue
        
        try:
            # Add delay between downloads
            if videos_backed_up > 0 and config.download_delay > 0:
                print(f"\n⏳ Waiting {config.download_delay} seconds before next download...")
                time.sleep(config.download_delay)
            
            # Download video
            video_data = downloader.download(video['url'], DOWNLOAD_DIR)
            
            if not video_data['success'] or not video_data['video_file']:
                logger.log_warning("Error: video file not found after download")
                continue
            
            # Upload video
            uploaded_video_id = uploader.upload(youtube.service, video_data)
            
            # Save to archive
            storage.save_to_archive(video['id'])
            
            # Remove from queue
            storage.remove_from_queue(video['id'])
            
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
                downloader.cleanup(video_data)
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
                print(f"\n{'='*60}")
                print(f"⚠️  UPLOAD LIMIT EXCEEDED")
                print(f"{'='*60}")
                print(f"YouTube has daily upload limits:")
                print(f"  • Non-verified accounts: ~10-15 videos/day")
                print(f"  • Verified accounts: ~50-100 videos/day")
                print(f"\nSolutions:")
                print(f"  1. Verify your account: https://www.youtube.com/verify")
                print(f"  2. Wait 24 hours for limit reset")
                print(f"  3. Request quota increase via YouTube support")
                print(f"\nVideos backed up so far: {videos_backed_up}")
                print(f"Remaining videos: {len(videos_to_backup) - idx}")
                print(f"{'='*60}\n")
                break
            
            if not config.auto_confirm:
                response = input("Continue with the next video? (y/n): ").lower()
                if response != 'y':
                    break
            else:
                print("Auto-continuing to next video...")
    
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
    
    # Summary
    print(f"\n{'='*60}")
    print(f"🎉 Backup operation completed!")
    print(f"   Videos backed up this run: {videos_backed_up}")
    print(f"   Total videos backed up: {state.get('total_videos_backed_up', 0)}")
    print(f"   API quota used this run: {youtube.get_quota_usage()} units")
    
    # Quota breakdown
    if youtube.get_quota_usage() > 0:
        print(f"\n   Quota breakdown:")
        if use_full_backup:
            pages = (len(source_videos) // VIDEOS_PER_API_PAGE) + 1
            print(f"   • Channel video list: ~{pages} units (API, {pages} pages)")
        else:
            print(f"   • RSS feed checks: 0 units (free)")
        
        if videos_backed_up > 0:
            print(f"   • Video uploads: {videos_backed_up * QUOTA_VIDEO_UPLOAD} units ({QUOTA_VIDEO_UPLOAD} per video)")
            print(f"   • Thumbnail uploads: {videos_backed_up * QUOTA_THUMBNAIL_UPLOAD} units ({QUOTA_THUMBNAIL_UPLOAD} per thumbnail)")
    
    # Daily quota limit info
    total_used_today = youtube.get_quota_today()
    remaining_quota = QUOTA_DAILY_LIMIT - total_used_today
    
    print(f"\n   📊 Daily quota summary:")
    print(f"   • Total used today: {total_used_today:,} units")
    print(f"   • Remaining: {remaining_quota:,} / {QUOTA_DAILY_LIMIT:,} units")
    print(f"   • Reset: Midnight Pacific Time (PT/PDT)")
    
    if total_used_today > 8000:
        print(f"\n   ⚠️  WARNING: High quota usage!")
        print(f"   YouTube API daily limit is {QUOTA_DAILY_LIMIT:,} units")
    
    if use_full_backup and videos_backed_up < len(videos_to_backup):
        print(f"\n   ⚠️  Full backup incomplete - run again to continue")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Operation interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)