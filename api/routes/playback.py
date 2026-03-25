from fastapi import APIRouter, HTTPException
import logging

router = APIRouter(prefix="/playback", tags=["playback"])
logger = logging.getLogger("PlaybackRoute")

@router.post("/{action}")
async def control_playback(action: str):
    from api.api_server import player
    if not player:
        raise HTTPException(status_code=503, detail="Player not initialized")
    
    if action == "play": player.play()
    elif action == "pause": player.pause()
    elif action == "next": player.next_track()
    elif action == "prev": player.prev_track()
    elif action == "shuffle": player.shuffle_mode = not player.shuffle_mode
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    
    return {"status": "success", "action": action}

@router.get("/status")
async def get_status():
    from api.api_server import player
    return player.get_status() if player else {"error": "offline"}
