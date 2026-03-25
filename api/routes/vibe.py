from fastapi import APIRouter
import logging

router = APIRouter(prefix="/vibe", tags=["vibe"])

@router.get("/current")
async def get_current_vibe():
    from api.api_server import vibe_engine
    return vibe_engine.get_status() if vibe_engine else {"error": "offline"}

@router.get("/journal")
async def get_journal():
    from api.api_server import vibe_engine
    if not vibe_engine: return []
    with vibe_engine.lock:
        return list(vibe_engine.journal)
