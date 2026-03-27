from fastapi import APIRouter, Response, Request
from fastapi.responses import StreamingResponse
import os
import logging

router = APIRouter(prefix="/cameras", tags=["cameras"])
logger = logging.getLogger("CamerasRoute")

@router.get("/")
async def list_cameras():
    # Attempt to use cam_pool if initialized, else fallback to .env
    import api.api_server as server
    
    sources = []
    if hasattr(server, 'cam_pool') and server.cam_pool is not None:
        # Robust check for different attribute names
        sources = getattr(server.cam_pool, 'sources', 
                  getattr(server.cam_pool, 'camera_sources',
                  getattr(server.cam_pool, '_sources', [])))
    
    if not sources:
        # Fallback to .env parsing
        env_sources = os.getenv("CAMERA_SOURCES", "0")
        sources = env_sources.split(",") if env_sources else ["0"]

    return [
        {
            "id": i, 
            "source": str(s), 
            "status": "online", 
            "name": f"Camera {i}",
            "feed_url": f"/api/cameras/feed/{i}"
        }
        for i, s in enumerate(sources)
    ]

@router.post("/{cam_id}/settings")
async def update_settings(cam_id: int, request: Request):
    body = await request.json()
    import api.api_server as server
    if hasattr(server, 'cam_pool') and server.cam_pool is not None:
        server.cam_pool.update_settings(cam_id, body)
        return {"status": "ok", "cam_id": cam_id, "settings": body}
    return {"status": "error", "message": "CameraPool not initialized"}
