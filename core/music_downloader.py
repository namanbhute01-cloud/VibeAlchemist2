import os
import logging
import asyncio
import yt_dlp
import re
from pathlib import Path

logger = logging.getLogger("MusicDownloader")

def sanitize_filename(filename: str) -> str:
    """Sanitize filenames: replace / \ : * ? \" < > | with underscores and limit length."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", filename)
    # Max length 60 chars to avoid filesystem issues
    return sanitized[:60]

def download_song_sync(url: str, group: str = None) -> dict:
    """
    Synchronous download using yt-dlp.
    If group is provided, saves to ROOT_MUSIC_DIR / group.
    Otherwise, saves directly to ROOT_MUSIC_DIR.
    """
    root_music_dir = os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback")
    audio_format = os.getenv("YTDLP_AUDIO_FORMAT", "mp3")
    audio_quality = os.getenv("YTDLP_AUDIO_QUALITY", "192")
    
    target_dir = Path(root_music_dir)
    if group:
        target_dir = target_dir / group
        
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # yt-dlp options
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': audio_format,
            'preferredquality': audio_quality,
        }],
        'outtmpl': str(target_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info first to get title and sanitize it
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown Title')
            sanitized_title = sanitize_filename(title)
            
            # Update output template with sanitized title
            ydl_opts['outtmpl'] = str(target_dir / f"{sanitized_title}.%(ext)s")
            
            # Now download with sanitized title
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_actual:
                info = ydl_actual.extract_info(url, download=True)
                
            return {
                "status": "success",
                "filename": f"{sanitized_title}.{audio_format}",
                "title": title,
                "duration": info.get('duration'),
                "group": group
            }
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
        return {"status": "error", "message": str(e)}

async def download_song(youtube_url: str, group: str = None) -> dict:
    """
    Wrapper for non-blocking execution of the synchronous download.
    """
    return await asyncio.to_thread(download_song_sync, youtube_url, group)
