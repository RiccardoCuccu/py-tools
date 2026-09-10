#!/usr/bin/env python3
"""
Utilities Module
Handles storage management (archive, state, config) and logging
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import ARCHIVE_FILE, STATE_FILE, LOG_FILE, DOWNLOAD_DIR, CONFIG_DIR, CHANNEL_VIDEOS_FILE, Config


class StorageManager:
    """Manages persistent data storage"""
    
    def __init__(self, config: Config) -> None:
        """Initialise storage paths and create required directories."""
        self.config = config
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Create necessary directories if they don't exist"""
        Path(CONFIG_DIR).mkdir(exist_ok=True)
        Path(DOWNLOAD_DIR).mkdir(exist_ok=True)
    
    def load_archive(self) -> set[str]:
        """Load archive of already processed videos"""
        if Path(ARCHIVE_FILE).exists():
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f if line.strip())
        return set()
    
    def save_to_archive(self, video_id: str) -> None:
        """Save video ID to archive"""
        with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{video_id}\n")
    
    def load_state(self) -> dict[str, Any]:
        """Load backup state"""
        if Path(STATE_FILE).exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "full_backup_completed": False,
            "last_backup_date": None,
            "total_videos_backed_up": 0,
            "quota_used_today": 0,
            "quota_reset_date": datetime.now().isoformat()
        }
    
    def save_state(self, state: dict[str, Any]) -> None:
        """Save backup state"""
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    
    def load_channel_videos(self) -> dict[str, Any]:
        """Load complete channel videos cache"""
        if Path(CHANNEL_VIDEOS_FILE).exists():
            with open(CHANNEL_VIDEOS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "all_videos": [],
            "last_updated": None,
            "source_channel_id": None,
            "total_count": 0
        }
    
    def save_channel_videos(self, cache_data: dict[str, Any]) -> None:
        """Save complete channel videos cache"""
        with open(CHANNEL_VIDEOS_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    
    def update_channel_videos_cache(self, videos: list[dict[str, Any]], source_channel_id: str) -> dict[str, Any]:
        """Update the complete channel videos cache with ALL videos"""
        cache = {
            "all_videos": videos,
            "last_updated": datetime.now().isoformat(),
            "source_channel_id": source_channel_id,
            "total_count": len(videos)
        }
        self.save_channel_videos(cache)
        return cache
    
    def get_cached_videos(self) -> list[dict[str, Any]]:
        """Get all videos from cache"""
        cache = self.load_channel_videos()
        return cache.get('all_videos', [])
    
    def clear_channel_videos_cache(self) -> None:
        """Clear the entire channel videos cache"""
        self.save_channel_videos({
            "all_videos": [],
            "last_updated": None,
            "source_channel_id": None,
            "total_count": 0
        })


class Logger:
    """Handles logging and console output"""
    
    def __init__(self, config: Config) -> None:
        """Initialise logger with the active configuration."""
        self.config = config

    def log_backed_up_video(self, video_id: str, video_title: str, channel_title: str, backup_video_id: str) -> None:
        """Log backed up video to file and print compact format"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        backup_url = f"https://www.youtube.com/watch?v={backup_video_id}"
        log_entry = f"[{timestamp}] {channel_title} - {video_title}\n  Source: {source_url}\n  Backup: {backup_url}\n\n"
        
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        
        print(f"  ✓ {video_title}")
        print(f"    Source: {source_url}")
        print(f"    Backup: {backup_url}")
    
    def log_info(self, message: str) -> None:
        """Log informational message"""
        print(message)
    
    def log_error(self, message: str) -> None:
        """Log error message to console and file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] ERROR: {message}\n")
        print(f"❌ {message}")

    def log_warning(self, message: str) -> None:
        """Log warning message to console and file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] WARNING: {message}\n")
        print(f"⚠️  {message}")


def safe_remove_files(*filepaths: str) -> None:
    """Remove files safely, ignoring errors"""
    for filepath in filepaths:
        if filepath and Path(filepath).exists():
            try:
                Path(filepath).unlink()
            except Exception as e:
                print(f"⚠️ Error removing {filepath}: {e}")