from fastapi import APIRouter
import logging
from collections import Counter

router = APIRouter(prefix="/vibe", tags=["vibe"])
logger = logging.getLogger("VibeRoute")

@router.get("/current")
@router.get("/current/")
async def get_current():
    """Returns flat vibe state."""
    from api import api_server as server
    vibe_engine = getattr(server, 'vibe_engine', None)
    player = getattr(server, 'player', None)
    
    if vibe_engine:
        return vibe_engine.get_state(player=player)
    return {
        "status": "offline",
        "detected_group": "None",
        "current_vibe": "None",
        "age": "...",
        "journal_count": 0,
        "percent_pos": 0,
        "is_playing": False,
        "paused": True,
        "shuffle": True,
        "current_song": "",
        "next_vibe": None
    }

@router.get("/journal")
@router.get("/journal/")
async def get_journal():
    """Returns flat aggregated vibe analytics."""
    from api import api_server as server
    vibe_engine = getattr(server, 'vibe_engine', None)
    if vibe_engine:
        with vibe_engine.lock:
            journal = list(vibe_engine.journal)
        
        counts = dict(Counter(journal))
        return {
            "entries": journal,
            "count": len(journal),
            "distribution": counts,
            "next_vibe": vibe_engine.next_vibe
        }
    return {"entries": [], "count": 0, "distribution": {}, "next_vibe": None}
