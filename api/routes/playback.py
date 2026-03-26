from fastapi import APIRouter, Request
import logging

router = APIRouter(prefix="/playback", tags=["playback"])
logger = logging.getLogger("PlaybackRoute")

@router.get("/status")
async def get_status():
    import api.api_server as server
    if server.player:
        return server.player.get_status()
    return {"status": "error", "message": "Player not initialized"}

@router.post("/{action}")
async def control_playback(action: str, request: Request):
    import api.api_server as server
    if not server.player:
        return {"status": "error", "message": "Player not initialized"}
    
    body = {}
    try:
        if await request.body():
            body = await request.json()
    except:
        pass

    if action == "play":
        server.player.play()
    elif action == "pause":
        server.player.pause()
    elif action == "next":
        group = server.vibe_engine.current_vibe if server.vibe_engine else "adults"
        server.player.play(group=group)
    elif action == "prev":
        server.player.prev_track()
    elif action == "shuffle":
        mode = server.player.toggle_shuffle()
        return {"status": "ok", "shuffle": mode}
    elif action == "volume":
        vol = body.get("level") or body.get("vol")
        if vol is not None:
            server.player.set_volume(int(vol))
    
    return {"status": "ok", "action": action}
