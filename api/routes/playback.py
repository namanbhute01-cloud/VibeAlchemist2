from fastapi import APIRouter, Request
import logging
import os
from pathlib import Path
from typing import Optional

router = APIRouter(prefix="/playback", tags=["playback"])
logger = logging.getLogger("PlaybackRoute")

@router.get("/library")
async def get_library():
    """Returns the music library organized by age groups."""
    from api import api_server as server
    player = getattr(server, 'player', None)
    
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
    from api import api_server as server
    player = getattr(server, 'player', None)
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

@router.post("/{action}")
async def control_playback(action: str, request: Request):
    """Handles playback actions with flat JSON responses."""
    from api import api_server as server
    player = getattr(server, 'player', None)
    vibe_engine = getattr(server, 'vibe_engine', None)
    
    if not player:
        return {"ok": False, "error": "Player not initialized"}
    
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if action == "pause" or action == "play":
        # In the context of toggle_pause, we just call it
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
    
    return {"ok": True}
