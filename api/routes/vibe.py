from fastapi import APIRouter
import logging
from collections import Counter

router = APIRouter(prefix="/vibe", tags=["vibe"])
logger = logging.getLogger("VibeRoute")

@router.get("/current")
async def get_current():
    from api.api_server import vibe_engine, api_response
    if vibe_engine:
        return api_response(data=vibe_engine.get_state())
    return api_response(success=False, error="VibeEngine not initialized")

@router.get("/journal")
async def get_journal():
    """Returns aggregated vibe analytics to prevent frontend stuttering."""
    from api.api_server import vibe_engine, api_response
    if vibe_engine:
        with vibe_engine.lock:
            journal = list(vibe_engine.journal)
        
        # Aggregate logic (Optimization from PDF)
        counts = dict(Counter(journal))
        summary = {
            "total_samples": len(journal),
            "distribution": counts,
            "recent_trend": journal[-10:] if len(journal) >= 10 else journal
        }
        return api_response(data=summary)
    return api_response(success=False, error="VibeEngine not initialized")
