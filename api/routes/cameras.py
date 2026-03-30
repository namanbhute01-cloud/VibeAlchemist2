from fastapi import APIRouter, Response, Request
import os
import logging

router = APIRouter(prefix="/cameras", tags=["cameras"])
logger = logging.getLogger("CamerasRoute")

# Global reference to cam_pool - set by api_server during startup
cam_pool_ref = {"pool": None}

def set_cam_pool(pool):
    """Set the camera pool reference (called by api_server during startup)."""
    cam_pool_ref["pool"] = pool

@router.get("")
@router.get("/")
async def list_cameras():
    """Returns flat list of cameras as per contract."""
    cam_pool = cam_pool_ref.get("pool")
    sources = []

    if cam_pool is not None:
        sources = getattr(cam_pool, 'sources', [])
        logger.debug(f"Cameras from pool: {sources}")

    if not sources:
        # Fallback to .env parsing
        env_sources = os.getenv("CAMERA_SOURCES", "0")
        sources = [s.strip() for s in env_sources.split(",") if s.strip()]
        logger.debug(f"Cameras from env: {sources}")

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
    cam_pool = cam_pool_ref.get("pool")

    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Invalid JSON body"}

    if cam_pool is not None:
        cam_pool.update_settings(cam_id, body)
        return {"ok": True}

    return {"ok": False, "error": "CameraPool not initialized"}
