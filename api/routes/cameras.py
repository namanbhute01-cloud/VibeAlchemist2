from fastapi import APIRouter, Response, Request
from fastapi.responses import StreamingResponse
import os
import logging

router = APIRouter(prefix="/cameras", tags=["cameras"])
logger = logging.getLogger("CamerasRoute")

@router.get("/")
async def list_cameras():
    # Attempt to use cam_pool if initialized, else fallback to .env
    from api.api_server import cam_pool, api_response
    
    sources = []
    if cam_pool is not None:
        sources = getattr(cam_pool, 'sources', 
                  getattr(cam_pool, 'camera_sources',
                  getattr(cam_pool, '_sources', [])))
    
    if not sources:
        # Fallback to .env parsing
        env_sources = os.getenv("CAMERA_SOURCES", "0")
        sources = env_sources.split(",") if env_sources else ["0"]

    data = [
        {
            "id": i, 
            "source": str(s), 
            "status": "online", 
            "name": f"Camera {i}",
            "feed_url": f"/api/cameras/feed/{i}"
        }
        for i, s in enumerate(sources)
    ]
    return api_response(data=data)

@router.post("/{cam_id}/settings")
async def update_settings(cam_id: int, request: Request):
    from api.api_server import cam_pool, api_response
    body = await request.json()
    if cam_pool is not None:
        cam_pool.update_settings(cam_id, body)
        return api_response(data={"cam_id": cam_id, "settings": body})
    return api_response(success=False, error="CameraPool not initialized")
