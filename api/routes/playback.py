from fastapi import APIRouter, Request
import logging
from typing import Optional
from api.models import PlaybackCommand

router = APIRouter(prefix="/playback", tags=["playback"])
logger = logging.getLogger("PlaybackRoute")

@router.get("/status")
async def get_status():
    from api.api_server import player, api_response
    if player:
        return api_response(data=player.get_status())
    return api_response(success=False, error="Player not initialized")

@router.post("/{action}")
async def control_playback(action: str, cmd: Optional[PlaybackCommand] = None):
    from api.api_server import player, vibe_engine, api_response
    if not player:
        return api_response(success=False, error="Player not initialized")
    
    if action == "play":
        player.play(group=cmd.group if cmd else None)
    elif action == "pause":
        player.pause()
    elif action == "next":
        group = cmd.group if (cmd and cmd.group) else (vibe_engine.current_vibe if vibe_engine else "adults")
        player.play(group=group)
    elif action == "prev":
        player.prev_track()
    elif action == "shuffle":
        mode = player.toggle_shuffle()
        return api_response(data={"shuffle": mode})
    elif action == "volume":
        if cmd:
            vol = cmd.level if cmd.level is not None else cmd.vol
            if vol is not None:
                player.set_volume(vol)
                return api_response(data={"volume": vol})
    
    return api_response(data={"action": action})
