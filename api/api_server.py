import cv2
import time
import asyncio
import json
import logging
import threading
import queue
import os
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

# Core Imports
from core.camera_pool import CameraPool
from core.vision_pipeline import VisionPipeline
from core.vibe_engine import VibeEngine
from core.face_vault import FaceVault
from core.alchemist_player import AlchemistPlayer

# Routes
from api.routes import cameras, playback, vibe, faces

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

# --- FASTAPI APP ---
app = FastAPI(title="Vibe Alchemist V2 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Modular Routers
app.include_router(cameras.router, prefix="/api")
app.include_router(playback.router, prefix="/api")
app.include_router(vibe.router, prefix="/api")
app.include_router(faces.router, prefix="/api")

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
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
    """
    Main loop: Pulls from CameraPool -> VisionPipeline -> Broadcasts Results.
    """
    global pipeline, cam_pool, vibe_engine, face_vault
    
    app.state.latest_frames = {} 
    logger.info("Starting Vision Processing Loop...")
    
    while True:
        try:
            item = frame_queue.get(timeout=1.0) 
            cam_id = item["cam_id"]
            frame = item["frame"]
            
            # 1. Run Pipeline
            detections = pipeline.process_frame(frame, cam_id)
            
            # 2. Update Engine & Vault
            for det in detections:
                vibe_engine.log_detection(det['group'])
                
                # Check 95% rule for player
                status = player.get_status()
                if status.get("percent", 0) > 95:
                    vibe_engine.prepare_handover()

            # 3. Draw Debug Info (for MJPEG)
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{det['group']} {det['age']}", (x1, y1-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # 4. Encode MJPEG Buffer
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                app.state.latest_frames[cam_id] = buffer.tobytes()

            # 5. Broadcast Detection to Main Loop
            if detections:
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({
                        "type": "detection",
                        "cam_id": cam_id,
                        "data": detections
                    }), 
                    loop
                )

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Loop Error: {e}")

# --- MJPEG GENERATOR ---
def generate_mjpeg(cam_id):
    while True:
        if hasattr(app.state, 'latest_frames'):
            frame_bytes = app.state.latest_frames.get(cam_id)
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.1) # ~20 FPS

# --- LIFECYCLE EVENTS ---
@app.on_event("startup")
async def startup_event():
    global pipeline, cam_pool, vibe_engine, face_vault, player
    
    logger.info("Initializing Vibe Alchemist V2 Systems...")
    
    pipeline = VisionPipeline(models_dir="models")
    vibe_engine = VibeEngine()
    face_vault = FaceVault()
    player = AlchemistPlayer()
    
    sources = os.getenv("CAMERA_SOURCES", "0").split(",")
    cam_pool = CameraPool(sources, frame_queue)
    cam_pool.start()
    
    # Pass the current event loop to the processing thread
    main_loop = asyncio.get_event_loop()
    threading.Thread(target=processing_loop, args=(main_loop,), daemon=True).start()
    asyncio.create_task(status_broadcaster())

@app.on_event("shutdown")
async def shutdown_event():
    if cam_pool: cam_pool.stop()
    if face_vault: face_vault.stop()
    if player: player.stop()

async def status_broadcaster():
    """1Hz System Status Broadcast."""
    while True:
        await asyncio.sleep(1)
        if player and vibe_engine:
            await manager.broadcast({
                "type": "status",
                "player": player.get_status(),
                "vibe": vibe_engine.get_status(),
                "vault": {"last_sync": face_vault.last_sync, "uploads": face_vault.upload_count}
            })

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
