from fastapi import APIRouter, Response, Request
import os
import logging
import json
from core import env_manager

router = APIRouter(prefix="/cameras", tags=["cameras"])
logger = logging.getLogger("CamerasRoute")

# Global reference to cam_pool - set by api_server during startup
cam_pool_ref = {"pool": None}

def set_cam_pool(pool):
    """Set the camera pool reference (called by api_server during startup)."""
    cam_pool_ref["pool"] = pool

@router.get("")
async def list_cameras():
    """Returns flat list of cameras as per contract."""
    cam_pool = cam_pool_ref.get("pool")
    sources = []

    if cam_pool is not None:
        sources = getattr(cam_pool, 'sources', [])
        logger.debug(f"Cameras from pool: {sources}")

    if not sources:
        # Fallback to .env parsing via env_manager
        settings = env_manager.load_all_settings()
        sources_str = settings.get("CAMERA_SOURCES", "0")
        sources = [s.strip() for s in str(sources_str).split(",") if s.strip()]
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

@router.get("/config")
async def get_camera_config():
    """Returns the current camera sources configuration."""
    settings = env_manager.load_all_settings()
    sources_str = settings.get("CAMERA_SOURCES", "0")
    sources = [s.strip() for s in str(sources_str).split(",") if s.strip()]
    return {
        "sources": sources,
        "raw": sources_str
    }

@router.post("/config")
async def save_camera_config(request: Request):
    """Saves new camera sources configuration to .env file."""
    try:
        body = await request.json()
        sources = body.get("sources", [])

        if not isinstance(sources, list):
            return {"ok": False, "error": "Sources must be a list"}

        # Convert list to comma-separated string
        sources_str = ",".join(str(s).strip() for s in sources if str(s).strip())

        if not sources_str:
            return {"ok": False, "error": "At least one camera source is required"}

        # Update .env file using env_manager
        success, error = env_manager.update_setting("CAMERA_SOURCES", sources_str)
        
        if not success:
            return {"ok": False, "error": error}

        logger.info(f"Camera sources updated: {sources_str}")

        # Update camera pool if available
        cam_pool = cam_pool_ref.get("pool")
        if cam_pool:
            # Parse new sources
            new_sources = []
            for s in sources_str.split(","):
                s = s.strip()
                if not s:
                    continue
                if s.isdigit():
                    new_sources.append(int(s))
                else:
                    new_sources.append(s)
            cam_pool.sources = new_sources
            logger.info(f"Camera pool updated with {len(new_sources)} sources")

        return {"ok": True, "sources": sources}

    except Exception as e:
        logger.error(f"Error saving camera config: {e}")
        return {"ok": False, "error": str(e)}

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
