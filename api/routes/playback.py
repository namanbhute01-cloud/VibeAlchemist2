from fastapi import APIRouter, Request, UploadFile, File, Form
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

router = APIRouter(prefix="/playback", tags=["playback"])
logger = logging.getLogger("PlaybackRoute")

# Global references - set by api_server during startup
refs = {"player": None, "vibe_engine": None}

def set_refs(player, vibe_engine):
    """Set references (called by api_server during startup)."""
    refs["player"] = player
    refs["vibe_engine"] = vibe_engine

@router.get("/library")
async def get_library():
    """Returns the music library organized by age groups."""
    player = refs.get("player")

    if player and hasattr(player, 'music_root'):
        music_dir = Path(player.music_root)
        library = {}
        for group in ["kids", "youths", "adults", "seniors"]:
            group_dir = music_dir / group
            if group_dir.exists():
                files = [f.name for f in group_dir.iterdir() if f.is_file() and f.suffix.lower() in ['.mp3', '.wav', '.flac', '.m4a', '.ogg']]
                library[group] = files
            else:
                library[group] = []
        return library

    return {"kids": [], "youths": [], "adults": [], "seniors": []}

@router.get("/status")
async def get_status():
    """Returns flat playback status."""
    player = refs.get("player")
    if player:
        return player.get_status()
    return {
        "song": "None",
        "percent": 0,
        "paused": False,
        "shuffle": True,
        "group": "adults",
        "volume": 70
    }

@router.post("/add-song")
async def add_song(
    file: Optional[UploadFile] = File(None),
    group: str = Form("adults"),
    url: Optional[str] = Form(None)
):
    """
    Add a song to the music library.
    Supports:
    - File upload (multipart/form-data)
    - URL download (YouTube, direct MP3, etc.)
    
    Args:
        file: Audio file to upload (mp3, wav, flac, m4a, ogg)
        group: Age group folder (kids, youths, adults, seniors)
        url: Optional URL to download from
    """
    player = refs.get("player")
    
    if not player or not hasattr(player, 'music_root'):
        return {"ok": False, "error": "Player not initialized"}
    
    # Validate group
    valid_groups = ["kids", "youths", "adults", "seniors"]
    if group not in valid_groups:
        return {"ok": False, "error": f"Invalid group. Must be one of: {valid_groups}"}
    
    music_dir = Path(player.music_root) / group
    music_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        filename = None
        
        # Handle file upload
        if file and file.filename:
            # Validate file extension
            allowed_extensions = ['.mp3', '.wav', '.flac', '.m4a', '.ogg']
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in allowed_extensions:
                return {"ok": False, "error": f"Invalid file type. Allowed: {allowed_extensions}"}
            
            # Save file
            filename = file.filename
            filepath = music_dir / filename
            
            # Handle duplicate filenames
            counter = 1
            while filepath.exists():
                stem = Path(file.filename).stem
                suffix = Path(file.filename).suffix
                filename = f"{stem}_{counter}{suffix}"
                filepath = music_dir / filename
                counter += 1
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            logger.info(f"Uploaded song: {filename} to {group}")
        
        # Handle URL download (future enhancement - would need yt-dlp or similar)
        elif url:
            return {
                "ok": False, 
                "error": "URL download not yet implemented. Please upload file directly."
            }
        
        else:
            return {"ok": False, "error": "No file or URL provided"}
        
        return {
            "ok": True, 
            "filename": filename,
            "group": group,
            "path": str(music_dir / filename)
        }
    
    except Exception as e:
        logger.error(f"Error adding song: {e}")
        return {"ok": False, "error": str(e)}

@router.post("/{action}")
async def control_playback(action: str, request: Request):
    """Handles playback actions with flat JSON responses."""
    player = refs.get("player")
    vibe_engine = refs.get("vibe_engine")

    if not player:
        return {"ok": False, "error": "Player not initialized"}

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if action == "pause" or action == "play":
        player.toggle_pause()
    elif action == "next":
        group = body.get("group") or (vibe_engine.current_vibe if vibe_engine else "adults")
        player.next(group)
    elif action == "prev":
        player.prev()
    elif action == "shuffle":
        mode = player.toggle_shuffle()
        return {"ok": True, "shuffle": mode}
    elif action == "volume":
        level = body.get("level") or body.get("vol") or 70
        player.set_volume(int(level))
        return {"ok": True}
    elif action == "mute":
        player.set_volume(0)
        return {"ok": True}
    elif action == "unmute":
        player.set_volume(70)  # Restore to default
        return {"ok": True}

    return {"ok": True}
