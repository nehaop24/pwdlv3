import os
import requests
import subprocess
from pathlib import Path
from typing import Dict, Optional, Callable, List
import concurrent.futures
from threading import Lock
from tqdm import tqdm
import time

from pw_api import LicenseKeyFetcher, MPDParser, PWAPIError
from config import config

class DownloadResult:
    def __init__(self, init_file: Optional[Path], segments_dir: Path, 
                 total_segments: int, successful_segments: int, failed_segments: List[int]):
        self.init_file = init_file
        self.segments_dir = segments_dir
        self.total_segments = total_segments
        self.successful_segments = successful_segments
        self.failed_segments = failed_segments
        self.encoded_file = ""

class ProgressTracker:
    def __init__(self, total_segments: int, media_type: str, progress_callback: Optional[Callable] = None):
        self.total = total_segments
        self.current = 0
        self.media_type = media_type
        self.lock = Lock()
        self.failed_segments = []
        self.progress_callback = progress_callback
        self.pbar = tqdm(
            total=total_segments,
            desc=f"{media_type.capitalize()} Progress",
            unit='segment',
        )

    def update(self, segment_num: int, success: bool = True) -> Dict:
        with self.lock:
            self.current += 1
            if not success:
                self.failed_segments.append(segment_num)

            self.pbar.update(1)
            
            progress_info = {
                "type": self.media_type,
                "total": self.total,
                "current": self.current,
                "percentage": (self.current / self.total) * 100,
                "segment_num": segment_num,
                "success": success,
                "failed_segments": self.failed_segments.copy()
            }
            
            if self.progress_callback:
                self.progress_callback(progress_info)
                
            return progress_info

    def close(self):
        self.pbar.close()

