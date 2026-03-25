from fastapi import APIRouter
from pathlib import Path
import os

router = APIRouter(prefix="/faces", tags=["faces"])

@router.get("/stats")
async def get_face_stats():
    from api.api_server import face_vault
    temp_dir = Path("temp_faces")
    local_count = len(list(temp_dir.glob("*.png")))
    
    return {
        "local_pending": local_count,
        "total_uploaded": face_vault.upload_count if face_vault else 0,
        "last_sync": face_vault.last_sync if face_vault else 0
    }

@router.post("/sync")
async def trigger_sync():
    from api.api_server import face_vault
    if face_vault:
        face_vault.sync_now()
        return {"status": "sync_triggered"}
    return {"error": "Vault offline"}
