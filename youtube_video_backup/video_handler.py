#!/usr/bin/env python3
"""
Video Handler Module
Handles video download (yt-dlp) and upload to YouTube
"""

import os
import json
import subprocess
import yt_dlp
from googleapiclient.http import MediaFileUpload

# YouTube API Quota Costs (as per YouTube Data API v3 documentation)
QUOTA_VIDEO_UPLOAD = 1600
QUOTA_THUMBNAIL_UPLOAD = 50

# Quality constraints
MIN_NATIVE_HEIGHT = 1080  # Minimum resolution for "native quality"

class VideoDownloader:
    """Manages video downloads with yt-dlp"""
    
    # File extensions to search for
    VIDEO_EXTENSIONS = ['mp4', 'webm', 'mkv', 'mov']
    THUMBNAIL_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
    
    def __init__(self, config):
        self.config = config
    
    @staticmethod
    def _find_file_with_extensions(base_path, extensions):
        """Find first existing file matching base_path with given extensions"""
        for ext in extensions:
            path = f"{base_path}.{ext}"
            if os.path.exists(path):
                return path
        return None
    
    @staticmethod
    def _get_video_resolution(video_path):
        """Get video resolution using ffprobe"""
        if not video_path or not os.path.exists(video_path):
            return None
        
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                 video_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                if len(parts) == 2:
                    width, height = parts[0].strip(), parts[1].strip()
                    if width and height:
                        return f"{width}x{height}"
        except:
            pass
        
        return None
    
    @staticmethod
    def _get_image_resolution(image_path):
        """Get image resolution using PIL"""
        if not image_path or not os.path.exists(image_path):
            return None
        
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                return f"{img.width}x{img.height}"
        except:
            pass
        
        return None
    
    @staticmethod
    def _format_file_info(filepath, resolution):
        """Format file display with optional resolution"""
        filename = os.path.basename(filepath)
        return f"{filename} [{resolution}]" if resolution else filename
    
    @staticmethod
    def _create_result(video_file=None, thumbnail_file=None, info=None):
        """Factory method for download results"""
        return {
            'video_file': video_file,
            'thumbnail_file': thumbnail_file,
            'info': info or {},
            'success': video_file is not None
        }
    
    def _load_info_json(self, video_id, output_dir):
        """Load video info from .info.json file"""
        info_file = f"{output_dir}/{video_id}.info.json"
        if os.path.exists(info_file):
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _log_download_error(self, reason):
        """Log download error with consistent formatting"""
        print(f"\n   ❌ Download failed: {reason}")
    
    def download(self, video_url, output_dir):
        """Download video with yt-dlp"""
        print(f"\n⬇️ Downloading video...")
        
        # Extract video ID from URL
        video_id = video_url.split('watch?v=')[-1].split('&')[0]
        base_path = f"{output_dir}/{video_id}"
        
        # Check if video already exists locally
        video_file = self._find_file_with_extensions(base_path, self.VIDEO_EXTENSIONS)
        
        if video_file:
            # File exists - load metadata and display
            thumbnail_file = self._find_file_with_extensions(base_path, self.THUMBNAIL_EXTENSIONS)
            info = self._load_info_json(video_id, output_dir)
            
            print(f"\n   📂 Found existing download:")
            
            # Display video with resolution
            video_resolution = self._get_video_resolution(video_file)
            print(f"      Video: {self._format_file_info(video_file, video_resolution)}")
            
            # Display thumbnail with resolution
            if thumbnail_file:
                thumb_resolution = self._get_image_resolution(thumbnail_file)
                print(f"      Thumbnail: {self._format_file_info(thumbnail_file, thumb_resolution)}")
            
            # Ask user if they want to use existing
            if self.config.auto_confirm:
                print(f"   ✓ Auto-using existing download (AUTO_CONFIRM enabled)")
                return self._create_result(video_file, thumbnail_file, info)
            
            response = input("\n   Use existing download? (y/n): ").lower()
            if response == 'y':
                print(f"   ✓ Using existing download")
                return self._create_result(video_file, thumbnail_file, info)
            else:
                print(f"   Re-downloading...")
        
        # Download with yt-dlp
        print(f"   Method: yt-dlp")
        
        # Format 96 is 1080p m3u8/HLS - most reliable and works consistently
        if self.config.require_native_quality:
            format_string = f"96/bestvideo[height>={MIN_NATIVE_HEIGHT}]+bestaudio/best[height>={MIN_NATIVE_HEIGHT}]"
            print(f"   Note: Requiring {MIN_NATIVE_HEIGHT}p+ quality")
        else:
            format_string = "96/bestvideo+bestaudio/best"
            print(f"   Note: Accepting best available quality")
        
        ydl_opts = {
            'format': format_string,
            'merge_output_format': 'mp4',
            'writeinfojson': True,
            'writethumbnail': True,
            'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
            'quiet': False,
            'no_warnings': True,
            'ignoreerrors': False,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web_safari'],
                    'player_skip': ['configs'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(video_url, download=True)  # type: ignore
                
                if not info:
                    self._log_download_error("No response from yt-dlp")
                    return self._create_result()
                    
                video_id = info['id']  # type: ignore
                base_path = f"{output_dir}/{video_id}"
                
                # Find downloaded video file
                video_file = self._find_file_with_extensions(base_path, self.VIDEO_EXTENSIONS)
                
                if not video_file:
                    self._log_download_error("Video file not found after download")
                    return self._create_result()
                
                # Find thumbnail file
                thumbnail_file = self._find_file_with_extensions(base_path, self.THUMBNAIL_EXTENSIONS)
                
                print(f"   ✓ Download successful")
                return self._create_result(video_file, thumbnail_file, info)
        
        except Exception as e:
            self._log_download_error(str(e))
            return self._create_result()


def upload_video(youtube_service, video_data, config, youtube_client):
    """Upload video to YouTube with original metadata"""
    if config.dry_run:
        print(f"\n⬆️ [DRY RUN] Would upload video to backup channel...")
        print(f"   Title: {video_data['info'].get('title', 'Untitled')}")
        print(f"✓ [DRY RUN] Upload simulated successfully!")
        return "DRY_RUN_VIDEO_ID"
    
    print(f"\n⬆️ Uploading video to backup channel...")
    
    info = video_data['info']
    video_file = video_data['video_file']
    thumbnail_file = video_data['thumbnail_file']
    
    # Prepare metadata
    title = info.get('title', 'Untitled')
    description = info.get('description', '')
    tags = info.get('tags', [])
    category_id = str(info.get('category_id') or info.get('categoryId', '22'))
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags if tags else [],
            'categoryId': category_id
        },
        'status': {
            'privacyStatus': 'private',
            'selfDeclaredMadeForKids': False
        }
    }
    
    # Upload video
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)  # type: ignore[arg-type]
    
    request = youtube_service.videos().insert(  # type: ignore
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    # Track quota cost and save to disk immediately before upload
    if youtube_client:
        youtube_client.add_quota_cost(QUOTA_VIDEO_UPLOAD)
        youtube_client.save_quota_state()
    
    response = None
    print("   Uploading...", end='', flush=True)
    
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"\r   Uploading... {progress}%", end='', flush=True)
    
    print(f"\r✓ Video uploaded successfully! ID: {response['id']}")
    
    # Upload thumbnail if available
    if thumbnail_file and os.path.exists(thumbnail_file):
        try:
            print("   Uploading thumbnail...", end='', flush=True)
            
            # Track quota cost and save to disk immediately before thumbnail upload
            if youtube_client:
                youtube_client.add_quota_cost(QUOTA_THUMBNAIL_UPLOAD)
                youtube_client.save_quota_state()
            
            youtube_service.thumbnails().set(  # type: ignore
                videoId=response['id'],
                media_body=MediaFileUpload(thumbnail_file)  # type: ignore[arg-type]
            ).execute()
            
            print("\r✓ Thumbnail uploaded successfully!")
        except Exception as e:
            print(f"\r⚠️ Error uploading thumbnail: {e}")
    
    return response['id']