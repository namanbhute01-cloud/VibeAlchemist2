from fastapi import APIRouter, Response, Request
import os
import logging
import json

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

@router.get("/config")
async def get_camera_config():
    """Returns the current camera sources configuration."""
    env_sources = os.getenv("CAMERA_SOURCES", "0")
    sources = [s.strip() for s in env_sources.split(",") if s.strip()]
    return {
        "sources": sources,
        "raw": env_sources
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
        
        # Update .env file
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        
        if not os.path.exists(env_path):
            return {"ok": False, "error": ".env file not found"}
        
        # Read existing .env
        with open(env_path, "r") as f:
            lines = f.readlines()
        
        # Find and update CAMERA_SOURCES line
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("CAMERA_SOURCES="):
                new_lines.append(f"CAMERA_SOURCES={sources_str}\n")
                updated = True
            else:
                new_lines.append(line)
        
        # If not found, add it
        if not updated:
            new_lines.append(f"CAMERA_SOURCES={sources_str}\n")
        
        # Write back
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        
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
