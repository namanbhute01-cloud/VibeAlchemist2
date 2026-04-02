import cv2
import numpy as np
import time
import asyncio
import json
import logging
import threading
import queue
import os
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from pathlib import Path

# Setup Logging & Env
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("APIServer")

# --- GLOBAL SINGLETONS ---
frame_queue = queue.Queue(maxsize=30)
pipeline = None
cam_pool = None
vibe_engine = None
face_vault = None
player = None
face_registry = None

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# --- VISION PROCESSING LOOP ---
def processing_loop(loop):
    global pipeline, cam_pool, vibe_engine, face_vault, face_registry, player
    faces_detected_count = 0
    last_music_change = time.time()

    # Track last processing time per camera to ensure fair processing
    camera_last_process = {}
    min_process_interval = 0.15  # Minimum 150ms between processing same camera (faster for better real-time)

    while True:
        try:
            if not pipeline or not cam_pool:
                time.sleep(1)
                continue

            # Get frame from queue with timeout
            try:
                item = frame_queue.get(timeout=0.5)
            except queue.Empty:
                # If queue is empty, try to process latest frames from each camera
                current_time = time.time()
                for cam_id in range(len(cam_pool.sources)):
                    # Check if enough time has passed since last processing
                    last_process = camera_last_process.get(cam_id, 0)
                    if current_time - last_process >= min_process_interval:
                        frame = cam_pool.get_latest_frame(cam_id)
                        if frame is not None:
                            detections = pipeline.process_frame(frame, cam_id)
                            process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                            camera_last_process[cam_id] = current_time
                            faces_detected_count += len(detections)
                continue

            cam_id = item["cam_id"]
            frame = item["frame"]

            # Check if we should process this camera or wait (rate limiting)
            current_time = time.time()
            last_process = camera_last_process.get(cam_id, 0)
            if current_time - last_process < min_process_interval:
                # Skip this frame, not enough time passed
                continue

            camera_last_process[cam_id] = current_time
            detections = pipeline.process_frame(frame, cam_id)
            process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
            faces_detected_count += len(detections)

        except Exception as e:
            logger.error(f"Loop Error: {e}")

