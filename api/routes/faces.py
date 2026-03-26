from fastapi import APIRouter
import logging

router = APIRouter(prefix="/faces", tags=["faces"])
logger = logging.getLogger("FacesRoute")

@router.get("/stats")
async def get_stats():
    import api.api_server as server
    if server.face_registry:
        return server.face_registry.get_summary()
    return {"total_unique": 0, "by_group": {}}

@router.get("/summary")
async def get_summary():
    import api.api_server as server
    if server.face_registry:
        return server.face_registry.get_summary()
    return {"total_unique": 0, "by_group": {}}

@router.get("/drive/status")
async def get_drive_status():
    import api.api_server as server
    if server.face_vault:
        return server.face_vault.get_status()
    return {"connected": False, "last_sync": None, "pending_count": 0}

@router.post("/sync")
async def sync_faces():
    import api.api_server as server
    if server.face_vault:
        server.face_vault.sync_now()
        return {"status": "ok"}
    return {"status": "error", "message": "FaceVault not initialized"}
