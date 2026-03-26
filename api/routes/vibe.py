from fastapi import APIRouter
import logging

router = APIRouter(prefix="/vibe", tags=["vibe"])
logger = logging.getLogger("VibeRoute")

@router.get("/current")
async def get_current():
    import api.api_server as server
    if server.vibe_engine:
        return server.vibe_engine.get_state()
    return {"status": "error", "message": "VibeEngine not initialized"}

@router.get("/journal")
async def get_journal():
    import api.api_server as server
    if server.vibe_engine:
        with server.vibe_engine.lock:
            journal = list(server.vibe_engine.journal)
        return {"entries": journal, "count": len(journal)}
    return {"entries": [], "count": 0}
