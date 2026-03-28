from fastapi import APIRouter
import logging

router = APIRouter(prefix="", tags=["faces"])
logger = logging.getLogger("FacesRoute")

@router.get("/faces")
@router.get("/faces/")
async def list_faces():
    """Returns flat face summary stats."""
    from api import api_server as server
    face_registry = getattr(server, 'face_registry', None)
    if face_registry:
        return face_registry.get_summary()
    return {"total_unique": 0, "by_group": {"kids": 0, "youths": 0, "adults": 0, "seniors": 0}}

@router.get("/drive/status")
@router.get("/drive/status/")
async def drive_status():
    """Returns flat drive sync status."""
    from api import api_server as server
    face_vault = getattr(server, 'face_vault', None)
    if face_vault:
        return face_vault.get_status()
    return {"connected": False, "last_sync": None, "pending_count": 0}

@router.post("/faces/sync")
async def sync_now():
    """Triggers immediate sync."""
    from api import api_server as server
    face_vault = getattr(server, 'face_vault', None)
    if face_vault:
        face_vault.sync_now()
        return {"ok": True}
    return {"ok": False, "error": "FaceVault not initialized"}
