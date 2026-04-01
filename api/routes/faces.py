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
    """Returns detailed face summary stats including per-face details and camera tracking."""
    face_registry = refs.get("face_registry")
    if face_registry:
        summary = face_registry.get_summary()
        # Add detailed face list
        detailed_faces = []
        with face_registry.lock:
            for fid, data in face_registry.known_faces.items():
                detailed_faces.append({
                    'id': fid,
                    'group': data.get('group', 'unknown'),
                    'age': data.get('age', 'unknown'),
                    'cameras': list(data.get('cam_ids', set())),
                    'last_seen': data.get('last_seen', 0)
                })
        summary['faces'] = detailed_faces
        summary['saved_count'] = face_registry.get_saved_count()
        return summary
    return {"total_unique": 0, "by_group": {"kids": 0, "youths": 0, "adults": 0, "seniors": 0}, "faces": []}

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
