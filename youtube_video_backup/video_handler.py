#!/usr/bin/env python3
"""
Video Handler Module
Handles video download (yt-dlp + API fallback) and upload to YouTube
"""

import os
import json
import yt_dlp
from googleapiclient.http import MediaFileUpload

# YouTube API Quota Costs (as per YouTube Data API v3 documentation)
QUOTA_VIDEO_UPLOAD = 1600
QUOTA_THUMBNAIL_UPLOAD = 50

# Quality constraints
MIN_NATIVE_HEIGHT = 1080  # Minimum resolution for "native quality"

class VideoDownloader:
    """Manages video downloads with yt-dlp and API fallback"""
    
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
            import subprocess
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
    
    def download(self, video_url, output_dir):
        """Download video with yt-dlp and API fallback"""
        print(f"\n⬇️ Downloading video...")
        
        # Extract video ID from URL
        video_id = video_url.split('watch?v=')[-1].split('&')[0]
        
        # Check if video already exists locally
        existing_files = self._check_existing_download(video_id, output_dir)
        if existing_files:
            print(f"\n   📂 Found existing download:")
            
            # Show video with resolution
            video_resolution = self._get_video_resolution(existing_files['video_file'])
            video_info = f"{os.path.basename(existing_files['video_file'])}"
            if video_resolution:
                video_info += f" [{video_resolution}]"
            print(f"      Video: {video_info}")
            
            # Show thumbnail with resolution
            if existing_files.get('thumbnail_file'):
                thumb_resolution = self._get_image_resolution(existing_files['thumbnail_file'])
                thumb_info = f"{os.path.basename(existing_files['thumbnail_file'])}"
                if thumb_resolution:
                    thumb_info += f" [{thumb_resolution}]"
                print(f"      Thumbnail: {thumb_info}")
            
            if not self.config.auto_confirm:
                response = input("\n   Use existing download? (y/n): ").lower()
                if response == 'y':
                    print(f"   ✓ Using existing download")
                    return existing_files
                else:
                    print(f"   Re-downloading...")
            else:
                print(f"   ✓ Auto-using existing download (AUTO_CONFIRM enabled)")
                return existing_files
        
        # Try yt-dlp first
        result = self._download_ytdlp(video_url, output_dir)
        
        # If yt-dlp failed and API fallback is enabled, try API
        if not result and self.config.use_api_fallback:
            print(f"\n   Trying API fallback...")
            result = self._download_api(video_id, output_dir)
        
        if not result:
            print(f"\n   ❌ All download methods failed")
            return {
                'video_file': None,
                'thumbnail_file': None,
                'info_file': None,
                'info': {},
                'success': False,
                'method': None
            }
        
        print(f"   ✓ Download successful via {result['method']}")
        return result
    
    def _check_existing_download(self, video_id, output_dir):
        """Check if video was already downloaded"""
        base_path = f"{output_dir}/{video_id}"
        
        # Check for video file
        video_file = self._find_file_with_extensions(base_path, self.VIDEO_EXTENSIONS)
        
        if not video_file:
            return None
        
        # Find thumbnail file
        thumbnail_file = self._find_file_with_extensions(base_path, self.THUMBNAIL_EXTENSIONS)
        
        # Find info file
        info_file = f"{output_dir}/{video_id}.info.json"
        info = {}
        
        if os.path.exists(info_file):
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
            except:
                pass
        
        return {
            'video_file': video_file,
            'thumbnail_file': thumbnail_file,
            'info_file': info_file if os.path.exists(info_file) else None,
            'info': info,
            'success': True,
            'method': 'existing'
        }
    
    def _download_ytdlp(self, video_url, output_dir):
        """Download video using yt-dlp at native resolution"""
        print(f"   Method: yt-dlp")
        
        # Build format string based on quality requirements
        # Prioritize m3u8 (HLS) streams which work reliably - Full HD quality
        format_string = (
            # Try m3u8/HLS 1080p stream
            '96/'
            # Then try DASH 1080p format with audio
            '137+140'  # 1080p video (137) + audio (140)
        )
        
        # Add height filter if native quality is required
        if self.config.require_native_quality:
            format_string = f"({format_string})[height>={MIN_NATIVE_HEIGHT}]"
            print(f"   Note: Requiring native quality ({MIN_NATIVE_HEIGHT}p+) - will abort if not available")
        else:
            # Add fallback formats for lower quality
            format_string += (
                # Fallback to combined formats
                '/bestvideo+bestaudio/'
                'best[ext=mp4]/best'
            )
            print(f"   Note: Will accept any quality if Full HD not available")
        
        ydl_opts = {
            'format': format_string,
            'merge_output_format': 'mp4',
            'writeinfojson': True,
            'writethumbnail': True,
            'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
            # Use clients that support m3u8 streams
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
                    return None
                    
                video_id = info['id']  # type: ignore
                base_path = f"{output_dir}/{video_id}"
                
                # Find downloaded video file
                video_file = self._find_file_with_extensions(base_path, self.VIDEO_EXTENSIONS)
                
                if not video_file:
                    return None
                
                # Find thumbnail file
                thumbnail_file = self._find_file_with_extensions(base_path, self.THUMBNAIL_EXTENSIONS)
                
                info_file = f"{output_dir}/{video_id}.info.json"
                
                return {
                    'video_file': video_file,
                    'thumbnail_file': thumbnail_file,
                    'info_file': info_file,
                    'info': info,
                    'success': True,
                    'method': 'yt-dlp'
                }
        
        except Exception as e:
            print(f"   yt-dlp failed: {e}")
            return None
    
    def _download_api(self, video_id, output_dir):
        """Download video using YouTube API at native resolution (fallback)"""
        print(f"   Method: YouTube API (fallback)")
        
        try:
            import requests
            from youtube_client import YouTubeClient
            from utils import StorageManager
            
            # Get YouTube service
            storage = StorageManager(self.config)
            youtube = YouTubeClient(self.config, storage)
            youtube.authenticate()
            
            # Get video details from API
            video_response = youtube.service.videos().list(  # type: ignore
                part='snippet,contentDetails,status',
                id=video_id,
                fields='items(id,snippet(title,description,tags,thumbnails,categoryId),contentDetails,status)'
            ).execute()
            youtube.add_quota_cost(1)
            
            if not video_response.get('items'):
                print(f"   Video not found in API")
                return None
            
            video_data = video_response['items'][0]
            snippet = video_data['snippet']
            
            # Use yt-dlp with specific format (96=1080p m3u8)
            print(f"   Checking available quality...")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': '96',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android'],
                    }
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)  # type: ignore
                
                if not info:
                    print(f"   Could not extract format info")
                    return None
                
                # Check quality
                height = info.get('height', 0)  # type: ignore
                
                if self.config.require_native_quality and height < MIN_NATIVE_HEIGHT:
                    print(f"   ❌ Quality check failed: Best available is {height}p < {MIN_NATIVE_HEIGHT}p")
                    print(f"   Skipping download (native quality required)")
                    return None
                else:
                    print(f"   ✓ Quality check passed: {height}p available")
                
                stream_url = info.get('url')  # type: ignore
                if not stream_url:
                    print(f"   Could not extract stream URL")
                    return None
                
                # Download video file
                video_file = f"{output_dir}/{video_id}.mp4"
                print(f"   Downloading {height}p stream...")
                self._download_stream(stream_url, video_file)
                
                # Download thumbnail
                thumbnail_file = None
                thumbnails = snippet.get('thumbnails', {})
                thumbnail_url = None
                
                for quality in ['maxres', 'standard', 'high', 'medium', 'default']:
                    if quality in thumbnails:
                        thumbnail_url = thumbnails[quality]['url']
                        break
                
                if thumbnail_url:
                    thumbnail_file = f"{output_dir}/{video_id}.jpg"
                    try:
                        thumb_response = requests.get(thumbnail_url, timeout=30)
                        thumb_response.raise_for_status()
                        with open(thumbnail_file, 'wb') as f:
                            f.write(thumb_response.content)
                        print(f"   ✓ Thumbnail downloaded")
                    except Exception as e:
                        print(f"   ⚠️ Thumbnail download failed: {e}")
                        thumbnail_file = None
                
                # Save info as JSON
                info_file = f"{output_dir}/{video_id}.info.json"
                info_data = {
                    'id': video_id,
                    'title': snippet.get('title'),
                    'description': snippet.get('description'),
                    'tags': snippet.get('tags', []),
                    'category_id': snippet.get('categoryId'),
                    'thumbnails': snippet.get('thumbnails'),
                    'channel': snippet.get('channelTitle'),
                    'channel_id': snippet.get('channelId'),
                }
                
                with open(info_file, 'w', encoding='utf-8') as f:
                    json.dump(info_data, f, indent=2, ensure_ascii=False)
                
                return {
                    'video_file': video_file,
                    'thumbnail_file': thumbnail_file,
                    'info_file': info_file,
                    'info': info_data,
                    'success': True,
                    'method': 'api'
                }
        
        except Exception as e:
            print(f"   API download failed: {e}")
            return None
    
    def _download_stream(self, url, output_file):
        """Download a single stream with progress tracking"""
        import requests
        
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = int((downloaded / total_size) * 100)
                        print(f"\r   Progress: {progress}%", end='', flush=True)
        
        print(f"\r   ✓ Downloaded ({downloaded / 1024 / 1024:.1f} MB)")
    
    def cleanup(self, video_data):
        """Remove temporary files"""
        files_to_remove = [
            video_data.get('video_file'),
            video_data.get('thumbnail_file'),
            video_data.get('info_file')
        ]
        
        for file in files_to_remove:
            if file and os.path.exists(file):
                try:
                    os.remove(file)
                except Exception as e:
                    print(f"⚠️ Error removing file {file}: {e}")


class VideoUploader:
    """Manages video uploads to YouTube"""
    
    def __init__(self, config, youtube_client=None):  # type: ignore
        self.config = config
        self.youtube_client = youtube_client  # Store reference to track quota
    
    def upload(self, youtube_service, video_data):
        """Upload video to YouTube with original metadata"""
        if self.config.dry_run:
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
        if self.youtube_client:
            self.youtube_client.add_quota_cost(QUOTA_VIDEO_UPLOAD)
            self.youtube_client.save_quota_state()
        
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
                if self.youtube_client:
                    self.youtube_client.add_quota_cost(QUOTA_THUMBNAIL_UPLOAD)
                    self.youtube_client.save_quota_state()
                
                youtube_service.thumbnails().set(  # type: ignore
                    videoId=response['id'],
                    media_body=MediaFileUpload(thumbnail_file)  # type: ignore[arg-type]
                ).execute()
                
                print("\r✓ Thumbnail uploaded successfully!")
            except Exception as e:
                print(f"\r⚠️ Error uploading thumbnail: {e}")
        
        return response['id']