#!/usr/bin/env python3
"""
Video Handler Module
Handles video download (yt-dlp + API fallback) and upload to YouTube
"""

import os
import json
from typing import Dict, Any, Optional
import yt_dlp
from googleapiclient.http import MediaFileUpload

class VideoDownloader:
    """Manages video downloads with yt-dlp and API fallback"""
    
    def __init__(self, config):
        self.config = config
    
    def download(self, video_url, output_dir):
        """Download video with yt-dlp and API fallback"""
        print(f"\n⬇️ Downloading video...")
        
        # Extract video ID from URL
        video_id = video_url.split('watch?v=')[-1].split('&')[0]
        
        # Check if video already exists locally
        existing_files = self._check_existing_download(video_id, output_dir)
        if existing_files:
            print(f"\n   📁 Found existing download:")
            print(f"      Video: {os.path.basename(existing_files['video_file'])}")
            if existing_files.get('thumbnail_file'):
                print(f"      Thumbnail: {os.path.basename(existing_files['thumbnail_file'])}")
            
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
        result: Optional[Dict[str, Any]] = self._download_ytdlp(video_url, output_dir)
        
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
        # Check for video file
        video_file = None
        for ext in ['mp4', 'webm', 'mkv', 'mov']:
            potential_file = f"{output_dir}/{video_id}.{ext}"
            if os.path.exists(potential_file):
                video_file = potential_file
                break
        
        if not video_file:
            return None
        
        # Find thumbnail file
        thumbnail_file = None
        for ext in ['jpg', 'jpeg', 'png', 'webp']:
            potential_thumb = f"{output_dir}/{video_id}.{ext}"
            if os.path.exists(potential_thumb):
                thumbnail_file = potential_thumb
                break
        
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
        
        # First, extract info without downloading to check quality
        if self.config.require_native_quality:
            print(f"   Checking available quality...")
            check_opts = {
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web_safari'],
                        'player_skip': ['configs'],
                    }
                },
            }
            
            try:
                with yt_dlp.YoutubeDL(check_opts) as ydl:  # type: ignore[arg-type]
                    info_check = ydl.extract_info(video_url, download=False)  # type: ignore
                    if info_check:
                        # Check for available formats
                        formats = info_check.get('formats', [])  # type: ignore
                        max_height = 0
                        for fmt in formats:  # type: ignore
                            height = fmt.get('height', 0)
                            if height and height > max_height:
                                max_height = height
                        
                        if max_height < 720:
                            print(f"   ❌ Quality check failed: Best available is {max_height}p < 720p")
                            print(f"   Skipping download (native quality required)")
                            return None
                        else:
                            print(f"   ✓ Quality check passed: {max_height}p available")
            except Exception as e:
                print(f"   ⚠️ Could not check quality: {e}")
                print(f"   Proceeding with download attempt...")
        
        ydl_opts = {
            # Prioritize m3u8 (HLS) streams which work reliably - HD quality
            'format': (
                # Try m3u8/HLS streams first (ID 96=1080p, 95=720p)
                '96/95/'
                # Then try DASH formats with separate video+audio
                '137+140/'  # 1080p video (137) + audio (140)
                '136+140/'  # 720p video (136) + audio (140)
            ),
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
        
        # Add fallback formats only if native quality is not required
        if not self.config.require_native_quality:
            ydl_opts['format'] += (
                # Fallback to combined formats
                '/bestvideo+bestaudio/'
                'best[ext=mp4]/best'
            )
            print(f"   Note: Will accept any quality if HD not available")
        else:
            print(f"   Note: Requiring native quality (720p+) - will abort if not available")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(video_url, download=True)  # type: ignore
                if not info:
                    return None
                    
                video_id = info['id']  # type: ignore
                
                # Find downloaded video file
                video_file = None
                for ext in ['mp4', 'webm', 'mkv', 'mov']:
                    potential_file = f"{output_dir}/{video_id}.{ext}"
                    if os.path.exists(potential_file):
                        video_file = potential_file
                        break
                
                if not video_file:
                    return None
                
                # Find thumbnail file
                thumbnail_file = None
                for ext in ['jpg', 'jpeg', 'png', 'webp']:
                    potential_thumb = f"{output_dir}/{video_id}.{ext}"
                    if os.path.exists(potential_thumb):
                        thumbnail_file = potential_thumb
                        break
                
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
            
            # Get YouTube service
            youtube = YouTubeClient(self.config)
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
            
            # Use yt-dlp with specific format (96=1080p, 95=720p m3u8)
            print(f"   Checking available quality...")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': '96/95',  # Try 1080p or 720p m3u8 streams
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
                
                if self.config.require_native_quality and height < 720:
                    print(f"   ❌ Quality check failed: Best available is {height}p < 720p")
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
        
        # Track quota cost
        if self.youtube_client:
            self.youtube_client.add_quota_cost(1600)
        
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
                youtube_service.thumbnails().set(  # type: ignore
                    videoId=response['id'],
                    media_body=MediaFileUpload(thumbnail_file)  # type: ignore[arg-type]
                ).execute()
                
                # Track quota cost
                if self.youtube_client:
                    self.youtube_client.add_quota_cost(50)
                
                print("\r✓ Thumbnail uploaded successfully!")
            except Exception as e:
                print(f"\r⚠️ Error uploading thumbnail: {e}")
        
        return response['id']