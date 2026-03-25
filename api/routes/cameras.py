from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
import time
import os

router = APIRouter(prefix="/cameras", tags=["cameras"])

# Accessing global state via app.state is cleaner in modular routes
# But for now we'll assume the MJPEG generator can access the buffers

@router.get("/")
async def list_cameras():
    sources = os.getenv("CAMERA_SOURCES", "0").split(",")
    return {"count": len(sources), "sources": sources}

@router.get("/feed/{cam_id}")
async def video_feed(cam_id: int):
    """Note: This route is usually handled in the main app to access state easily,
    but we can define the logic here and mount it."""
    from api.api_server import generate_mjpeg
    return StreamingResponse(generate_mjpeg(cam_id), media_type="multipart/x-mixed-replace;boundary=frame")

@router.post("/{cam_id}/settings")
async def update_settings(cam_id: int, settings: dict):
    # Placeholder for Phase 5 hardware tuning
    return {"status": "ok", "cam_id": cam_id, "settings": settings}
