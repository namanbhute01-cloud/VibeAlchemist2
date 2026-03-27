from fastapi import APIRouter
import logging

router = APIRouter(prefix="/faces", tags=["faces"])
logger = logging.getLogger("FacesRoute")

@router.get("/stats")
async def get_stats():
    from api.api_server import face_registry, api_response
    if face_registry:
        return api_response(data=face_registry.get_summary())
    return api_response(data={"total_unique": 0, "by_group": {}})

@router.get("/summary")
async def get_summary():
    from api.api_server import face_registry, api_response
    if face_registry:
        return api_response(data=face_registry.get_summary())
    return api_response(data={"total_unique": 0, "by_group": {}})

@router.get("/drive/status")
async def get_drive_status():
    from api.api_server import face_vault, api_response
    if face_vault:
        return api_response(data=face_vault.get_status())
    return api_response(data={"connected": False, "last_sync": None, "pending_count": 0})

@router.post("/sync")
async def sync_faces():
    from api.api_server import face_vault, api_response
    if face_vault:
        face_vault.sync_now()
        return api_response(data={"status": "sync_started"})
    return api_response(success=False, error="FaceVault not initialized")
