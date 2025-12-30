#!/usr/bin/env python3
"""
Utilities Module
Handles storage management (archive, state, config) and logging
"""

import os
import json
from datetime import datetime
from pathlib import Path
from config import ARCHIVE_FILE, STATE_FILE, LOG_FILE, DOWNLOAD_DIR, CONFIG_DIR, QUEUE_FILE

class StorageManager:
    """Manages persistent data storage"""
    
    def __init__(self, config):
        self.config = config
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        Path(CONFIG_DIR).mkdir(exist_ok=True)
        Path(DOWNLOAD_DIR).mkdir(exist_ok=True)
    
    def load_archive(self):
        """Load archive of already processed videos"""
        if os.path.exists(ARCHIVE_FILE):
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f if line.strip())
        return set()
    
    def save_to_archive(self, video_id):
        """Save video ID to archive"""
        with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{video_id}\n")
    
    def load_state(self):
        """Load backup state"""
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "full_backup_completed": False,
            "last_backup_date": None,
            "total_videos_backed_up": 0,
            "quota_used_today": 0,
            "quota_reset_date": datetime.now().isoformat()
        }
    
    def save_state(self, state):
        """Save backup state"""
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    
    def load_queue(self):
        """Load persistent video queue"""
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "videos": [],
            "last_updated": None,
            "source_channel_id": None
        }
    
    def save_queue(self, queue_data):
        """Save persistent video queue"""
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue_data, f, indent=2)
    
    def add_to_queue(self, videos, source_channel_id):
        """Add videos to persistent queue (avoiding duplicates)"""
        queue = self.load_queue()
        
        existing_ids = {v['id'] for v in queue['videos']}
        new_videos = [v for v in videos if v['id'] not in existing_ids]
        
        queue['videos'].extend(new_videos)
        queue['last_updated'] = datetime.now().isoformat()
        queue['source_channel_id'] = source_channel_id
        
        self.save_queue(queue)
        return len(new_videos)
    
    def remove_from_queue(self, video_id):
        """Remove video from queue after successful backup"""
        queue = self.load_queue()
        queue['videos'] = [v for v in queue['videos'] if v['id'] != video_id]
        self.save_queue(queue)
    
    def get_queue_videos(self):
        """Get videos from queue"""
        queue = self.load_queue()
        return queue['videos']
    
    def clear_queue(self):
        """Clear the entire queue"""
        self.save_queue({
            "videos": [],
            "last_updated": None,
            "source_channel_id": None
        })


class Logger:
    """Handles logging and console output"""
    
    def __init__(self, config):
        self.config = config
    
    def log_backed_up_video(self, video_id, video_title, channel_title, backup_video_id):
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
    
    def log_info(self, message):
        """Log informational message"""
        print(message)
    
    def log_error(self, message):
        """Log error message"""
        print(f"❌ {message}")
    
    def log_warning(self, message):
        """Log warning message"""
        print(f"⚠️  {message}")