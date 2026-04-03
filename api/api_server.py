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
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Non-blocking broadcast — slow clients don't block fast ones."""
        import asyncio
        with self._lock:
            connections = list(self.active_connections)

        # Send to each connection independently (no blocking)
        tasks = []
        for connection in connections:
            tasks.append(self._safe_send(connection, message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, connection, message):
        """Send to a single connection with timeout."""
        import asyncio
        try:
            await asyncio.wait_for(connection.send_json(message), timeout=1.0)
        except Exception:
            pass

manager = ConnectionManager()

# --- VISION PROCESSING LOOP ---
def processing_loop(loop):
    """
    Multi-camera processing loop with fair scheduling.

    Improvements:
    - Round-robin processing across all active cameras
    - Quality-based filtering (only process good detections)
    - Per-camera rate limiting with adaptive intervals
    - No race conditions with face registry (single-threaded)
    - Graceful handling of camera disconnects
    """
    global pipeline, cam_pool, vibe_engine, face_vault, face_registry, player
    faces_detected_count = 0
    last_music_change = time.time()

    # Per-camera rate limiting
    camera_last_process = {}
    base_process_interval = 0.5  # Process each camera every 500ms

    # Round-robin state
    current_camera_index = 0
    last_queue_check = time.time()

    while True:
        try:
            if not pipeline or not cam_pool:
                time.sleep(1)
                continue

            num_cameras = len(cam_pool.sources)
            if num_cameras == 0:
                time.sleep(1)
                continue

            # ── Process frames from queue first (newest frames) ──
            processed_from_queue = False
            try:
                # Drain queue but only process the latest frame per camera
                latest_per_cam = {}
                while not frame_queue.empty():
                    try:
                        item = frame_queue.get_nowait()
                        cam_id = item["cam_id"]
                        latest_per_cam[cam_id] = item  # Keep only latest
                    except queue.Empty:
                        break

                # Process latest frames with rate limiting
                current_time = time.time()
                for cam_id, item in latest_per_cam.items():
                    last_process = camera_last_process.get(cam_id, 0)
                    if current_time - last_process >= base_process_interval:
                        camera_last_process[cam_id] = current_time
                        detections = pipeline.process_frame(item["frame"], cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)
                        processed_from_queue = True

            except queue.Empty:
                pass

            # ── Round-robin fallback: process latest frames from each camera ──
            if not processed_from_queue:
                current_time = time.time()

                # Cycle through cameras in round-robin fashion
                current_camera_index = current_camera_index % num_cameras
                cam_id = current_camera_index
                current_camera_index += 1

                last_process = camera_last_process.get(cam_id, 0)
                if current_time - last_process >= base_process_interval:
                    frame = cam_pool.get_latest_frame(cam_id)
                    if frame is not None:
                        camera_last_process[cam_id] = current_time
                        detections = pipeline.process_frame(frame, cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)

            # Small sleep to prevent CPU spinning
            time.sleep(0.05)

        except Exception as e:
            logger.error(f"Processing loop error: {e}")
            time.sleep(1)

def process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry):
    """
    Process detections: log to vibe engine, trigger music, draw bounding boxes.

    Improvements:
    - Only log good-quality detections to vibe engine
    - Color-coded bounding boxes (green=good, yellow=low quality)
    - Shows confidence score on label
    - Detection counter shows total + good-quality count
    - 95% handover: prepares next vibe, continues current folder if no change
    """
    global last_music_change

    if not detections:
        return

    # Separate good and low-quality detections
    good_detections = [d for d in detections if d.get('is_good_quality', True)]
    low_quality = [d for d in detections if not d.get('is_good_quality', True)]

    # Only log good-quality detections to vibe engine (more reliable)
    for det in good_detections:
        if vibe_engine:
            quality = det.get('quality', 1.0)
            cam_id_val = det.get('cam_id', cam_id)
            vibe_engine.log_detection(
                det['group'],
                age=det['age'],
                quality=quality,
                cam_id=cam_id_val
            )

    # Log low-quality detections at debug level
    if low_quality:
        logger.debug(f"Cam {cam_id}: {len(low_quality)} low-quality detection(s) skipped for vibe")

    # ── Music Playback with 95% Handover ──
    if good_detections and player and vibe_engine:
        current_time = time.time()
        target_group = vibe_engine.get_current_group()
        current_status = player.get_status()
        current_group = current_status.get('group', 'adults')
        current_song = current_status.get('song', 'None')
        is_paused = current_status.get('paused', False)
        percent_pos = current_status.get('percent', 0)

        # ── 95% Handover: prepare next vibe ──
        if 92 <= percent_pos <= 96:
            vibe_engine.prepare_handover()

        # ── Song completion: commit handover and continue ──
        if current_song != 'None' and percent_pos < 5 and last_music_change > 0:
            # Song just finished (position reset to near 0)
            target = vibe_engine.commit_handover()
            if target != current_group:
                # Vibe changed — switch to new folder
                logger.info(f"Handover: Switching music {current_group} -> {target}")
                player.next(target)
            else:
                # Same vibe — continue playing from current folder
                logger.info(f"Handover: Continuing {target} folder")
                player.continue_current_folder()
            if is_paused:
                player.toggle_pause()
            last_music_change = current_time
            return  # Handled song transition, skip rest

        # ── Normal music selection ──
        should_change = (
            target_group != current_group or
            current_song == 'None' or
            (current_time - last_music_change > 15 and target_group == current_group)
        )

        if should_change and target_group != current_group:
            logger.info(f"Music: {target_group} (avg age: {vibe_engine.average_age})")
            player.next(target_group)
            if is_paused:
                player.toggle_pause()
            last_music_change = current_time
        elif current_song == 'None':
            logger.info(f"Music start: {target_group}")
            player.next(target_group)
            last_music_change = current_time
        elif is_paused and target_group == current_group:
            player.toggle_pause()

    # ── Draw Bounding Boxes ──
    frame = pipeline.pool.get_latest_frame(cam_id)
    if frame is None or not isinstance(frame, np.ndarray):
        return

    annotated_frame = frame.copy()
    h, w = annotated_frame.shape[:2]

    for det in detections:
        x1, y1, x2, y2 = det['bbox']
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        is_good = det.get('is_good_quality', True)
        quality = det.get('quality', 0)
        face_conf = det.get('face_conf', 0)

        # Color: green for good quality, yellow for low quality
        color = (0, 255, 0) if is_good else (0, 255, 255)  # BGR: green / yellow
        thickness = 3 if is_good else 2

        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, thickness)

        # Label with age, group, and confidence
        label = f"Age:{det['age']} {det['group']} ({quality:.1f})"
        (label_w, label_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)

        # Label background
        cv2.rectangle(
            annotated_frame,
            (x1, y1 - label_h - 8),
            (x1 + label_w + 6, y1),
            color, -1
        )

        # Text (white on colored background)
        cv2.putText(
            annotated_frame, label,
            (x1 + 3, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
        )

    # Detection counter badge
    total = len(detections)
    good_count = len(good_detections)
    if total > 0:
        counter_text = f"Faces: {good_count}/{total}"
        (cw, ch), cb = cv2.getTextSize(counter_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(
            annotated_frame,
            (w - cw - 20, 8),
            (w - 8, 8 + ch + 8),
            (0, 255, 0) if good_count == total else (0, 165, 255), -1
        )
        cv2.putText(
            annotated_frame, counter_text,
            (w - cw - 15, 8 + ch + 3),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
        )

    # Encode and store
    ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
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
    # Shutdown sequence - ONLY clean up temp_faces on termination
    logger.info("Shutting down Vibe Alchemist V2...")

    if cam_pool:
        cam_pool.stop_all()

    if player:
        player.stop()

    # Sync and cleanup faces on shutdown (ONLY when terminating)
    logger.info("Shutting down face vault and registry...")
    if face_vault:
        # Sync any pending faces to Drive before cleanup
        face_vault.sync_now()
        # Clean up temp_faces directory on termination
        face_vault.cleanup()

    if face_registry:
        face_registry.clear()

    # Final cleanup: ensure temp_faces is completely removed on termination
    import shutil
    temp_dir = Path(os.getenv("FACE_TEMP_DIR", "./temp_faces"))
    if temp_dir.exists():
        try:
            # Force delete all files
            for f in temp_dir.iterdir():
                if f.is_file():
                    f.unlink()
                    logger.info(f"Force deleted on termination: {f}")
            # Remove directory
            if not any(temp_dir.iterdir()):
                temp_dir.rmdir()
                logger.info("Removed temp_faces directory on termination")
        except Exception as e:
            logger.error(f"Final cleanup error: {e}")

    logger.info("Shutdown complete. temp_faces cleaned up on termination.")

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

# 4. MJPEG /feed/{cam_id} - Serves frames with bounding boxes
@app.get("/feed/{cam_id}")
async def camera_feed(cam_id: int):
    async def generate():
        last_frame = None
        while True:
            if cam_pool:
                frame_bytes = cam_pool.get_latest_frame(cam_id)
                if frame_bytes is not None:
                    if isinstance(frame_bytes, bytes):
                        last_frame = frame_bytes
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    elif isinstance(frame_bytes, np.ndarray):
                        _, buf = cv2.imencode('.jpg', frame_bytes, [
                            cv2.IMWRITE_JPEG_QUALITY, 75,
                            cv2.IMWRITE_JPEG_OPTIMIZE, 1,
                        ])
                        last_frame = buf.tobytes()
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + last_frame + b'\r\n')
            # Reduced sleep: 50ms = ~20 FPS for smoother display
            await asyncio.sleep(0.05)
    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace;boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

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
