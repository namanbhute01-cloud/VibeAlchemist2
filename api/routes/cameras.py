from fastapi import APIRouter, Response, Request
from fastapi.responses import StreamingResponse
import os

router = APIRouter(prefix="/cameras", tags=["cameras"])

@router.get("/")
async def list_cameras():
    # Attempt to use cam_pool if initialized, else fallback to .env
    import api.api_server as server
    if server.cam_pool:
        sources = server.cam_pool.sources
    else:
        sources = os.getenv("CAMERA_SOURCES", "0").split(",")
    
    return [
        {"id": i, "source": str(s), "status": "online", "name": f"Camera {i+1}"}
        for i, s in enumerate(sources)
    ]

@router.post("/{cam_id}/settings")
async def update_settings(cam_id: int, request: Request):
    body = await request.json()
    import api.api_server as server
    if server.cam_pool:
        server.cam_pool.update_settings(cam_id, body)
        return {"status": "ok", "cam_id": cam_id, "settings": body}
    return {"status": "error", "message": "CameraPool not initialized"}
