from fastapi import APIRouter
import logging
from collections import Counter

router = APIRouter(prefix="/vibe", tags=["vibe"])
logger = logging.getLogger("VibeRoute")

# Global references - set by api_server during startup
refs = {
    "vibe_engine": None,
    "player": None,
    "cam_pool": None,
    "face_registry": None
}

def set_refs(vibe_engine, player, cam_pool=None, face_registry=None):
    """Set references (called by api_server during startup)."""
    refs["vibe_engine"] = vibe_engine
    refs["player"] = player
    refs["cam_pool"] = cam_pool
    refs["face_registry"] = face_registry

@router.get("/current")
@router.get("/current/")
async def get_current():
    """Returns flat vibe state."""
    vibe_engine = refs.get("vibe_engine")
    player = refs.get("player")
    cam_pool = refs.get("cam_pool")
    face_registry = refs.get("face_registry")

    if vibe_engine:
        cam_count = len(cam_pool.sources) if cam_pool else 0
        face_count = face_registry.get_summary().get('total_unique', 0) if face_registry else 0
        saved_count = face_registry.get_saved_count() if face_registry else 0
        
        state = vibe_engine.get_state(player=player, camera_count=cam_count, face_count=face_count)
        # Override with actual saved faces count
        state['unique_faces'] = saved_count
        state['active_cameras'] = cam_count
        return state
        
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
        "next_vibe": None,
        "active_cameras": 0,
        "unique_faces": 0
    }

@router.get("/journal")
@router.get("/journal/")
async def get_journal():
    """Returns flat aggregated vibe analytics."""
    vibe_engine = refs.get("vibe_engine")
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
