from fastapi import APIRouter, Response, Request
import os
import logging

router = APIRouter(prefix="/cameras", tags=["cameras"])
logger = logging.getLogger("CamerasRoute")

@router.get("")
@router.get("/")
async def list_cameras():
    """Returns flat list of cameras as per contract."""
    from api import api_server as server

    cam_pool = getattr(server, 'cam_pool', None)
    sources = []

    if cam_pool is not None:
        sources = getattr(cam_pool, 'sources', [])

    if not sources:
        # Fallback to .env parsing
        env_sources = os.getenv("CAMERA_SOURCES", "0")
        sources = [s.strip() for s in env_sources.split(",") if s.strip()]

    return [
        {
            "id": i,
            "source": str(s),
            "status": "online",
            "name": f"Camera {i}",
            "feed_url": f"/feed/{i}"
        }
        for i, s in enumerate(sources)
    ]

@router.post("/{cam_id}/settings")
async def update_settings(cam_id: int, request: Request):
    """Updates camera settings."""
    from api import api_server as server
    cam_pool = getattr(server, 'cam_pool', None)

    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Invalid JSON body"}

    if cam_pool is not None:
        cam_pool.update_settings(cam_id, body)
        return {"ok": True}

    return {"ok": False, "error": "CameraPool not initialized"}