class PWDownloader:
    def __init__(self, tmp_dir: str = "tmp", out_dir: str = "output", 
                 max_workers: int = 8, progress_callback: Optional[Callable] = None):
        self.tmp_dir = Path(tmp_dir)
        self.out_dir = Path(out_dir)
        self.max_workers = max_workers
        self.progress_callback = progress_callback
        
        # Create directories
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _download_segment(self, url: str, output_path: Path, retry_count: int = 3) -> bool:
        """Download a single segment with retry logic"""
        for attempt in range(retry_count):
            try:
                response = requests.get(url, allow_redirects=True, timeout=30)
                response.raise_for_status()

                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            except Exception as e:
                if attempt == retry_count - 1:
                    print(f"Failed to download {url}: {str(e)}")
                    return False
                time.sleep(1)  # Wait before retry
        return False

    def _process_segment(self, args: tuple) -> bool:
        """Process a single segment download"""
        url, output_path, segment_num, progress_tracker = args
        success = self._download_segment(url, output_path)
        progress_tracker.update(segment_num, success)
        return success

    def _download_media(self, media_data: Dict, media_type: str, output_dir: Path) -> DownloadResult:
        """Download all segments for a media type"""
        if not media_data or "segments" not in media_data:
            print(f"No {media_type} data provided")
            return DownloadResult(None, output_dir, 0, 0, [])

        total_segments = len(media_data["segments"])
        init_file_path = None

        progress_tracker = ProgressTracker(total_segments, media_type, self.progress_callback)

        # Download init segment first
        if "init" in media_data:
            init_filename = f"init.mp4"
            init_file_path = output_dir / init_filename
            if not self._download_segment(media_data["init"], init_file_path):
                print(f"Failed to download {media_type} init segment")
                return DownloadResult(None, output_dir, total_segments, 0, list(range(1, total_segments + 1)))

        # Prepare segment download tasks
        download_tasks = []
        for segment_num, segment_url in media_data["segments"].items():
            segment_filename = f"{segment_num:04d}.mp4"
            segment_path = output_dir / segment_filename
            download_tasks.append((segment_url, segment_path, int(segment_num), progress_tracker))

        successful_segments = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self._process_segment, task) for task in download_tasks]
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    successful_segments += 1

        progress_tracker.close()

        return DownloadResult(
            init_file_path,
            output_dir,
            total_segments,
            successful_segments,
            progress_tracker.failed_segments
        )

    def _concatenate_segments(self, segments_dir: Path, output_filename: str) -> str:
        """Concatenate MP4 segments into a single file"""
        output_file = self.out_dir / output_filename
        
        # Find init and segment files
        init_file = segments_dir / "init.mp4"
        segment_files = sorted([f for f in segments_dir.glob("*.mp4") if f.name != "init.mp4"])
        
        try:
            with open(output_file, "wb") as outfile:
                # Write init segment
                if init_file.exists():
                    with open(init_file, "rb") as f:
                        outfile.write(f.read())
                
                # Write all segments in order
                for segment_file in segment_files:
                    with open(segment_file, "rb") as f:
                        outfile.write(f.read())
            
            print(f"Concatenated segments to: {output_file}")
            return str(output_file.absolute())
            
        except Exception as e:
            raise PWAPIError(f"Error concatenating segments: {str(e)}")

    def _decrypt_file(self, input_file: str, key: str, output_file: str) -> bool:
        """Decrypt MP4 file using mp4decrypt"""
        try:
            # Try to find mp4decrypt in common locations
            mp4decrypt_paths = [
                "mp4decrypt",
                "./bin/mp4decrypt",
                "./mp4decrypt",
                "/usr/local/bin/mp4decrypt"
            ]
            
            mp4decrypt_cmd = None
            for path in mp4decrypt_paths:
                try:
                    subprocess.run([path, "--version"], capture_output=True, check=True)
                    mp4decrypt_cmd = path
                    break
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue
            
            if not mp4decrypt_cmd:
                print("mp4decrypt not found. Please install it or add it to PATH.")
                return False
            
            # Decrypt the file
            cmd = [mp4decrypt_cmd, "--key", f"1:{key}", input_file, output_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"Successfully decrypted: {output_file}")
                return True
            else:
                print(f"Decryption failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"Error during decryption: {str(e)}")
            return False

    def _merge_audio_video(self, audio_file: str, video_file: str, output_file: str) -> bool:
        """Merge audio and video files using ffmpeg"""
        try:
            # Try to find ffmpeg
            ffmpeg_paths = [
                "ffmpeg",
                "./bin/ffmpeg", 
                "./ffmpeg",
                "/usr/local/bin/ffmpeg"
            ]
            
            ffmpeg_cmd = None
            for path in ffmpeg_paths:
                try:
                    subprocess.run([path, "-version"], capture_output=True, check=True)
                    ffmpeg_cmd = path
                    break
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue
            
            if not ffmpeg_cmd:
                print("ffmpeg not found. Please install it or add it to PATH.")
                return False
            
            # Merge files
            cmd = [
                ffmpeg_cmd, "-y",
                "-i", video_file,
                "-i", audio_file,
                "-c", "copy",
                output_file
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"Successfully merged: {output_file}")
                return True
            else:
                print(f"Merge failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"Error during merge: {str(e)}")
            return False

    def download_video(self, video_id: str, batch_name: str, name: str, token: str, random_id: str, quality: Optional[int] = None) -> Optional[str]:
        """Main download function for batch videos"""
        try:
            print(f"Starting download for: {name}")
            print(f"Video ID: {video_id}")
            print(f"Batch: {batch_name}")
            if quality:
                print(f"Target Quality: {quality}p")
            
            # Initialize API client
            fetcher = LicenseKeyFetcher(token, random_id)
            
            # Get video URL and decryption key
            print("Getting video URL and decryption key...")
            mpd_url, key, cookies = fetcher.get_video_url_and_key(video_id, batch_name)
            
            # Parse MPD and get segment URLs
            print("Parsing MPD manifest...")
            parser = MPDParser(mpd_url)
            segment_urls = parser.get_segment_urls(target_height=quality)
            
            # Create download directories
            download_id = f"{name}_{video_id}"
            audio_dir = self.tmp_dir / download_id / "audio"
            video_dir = self.tmp_dir / download_id / "video"
            audio_dir.mkdir(parents=True, exist_ok=True)
            video_dir.mkdir(parents=True, exist_ok=True)
            
            # Download audio and video segments
            print("Downloading audio segments...")
            audio_result = self._download_media(segment_urls['audio'], "audio", audio_dir)
            
            print("Downloading video segments...")
            video_result = self._download_media(segment_urls['video'], "video", video_dir)
            
            # Concatenate segments
            print("Concatenating audio segments...")
            audio_encrypted = self._concatenate_segments(audio_dir, f"{name}_audio_encrypted.mp4")
            
            print("Concatenating video segments...")
            video_encrypted = self._concatenate_segments(video_dir, f"{name}_video_encrypted.mp4")
            
            # Decrypt files
            audio_decrypted = str(self.out_dir / f"{name}_audio.mp4")
            video_decrypted = str(self.out_dir / f"{name}_video.mp4")
            
            print("Decrypting audio...")
            if not self._decrypt_file(audio_encrypted, key, audio_decrypted):
                raise PWAPIError("Audio decryption failed")
            
            print("Decrypting video...")
            if not self._decrypt_file(video_encrypted, key, video_decrypted):
                raise PWAPIError("Video decryption failed")
            
            # Merge audio and video
            final_output = str(self.out_dir / f"{name}.mp4")
            print("Merging audio and video...")
            if not self._merge_audio_video(audio_decrypted, video_decrypted, final_output):
                raise PWAPIError("Audio/video merge failed")
            
            # Cleanup temporary files
            try:
                os.remove(audio_encrypted)
                os.remove(video_encrypted)
                os.remove(audio_decrypted)
                os.remove(video_decrypted)
                
                # Remove temporary directories
                import shutil
                shutil.rmtree(self.tmp_dir / download_id, ignore_errors=True)
            except Exception as e:
                print(f"Cleanup warning: {str(e)}")
            
            print(f"Download completed successfully: {final_output}")
            return final_output
            
        except Exception as e:
            print(f"Download failed: {str(e)}")
            raise PWAPIError(f"Download failed: {str(e)}")

    def download_from_direct_link(self, link: str, token: str, random_id: str, quality: Optional[int] = None) -> Optional[str]:
        """Download from direct MPD link"""
        try:
            # Initialize API client
            fetcher = LicenseKeyFetcher(token, random_id)
            
            # Parse the direct link
            video_id, batch_id, name = fetcher.parse_direct_link(link)
            print(f"Parsed link - Video ID: {video_id}, Batch ID: {batch_id}, Name: {name}")
            
            # Extract MPD URL from the link
            if ':' in link:
                mpd_url = link.split(':', 1)[1].strip()
            else:
                mpd_url = link.strip()
            
            # Get decryption key for the direct link
            print("Getting decryption key...")
            mpd_url, key, cookies = fetcher.get_video_url_and_key_from_direct_link(mpd_url)
            
            # Parse MPD and get segment URLs
            print("Parsing MPD manifest...")
            parser = MPDParser(mpd_url)
            
            # Show available qualities
            qualities = parser.get_available_qualities()
            if qualities:
                print("Available qualities:")
                for q in qualities:
                    print(f"  - {q['label']} ({q['height']}p)")
            
            segment_urls = parser.get_segment_urls(target_height=quality)
            
            # Create download directories
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            download_id = f"{safe_name}_{video_id}"
            audio_dir = self.tmp_dir / download_id / "audio"
            video_dir = self.tmp_dir / download_id / "video"
            audio_dir.mkdir(parents=True, exist_ok=True)
            video_dir.mkdir(parents=True, exist_ok=True)
            
            # Download audio and video segments
            print("Downloading audio segments...")
            audio_result = self._download_media(segment_urls['audio'], "audio", audio_dir)
            
            print("Downloading video segments...")
            video_result = self._download_media(segment_urls['video'], "video", video_dir)
            
            # Concatenate segments
            print("Concatenating audio segments...")
            audio_encrypted = self._concatenate_segments(audio_dir, f"{safe_name}_audio_encrypted.mp4")
            
            print("Concatenating video segments...")
            video_encrypted = self._concatenate_segments(video_dir, f"{safe_name}_video_encrypted.mp4")
            
            # Decrypt files
            audio_decrypted = str(self.out_dir / f"{safe_name}_audio.mp4")
            video_decrypted = str(self.out_dir / f"{safe_name}_video.mp4")
            
            print("Decrypting audio...")
            if not self._decrypt_file(audio_encrypted, key, audio_decrypted):
                raise PWAPIError("Audio decryption failed")
            
            print("Decrypting video...")
            if not self._decrypt_file(video_encrypted, key, video_decrypted):
                raise PWAPIError("Video decryption failed")
            
            # Merge audio and video
            final_output = str(self.out_dir / f"{safe_name}.mp4")
            print("Merging audio and video...")
            if not self._merge_audio_video(audio_decrypted, video_decrypted, final_output):
                raise PWAPIError("Audio/video merge failed")
            
            # Cleanup temporary files
            try:
                os.remove(audio_encrypted)
                os.remove(video_encrypted)
                os.remove(audio_decrypted)
                os.remove(video_decrypted)
                
                # Remove temporary directories
                import shutil
                shutil.rmtree(self.tmp_dir / download_id, ignore_errors=True)
            except Exception as e:
                print(f"Cleanup warning: {str(e)}")
            
            print(f"Download completed successfully: {final_output}")
            return final_output
            
        except Exception as e:
            print(f"Download failed: {str(e)}")
            raise PWAPIError(f"Download failed: {str(e)}")