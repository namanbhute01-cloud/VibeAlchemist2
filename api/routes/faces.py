from fastapi import APIRouter
import logging

router = APIRouter(prefix="/faces", tags=["faces"])
logger = logging.getLogger("FacesRoute")

# Global references - set by api_server during startup
refs = {"face_registry": None, "face_vault": None}

def set_refs(face_registry, face_vault):
    """Set references (called by api_server during startup)."""
    refs["face_registry"] = face_registry
    refs["face_vault"] = face_vault

@router.get("")
@router.get("/")
async def list_faces():
    """Returns flat face summary stats."""
    face_registry = refs.get("face_registry")
    if face_registry:
        return face_registry.get_summary()
    return {"total_unique": 0, "by_group": {"kids": 0, "youths": 0, "adults": 0, "seniors": 0}}

@router.get("/drive/status")
async def drive_status():
    """Returns flat drive sync status."""
    face_vault = refs.get("face_vault")
    if face_vault:
        return face_vault.get_status()
    return {"connected": False, "last_sync": None, "pending_count": 0}

@router.post("/sync")
async def sync_now():
    """Triggers immediate sync."""
    face_vault = refs.get("face_vault")
    if face_vault:
        face_vault.sync_now()
        return {"ok": True}
    return {"ok": False, "error": "FaceVault not initialized"}
