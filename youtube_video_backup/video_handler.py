#!/usr/bin/env python3
"""
Video Handler Module
Handles video download (yt-dlp) and upload to YouTube
"""

import json
import os
import socket
import subprocess
import time

import yt_dlp
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# YouTube API Quota Costs (as per YouTube Data API v3 documentation)
QUOTA_VIDEO_UPLOAD = 1600

# Upload retry settings
UPLOAD_MAX_RETRIES = 10
UPLOAD_INITIAL_BACKOFF_SECONDS = 2
UPLOAD_MAX_BACKOFF_SECONDS = 60
RETRYABLE_HTTP_STATUS_CODES = {500, 502, 503, 504}
QUOTA_THUMBNAIL_UPLOAD = 50

# Quality constraints
MIN_NATIVE_HEIGHT = 1080  # Minimum resolution for "native quality"


class VideoDownloader:
    """Manages video downloads with yt-dlp"""
    
    # File extensions to search for
    VIDEO_EXTENSIONS = ['mp4', 'webm', 'mkv', 'mov']
    THUMBNAIL_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
    
    def __init__(self, config):
        """Initialise the video downloader with the active configuration."""
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
    def _get_file_size(filepath):
        """Get file size in human-readable format"""
        if not filepath or not os.path.exists(filepath):
            return None
        
        try:
            size_bytes = os.path.getsize(filepath)
            
            # Convert to human-readable format
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f}{unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f}TB"
        except:
            pass
        
        return None
    
    @staticmethod
    def _format_file_info(filepath, resolution, file_size):
        """Format file display with optional resolution and file size"""
        filename = os.path.basename(filepath)
        info_parts = []
        
        if resolution:
            info_parts.append(resolution)
        if file_size:
            info_parts.append(file_size)
        
        if info_parts:
            return f"{filename} [{', '.join(info_parts)}]"
        return filename
    
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

    def _list_available_formats(self, video_url):
        """List all available formats for a video and let user choose"""
        print(f"\n📋 Fetching available formats...")

        try:
            # Get format list without downloading
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(video_url, download=False)  # type: ignore

                if not info or 'formats' not in info:
                    print("   ❌ Could not retrieve format list")
                    return None

                formats = info.get('formats') or []  # type: ignore

                # Filter and organize formats
                video_formats = []
                for fmt in formats:
                    # Only include formats with video stream
                    if fmt.get('vcodec') != 'none':
                        # Identify HLS/DASH problematic formats
                        protocol = fmt.get('protocol', '')

                        # Detect HLS: check protocol and URL
                        is_hls = 'm3u8' in protocol or 'hls' in protocol.lower()
                        if not is_hls and 'url' in fmt:
                            # Fallback: check URL for m3u8
                            is_hls = '.m3u8' in str(fmt.get('url', ''))

                        format_info = {
                            'id': fmt.get('format_id', 'unknown'),
                            'ext': fmt.get('ext', 'unknown'),
                            'resolution': fmt.get('resolution', 'unknown'),
                            'height': fmt.get('height', 0),
                            'fps': fmt.get('fps', 0),
                            'vcodec': fmt.get('vcodec', 'unknown'),
                            'acodec': fmt.get('acodec', 'none'),
                            'filesize': fmt.get('filesize', 0),
                            'tbr': fmt.get('tbr', 0),
                            'is_hls': is_hls,
                        }
                        video_formats.append(format_info)

                # Sort by resolution (height) descending, handling None values
                # Prioritize by: 1) resolution (height in pixels), 2) non-HLS at same resolution
                def sort_key(fmt):
                    height = fmt['height'] or 0
                    is_hls = fmt.get('is_hls', False)
                    # Higher resolution wins, but at same resolution prefer non-HLS
                    # not is_hls = True (1) for non-HLS, False (0) for HLS
                    return (height, not is_hls)

                video_formats.sort(key=sort_key, reverse=True)

                if not video_formats:
                    print("   ❌ No video formats available")
                    return None

                # Display formats
                print(f"\n{'─'*88}")
                print(f"📹 Available formats ({len(video_formats)} total):")
                print(f"{'─'*88}")
                print(f"{'#':<4} {'ID':<8} {'Resolution':<15} {'FPS':<6} {'Ext':<6} {'Audio':<10} {'Size':<12} {'Type':<8}")
                print(f"{'─'*88}")

                for idx, fmt in enumerate(video_formats, 1):
                    has_audio = '✓ Yes' if fmt['acodec'] != 'none' else '✗ No'

                    # Format file size
                    if fmt['filesize'] and fmt['filesize'] > 0:
                        size_mb = fmt['filesize'] / (1024 * 1024)
                        size_str = f"{size_mb:.1f} MB"
                    else:
                        size_str = "Unknown"

                    # Format FPS
                    if fmt['fps'] and fmt['fps'] > 0:
                        fps_str = f"{fmt['fps']:.0f}"
                    else:
                        fps_str = "?"

                    # Format type
                    format_type = "⚠️ HLS" if fmt['is_hls'] else "Standard"

                    print(f"{idx:<4} {fmt['id']:<8} {fmt['resolution']:<15} {fps_str:<6} "
                          f"{fmt['ext']:<6} {has_audio:<10} {size_str:<12} {format_type:<8}")

                print(f"{'─'*88}")

                # Display HLS warning if any HLS formats are present
                if any(fmt['is_hls'] for fmt in video_formats):
                    print("\n⚠️  Note: HLS formats may have unstable fragments and could fail mid-download.")

                # Ask user to choose
                print("\nOptions:")
                print("  [number] - Select specific format by number")
                print("  a        - Auto-select best available format (recommended)")
                print("  0        - Cancel")

                while True:
                    try:
                        choice = input("\nYour choice: ").strip().lower()

                        # Handle auto-select
                        if choice == 'a':
                            # Auto-select: first in list (already sorted with non-HLS priority)
                            selected = video_formats[0]
                            format_quality = "non-HLS" if not selected['is_hls'] else "HLS"
                            print(f"\n✓ Auto-selected: Format {selected['id']} - {selected['resolution']} ({format_quality})")
                            return selected['id']

                        # Handle cancel
                        if choice == '0':
                            print("   Operation cancelled")
                            return None

                        # Handle numeric selection
                        if not choice.isdigit():
                            print("❌ Invalid input. Enter a number, 'a' for auto, or '0' to cancel")
                            continue

                        choice_num = int(choice)

                        if 1 <= choice_num <= len(video_formats):
                            selected = video_formats[choice_num - 1]
                            print(f"\n✓ Selected: Format {selected['id']} - {selected['resolution']}")
                            return selected['id']
                        else:
                            print(f"❌ Please enter a number between 0 and {len(video_formats)}")

                    except KeyboardInterrupt:
                        print("\n   Operation cancelled")
                        return None
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        continue

        except Exception as e:
            print(f"   ❌ Error retrieving formats: {e}")
            return None
    
    def download(self, video_url, output_dir, custom_format=None):
        """Download video with yt-dlp

        Args:
            video_url: URL of the video to download
            output_dir: Directory to save the downloaded video
            custom_format: Optional custom format ID to use (bypasses default format selection)
        """
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

            # Display video with resolution and size
            video_resolution = self._get_video_resolution(video_file)
            video_size = self._get_file_size(video_file)
            print(f"      Video: {self._format_file_info(video_file, video_resolution, video_size)}")

            # Display thumbnail with resolution and size
            if thumbnail_file:
                thumb_resolution = self._get_image_resolution(thumbnail_file)
                thumb_size = self._get_file_size(thumbnail_file)
                print(f"      Thumbnail: {self._format_file_info(thumbnail_file, thumb_resolution, thumb_size)}")

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

        # Determine format string
        if custom_format:
            # Use custom format selected by user with robust fallback chain
            format_string = (
                f"{custom_format}+bestaudio[ext=m4a]/"
                f"{custom_format}+bestaudio/"
                f"{custom_format}/"
                f"best"
            )
            print(f"   Note: Using custom format {custom_format}")
        else:
            # Prioritize progressive formats (mp4, webm) instead of HLS
            if self.config.require_native_quality:
                format_string = (
                    f"bestvideo[height>={MIN_NATIVE_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/"
                    f"bestvideo[height>={MIN_NATIVE_HEIGHT}]+bestaudio/"
                    f"best[height>={MIN_NATIVE_HEIGHT}][ext=mp4]/"
                    f"best[height>={MIN_NATIVE_HEIGHT}]"
                )
                print(f"   Note: Requiring {MIN_NATIVE_HEIGHT}p+ quality")
            else:
                format_string = (
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo+bestaudio/"
                    "best[ext=mp4]/"
                    "best"
                )
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
            'socket_timeout': self.config.socket_timeout,
            'retries': self.config.download_retries,
            'fragment_retries': self.config.fragment_retries,
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
                    # Likely a network timeout that exhausted all retries
                    if not self.config.auto_confirm:
                        choice = input("\n   Retry download? (r=retry / s=skip): ").strip().lower()
                        if choice == 'r':
                            return self.download(video_url, output_dir, custom_format=custom_format)
                    return self._create_result()

                # Find thumbnail file
                thumbnail_file = self._find_file_with_extensions(base_path, self.THUMBNAIL_EXTENSIONS)

                print(f"   ✓ Download successful")
                return self._create_result(video_file, thumbnail_file, info)

        except Exception as e:
            error_str = str(e)
            self._log_download_error(error_str)

            # Check if error is about unavailable format
            if "Requested format is not available" in error_str:
                print(f"\n⚠️  The requested format is not available for this video.")
                print(f"   Let's select an available format...")

                # Ask user to select from available formats
                selected_format = self._list_available_formats(video_url)

                if selected_format:
                    # Retry download with selected format
                    print(f"\n🔄 Retrying download with selected format...")
                    return self.download(video_url, output_dir, custom_format=selected_format)
                else:
                    print(f"\n❌ No format selected, download cancelled")
                    return self._create_result()

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
            'privacyStatus': config.get_privacy_status(),
            'selfDeclaredMadeForKids': False
        }
    }
    
    # Get chunk size from config
    chunk_size = config.get_chunk_size_bytes()
    
    # Display upload info
    privacy_status = config.get_privacy_status()
    privacy_emoji = {'private': '🔒', 'unlisted': '🔗', 'public': '🌐'}
    print(f"   Privacy: {privacy_emoji.get(privacy_status, '🔒')} {privacy_status.capitalize()}")
    
    if chunk_size > 0:
        chunk_mb = chunk_size / (1024 * 1024)
        print(f"   Upload mode: Chunked ({chunk_mb:.0f}MB per chunk)")
    else:
        print(f"   Upload mode: Single chunk (entire file)")
    
    # Upload video with resumable protocol
    media = MediaFileUpload(
        video_file,
        chunksize=chunk_size,
        resumable=True
    )  # type: ignore[arg-type]
    
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
    retry_count = 0
    backoff = UPLOAD_INITIAL_BACKOFF_SECONDS
    print("   Uploading...", end='', flush=True)

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"\r   Uploading... {progress}%", end='', flush=True)
            retry_count = 0
            backoff = UPLOAD_INITIAL_BACKOFF_SECONDS
        except HttpError as e:
            if e.resp.status not in RETRYABLE_HTTP_STATUS_CODES or retry_count >= UPLOAD_MAX_RETRIES:
                print(f"\r❌ Upload failed: {e}")
                raise
            retry_count += 1
            print(f"\r   ⚠️  HTTP {e.resp.status}, retrying in {backoff}s ({retry_count}/{UPLOAD_MAX_RETRIES})...", end='', flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, UPLOAD_MAX_BACKOFF_SECONDS)
        except (ConnectionResetError, ConnectionError, socket.timeout) as e:
            # ConnectionResetError (WinError 10054) is not caught by the library's
            # built-in retry - must be handled at application level
            if retry_count >= UPLOAD_MAX_RETRIES:
                print(f"\r❌ Upload failed: {e}")
                raise
            retry_count += 1
            print(f"\r   ⚠️  Connection reset, retrying in {backoff}s ({retry_count}/{UPLOAD_MAX_RETRIES})...", end='', flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, UPLOAD_MAX_BACKOFF_SECONDS)

    print(f"\r✓ Video uploaded successfully! ID: {response['id']}")
    
    # Upload thumbnail if available
    if thumbnail_file and os.path.exists(thumbnail_file):
        converted_thumbnail = None
        try:
            print("   Uploading thumbnail...", end='', flush=True)

            # YouTube only accepts JPG/PNG - convert WebP if needed
            upload_thumbnail = thumbnail_file
            if thumbnail_file.lower().endswith('.webp'):
                from PIL import Image
                converted_thumbnail = os.path.splitext(thumbnail_file)[0] + '_thumb.jpg'
                with Image.open(thumbnail_file) as img:
                    img.convert('RGB').save(converted_thumbnail, 'JPEG', quality=95)
                upload_thumbnail = converted_thumbnail

            # Track quota cost and save to disk immediately before thumbnail upload
            if youtube_client:
                youtube_client.add_quota_cost(QUOTA_THUMBNAIL_UPLOAD)
                youtube_client.save_quota_state()

            youtube_service.thumbnails().set(  # type: ignore
                videoId=response['id'],
                media_body=MediaFileUpload(upload_thumbnail)  # type: ignore[arg-type]
            ).execute()

            print("\r✓ Thumbnail uploaded successfully!")
        except Exception as e:
            print(f"\r⚠️ Error uploading thumbnail: {e}")
        finally:
            if converted_thumbnail and os.path.exists(converted_thumbnail):
                os.remove(converted_thumbnail)
    
    return response['id']