def process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry):
    """Process detections from a single frame and draw bounding boxes."""
    global last_music_change

    for det in detections:
        # Log detection to vibe engine (includes age tracking)
        if vibe_engine:
            vibe_engine.log_detection(det['group'], age=det['age'])

    # If faces detected, trigger music playback based on detected age group
    if detections and player:
        current_time = time.time()
        # Get the current vibe group based on all detections
        target_group = vibe_engine.get_current_group() if vibe_engine else "adults"

        # Check if we need to change the music
        current_status = player.get_status()
        current_group = current_status.get('group', 'adults')
        current_song = current_status.get('song', 'None')
        is_paused = current_status.get('paused', False)

        # Play music from the detected group's folder
        # Change music if: different group, no song playing, or it's been 15 seconds
        should_change = (
            target_group != current_group or
            current_song == 'None' or
            (current_time - last_music_change > 15 and target_group == current_group)
        )

        if should_change and target_group != current_group:
            logger.info(f"Playing music for detected group: {target_group} (avg age: {vibe_engine.average_age if vibe_engine else 25})")
            player.next(target_group)
            # Ensure music is playing (not paused)
            if is_paused:
                player.toggle_pause()
            last_music_change = current_time
        elif current_song == 'None':
            # Start playing immediately if nothing is playing
            logger.info(f"Starting music for detected group: {target_group}")
            player.next(target_group)
            last_music_change = current_time
        elif is_paused and target_group == current_group:
            # If paused but same group, just resume playing
            logger.info(f"Resuming music for detected group: {target_group}")
            player.toggle_pause()

    # Draw bounding boxes on detected faces on the latest frame
    for det in detections:
        x1, y1, x2, y2 = det['bbox']
        # Get the latest frame for this camera
        frame = pipeline.pool.get_latest_frame(cam_id)
        if frame is not None and isinstance(frame, np.ndarray):
            # Draw rectangle around face (green box, 2px thick)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Add age/group label with background
            label = f"{det['age']} ({det['group']})"
            (label_w, label_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            
            # Draw label background
            cv2.rectangle(frame, (x1, y1 - label_h - baseline - 5), (x1 + label_w, y1), (0, 255, 0), -1)
            
            # Add text
            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

            # Encode and store frame for MJPEG stream
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ret:
                pipeline.pool.latest_frames[cam_id] = buffer.tobytes()

# --- LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline, cam_pool, vibe_engine, face_vault, player, face_registry
    logger.info("Initializing Vibe Alchemist V2 Systems...")
    app.state.start_time = time.time()
    
    music_dir = Path(os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback"))
    for group in ["kids", "youths", "adults", "seniors"]:
        (music_dir / group).mkdir(parents=True, exist_ok=True)
    Path(os.getenv("FACE_TEMP_DIR", "./temp_faces")).mkdir(exist_ok=True)

    try:
        from core.camera_pool import CameraPool
        from core.vision_pipeline import VisionPipeline
        from core.vibe_engine import VibeEngine
        from core.face_vault import FaceVault
        from core.alchemist_player import AlchemistPlayer
        from core.face_registry import FaceRegistry

        vibe_engine = VibeEngine()
        player = AlchemistPlayer(music_root=str(music_dir))
        face_registry = FaceRegistry()
        face_vault = FaceVault(temp_dir=os.getenv("FACE_TEMP_DIR", "temp_faces"))
        pipeline = VisionPipeline(models_dir=os.getenv("MODELS_DIR", "models"), pool=None, engine=vibe_engine, vault=face_vault, registry=face_registry)
        
        cam_pool = CameraPool(target_height=int(os.getenv("TARGET_HEIGHT", "720")), frame_queue=frame_queue)
        pipeline.pool = cam_pool
        cam_pool.start()

        threading.Thread(target=processing_loop, args=(asyncio.get_event_loop(),), daemon=True).start()
        logger.info("[STARTUP] All core modules initialized.")
        
        # Set global references for API routes
        cameras.set_cam_pool(cam_pool)
        playback.set_refs(player, vibe_engine)
        vibe.set_refs(vibe_engine, player, cam_pool, face_registry)
        faces.set_refs(face_registry, face_vault)
    except Exception as e:
        logger.error(f"[STARTUP ERROR] {e}")

    yield
    # Shutdown sequence
    logger.info("Shutting down Vibe Alchemist V2...")
    
    if cam_pool: 
        cam_pool.stop_all()
    
    if player: 
        player.stop()
    
    # Sync and cleanup faces on shutdown
    if face_vault:
        # Optional: sync to Drive before cleanup (if credentials configured)
        # face_vault.shutdown_push()
        # Clean up temp_faces directory
        face_vault.cleanup()
    
    if face_registry:
        face_registry.clear()
    
    logger.info("Shutdown complete. temp_faces cleaned up.")

# --- APP INIT ---
app = FastAPI(title="Vibe Alchemist V2", lifespan=lifespan)

# 1. CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://127.0.0.1:8000", "http://localhost:5173", "http://localhost:8000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. API Routers
from api.routes import cameras, playback, vibe, faces, settings

app.include_router(cameras.router, prefix="/api")
app.include_router(playback.router, prefix="/api")
app.include_router(vibe.router, prefix="/api")
app.include_router(faces.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

# 3. WebSocket /ws and /ws/vibe-stream
@app.websocket("/ws")
@app.websocket("/ws/vibe-stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            if vibe_engine:
                # Fetch counts for real-time StatCards
                cam_count = len(cam_pool.sources) if cam_pool else 0
                face_count = face_registry.get_summary().get('total_unique', 0) if face_registry else 0
                saved_count = face_registry.get_saved_count() if face_registry else 0

                state = vibe_engine.get_state(
                    player=player,
                    camera_count=cam_count,
                    face_count=face_count
                )
                # Override with actual saved faces count for UI
                state['unique_faces'] = saved_count
                state['active_cameras'] = cam_count
                await websocket.send_json(state)
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception):
        pass

# 4. MJPEG /feed/{cam_id}
@app.get("/feed/{cam_id}")
async def camera_feed(cam_id: int):
    def generate():
        while True:
            if cam_pool:
                frame_bytes = cam_pool.get_latest_frame(cam_id)
                if frame_bytes is not None:
                    # If it's a numpy array, encode it. If it's bytes (already encoded), use directly.
                    if isinstance(frame_bytes, bytes):
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    else:
                        _, buf = cv2.imencode('.jpg', frame_bytes, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
            time.sleep(0.1)
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace;boundary=frame")

# 5. Static Files & SPA Catch-all
static_dir = Path(__file__).parent.parent / "static"

# Mount static files at root level for production
if static_dir.exists():
    logger.info(f"[STATIC] Serving static files from: {static_dir}")
    # Mount assets directory for JS/CSS bundles
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets"), html=True), name="assets")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Skip core system endpoints
    skip = ("api/", "feed/", "ws", "docs", "openapi")
    if any(full_path.startswith(s) for s in skip):
        raise HTTPException(status_code=404)

    # Serve index.html for root path
    index_file = static_dir / "index.html"
    if full_path == "" or full_path == "/":
        if index_file.exists():
            logger.info(f"[STATIC] Serving index.html")
            return FileResponse(index_file)
    
    # Check if a specific static file exists (e.g., favicon.ico, placeholder.svg)
    target_file = static_dir / full_path
    if target_file.is_file():
        logger.debug(f"[STATIC] Serving file: {target_file}")
        return FileResponse(target_file)

    # Serve index.html for SPA routes (React Router)
    if index_file.exists():
        logger.debug(f"[STATIC] Serving index.html for route: {full_path}")
        return FileResponse(index_file)

    logger.warning(f"[STATIC] File not found: {full_path}")
    return {"error": "Frontend not built", "path": full_path}
