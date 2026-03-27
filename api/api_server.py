import cv2
import time
import asyncio
import json
import logging
import threading
import queue
import os
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Core Imports are moved inside lifespan for degraded mode

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
    """
    Main loop: Pulls from CameraPool -> VisionPipeline -> Broadcasts Results.
    """
    global pipeline, cam_pool, vibe_engine, face_vault, face_registry, player
    
    app.state.latest_frames = {} 
    logger.info("Starting Vision Processing Loop...")
    
    while True:
        try:
            if not pipeline or not cam_pool:
                time.sleep(1)
                continue

            item = frame_queue.get(timeout=1.0) 
            cam_id = item["cam_id"]
            frame = item["frame"]
            
            # 1. Run Pipeline
            detections = pipeline.process_frame(frame, cam_id)
            
            # 2. Update Engine & Vault
            for det in detections:
                if vibe_engine: vibe_engine.log_detection(det['group'])
                
                # Check 95% rule for player
                if player:
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
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
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

# --- LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline, cam_pool, vibe_engine, face_vault, player, face_registry
    
    app.state.start_time = time.time()
    logger.info("Initializing Vibe Alchemist V2 Systems...")
    
    # Auto-create required directories
    music_dir = Path(os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback"))
    for group in ["kids", "youths", "adults", "seniors"]:
        (music_dir / group).mkdir(parents=True, exist_ok=True)
    Path(os.getenv("FACE_TEMP_DIR", "./temp_faces")).mkdir(exist_ok=True)
    logger.info(f"Storage ready: {music_dir.resolve()}")

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
        
        # Load vision models
        pipeline = VisionPipeline(
            models_dir=os.getenv("MODELS_DIR", "models"), 
            pool=None, # pool started after
            engine=vibe_engine, 
            vault=face_vault, 
            registry=face_registry
        )
        
        sources = os.getenv("CAMERA_SOURCES", "0").split(",")
        target_h = int(os.getenv("TARGET_HEIGHT", "720"))
        
        cam_pool = CameraPool(sources, frame_queue, target_height=target_h)
        pipeline.pool = cam_pool # Link pool back
        cam_pool.start()
        
        # Start background threads
        main_loop = asyncio.get_event_loop()
        threading.Thread(target=processing_loop, args=(main_loop,), daemon=True).start()
        asyncio.create_task(status_broadcaster())
        
        logger.info("[STARTUP] All core modules initialized.")
    except Exception as e:
        logger.error(f"[STARTUP ERROR] {e} — server running in degraded mode")

    yield

    # Shutdown
    logger.info("Shutting down systems...")
    if cam_pool: cam_pool.stop()
    if face_vault: face_vault.stop()
    if player: player.stop()
    logger.info("[SHUTDOWN] Clean exit.")

app = FastAPI(title="Vibe Alchemist V2 API", lifespan=lifespan)

# Add imports for StaticFiles
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

# --- UTILITIES ---
def api_response(success: bool = True, data: any = None, error: str = None):
    """Standardized API Response Wrapper."""
    return {
        "success": success,
        "data": data,
        "error": error
    }

# --- MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    path = request.url.path
    method = request.method

    # Direct print for debugging
    if not path.startswith(("/api/cameras/feed", "/assets")):
        print(f"➜ {method:4} | {path}")

    try:
        response = await call_next(request)
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        return StreamingResponse(
            iter([json.dumps(api_response(False, error=str(e))).encode()]),
            status_code=500,
            media_type="application/json"
        )

    process_time = (time.time() - start_time) * 1000
    status_code = response.status_code

    # ANSI Colors
    color = "\033[32m" # Green
    if status_code >= 400: color = "\033[31m" # Red
    elif status_code >= 300: color = "\033[33m" # Yellow
    reset = "\033[0m"

    # Don't log feed to keep console clean
    if not path.startswith("/api/cameras/feed"):
        logger.info(f"| {method:4} | {path:<30} | {color}{status_code}{reset} | {process_time:7.2f}ms")

    return response

# --- HEALTH CHECK ---
@app.get("/api/health")
async def health_check():
    """Automated System Connectivity Test."""
    status = {
        "engine": "online" if vibe_engine else "offline",
        "player": "online" if player else "offline",
        "cameras": len(cam_pool.workers) if cam_pool else 0,
        "uptime": time.time() - app.state.start_time if hasattr(app.state, 'start_time') else 0
    }
    return api_response(data=status)


# --- WEBSOCKET ENDPOINT ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    logger.info(f"\033[36m[WS]\033[0m Client connected from {websocket.client.host}")
    try:
        while True:
            if vibe_engine:
                state = vibe_engine.get_state()
                state["type"] = "vibe_update"
                await websocket.send_json(state)
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception) as e:
        logger.info(f"\033[36m[WS]\033[0m Client disconnected ({type(e).__name__})")
        manager.disconnect(websocket)

# --- MJPEG FEED ---
@app.get("/api/cameras/feed/{cam_id}")
async def video_feed(cam_id: int):
    def generate():
        while True:
            if hasattr(app.state, 'latest_frames'):
                frame_bytes = app.state.latest_frames.get(cam_id)
                if frame_bytes:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.1)
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace;boundary=frame")

# --- BROADCASTER ---
async def status_broadcaster():
    """1Hz System Status Broadcast."""
    while True:
        await asyncio.sleep(1)
        try:
            if vibe_engine and face_registry:
                # Offload blocking IPC to a thread to keep event loop fast
                player_status = {}
                if player:
                    try:
                        player_status = await asyncio.to_thread(player.get_status)
                    except Exception as e:
                        player_status = {"error": str(e)}
                
                await manager.broadcast({
                    "type": "status",
                    "player": player_status,
                    "vibe": vibe_engine.get_status(),
                    "vault": face_vault.get_status() if face_vault else {},
                    "faces": face_registry.get_summary() if face_registry else {}
                })
        except Exception as e:
            print(f"DEBUG BROADCASTER ERROR: {e}")

# Include Modular Routers
from api.routes import cameras, playback, vibe, faces
app.include_router(cameras.router, prefix="/api")
app.include_router(playback.router, prefix="/api")
app.include_router(vibe.router, prefix="/api")
app.include_router(faces.router, prefix="/api")

# --- STATIC FILE SERVING (After API Routes) ---
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(str(static_dir / "favicon.ico"))

# Serve index.html for ALL non-API, non-asset routes (React Router SPA fallback)
@app.get("/")
async def serve_root():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "Frontend not built. Run: npm run build"}

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # CRITICAL: Never intercept API, Feed, WS, or direct Asset paths
    # If it has a dot, it's likely a file that should have been caught by mount/other routes
    if full_path.startswith(("api/", "feed/", "ws", "assets/")) or "." in full_path:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "Frontend not built"}

