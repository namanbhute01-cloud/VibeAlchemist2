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

# --- MUSIC HANDOVER MONITOR (Background Thread) ---
# Runs independently of face detection — ensures zero-gap song transitions.
# Monitors song position continuously, pre-loads next song before current ends.

def music_handover_loop():
    """
    Background thread that monitors song playback position.
    - At 90%+: collects age samples continuously
    - At 92%: prepares handover (locks in next vibe)
    - At song end (percent drops from high to low): immediately queues next song
    - If vibe changed: switches folder; if same: continues current folder
    - Runs every 100ms for instant response
    """
    global vibe_engine, player

    last_monitored_song = None
    handover_age_samples = []
    handover_prepared = False
    last_percent = 0
    song_ended = False

    logger.info("Music handover monitor started")

    while True:
        try:
            if not player or not vibe_engine:
                time.sleep(1)
                continue

            status = player.get_status()
            current_song = status.get('song', 'None')
            percent_pos = status.get('percent', 0)
            current_group = status.get('group', 'adults')

            # ── Detect new song started ──
            if current_song != last_monitored_song and current_song != 'None':
                last_monitored_song = current_song
                handover_age_samples = []
                handover_prepared = False
                last_percent = 0
                song_ended = False
                logger.debug(f"New song: {current_song}")

            if current_song == 'None':
                # No song playing — start music
                target_group = vibe_engine.get_current_group()
                started = False
                with _playback_lock:
                    try:
                        success = player.next(target_group)
                        if success:
                            time.sleep(0.8)
                            verify = player.get_status()
                            if verify.get('percent', 0) > 0:
                                started = True
                                logger.info(f"Music started: {target_group}")
                            else:
                                logger.warning(f"next() succeeded but percent=0")
                        else:
                            logger.error(f"player.next() returned False — playback failed")
                    except Exception as e:
                        logger.warning(f"Failed to start music: {e}")

                if not started:
                    time.sleep(3)  # Longer wait before retry
                else:
                    time.sleep(1)
                last_monitored_song = None  # Force re-detect
                continue

            # ── Detect song ended (percent dropped from high to low) ──
            # This catches the case where MPV jumps from 91% → 100% → 0%
            if last_percent > 85 and percent_pos < 10 and not song_ended:
                song_ended = True
                logger.info(f"Song ended at {last_percent:.0f}% — triggering handover")

                # Collect final age sample
                avg_age = vibe_engine.average_age
                if avg_age and avg_age > 0:
                    handover_age_samples.append(avg_age)

                # Prepare if not already done
                if not handover_prepared:
                    vibe_engine.prepare_handover()
                    handover_prepared = True

                # Commit and queue next song
                target_group = vibe_engine.commit_handover()

                with _playback_lock:
                    try:
                        if target_group != current_group:
                            logger.info(f"HANDOVER: {current_group} -> {target_group}")
                            success = player.next(target_group)
                        else:
                            logger.info(f"HANDOVER: Continuing {current_group}")
                            success = player.continue_current_folder()

                        if not success:
                            logger.error(f"Handover: player returned False — will retry")
                            last_monitored_song = None
                            song_ended = False
                            continue

                        # Verify playback actually started
                        time.sleep(0.5)
                        verify = player.get_status()
                        if verify.get('percent', 0) < 1:
                            logger.warning(f"Handover: music not playing after handover — retrying")
                            last_monitored_song = None
                            song_ended = False
                            continue
                    except Exception as e:
                        logger.error(f"Song handover failed: {e}")
                        last_monitored_song = None
                        song_ended = False
                        continue

                # Reset for next song
                handover_age_samples = []
                handover_prepared = False
                last_monitored_song = None  # Force re-detect
                last_percent = 0
                time.sleep(0.5)  # Let new song start
                continue

            # ── 90%+ window: collect age samples ──
            if percent_pos >= 90:
                avg_age = vibe_engine.average_age
                if avg_age and avg_age > 0:
                    handover_age_samples.append(avg_age)

                # Prepare handover at 92%
                if not handover_prepared and percent_pos >= 92:
                    handover_prepared = True
                    vibe_engine.prepare_handover()
                    logger.info(f"Handover prepared at {percent_pos:.0f}% ({len(handover_age_samples)} samples)")

            last_percent = percent_pos

            # Poll every 100ms for instant response
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Music handover error: {e}")
            time.sleep(1)


# --- VISION PROCESSING LOOP ---
def processing_loop():
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

    # Per-camera rate limiting
    camera_last_process = {}
    base_process_interval = 0.5  # Process each camera every 500ms

    # Round-robin state
    current_camera_index = 0

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

                last_process = camera_last_process.get(cam_id, 0)
                if current_time - last_process >= base_process_interval:
                    frame = cam_pool.get_latest_frame(cam_id)
                    if frame is not None:
                        camera_last_process[cam_id] = current_time
                        detections = pipeline.process_frame(frame, cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)
                        # Only advance to next camera when we actually process one
                        current_camera_index += 1
                else:
                    # Rate limit active — advance to next camera for next iteration
                    current_camera_index += 1

            # Small sleep to prevent CPU spinning
            time.sleep(0.05)

        except Exception as e:
            logger.error(f"Processing loop error: {e}")
            time.sleep(1)

# Global lock to prevent race condition between handover loop and detection loop
# when starting/switching songs
_playback_lock = threading.Lock()


def _log_detections(detections, vibe_engine, cam_id):
    """Log good-quality detections to vibe engine; skip low-quality ones."""
    good = [d for d in detections if d.get('is_good_quality', True)]
    low_quality = [d for d in detections if not d.get('is_good_quality', True)]

    for det in good:
        if vibe_engine:
            vibe_engine.log_detection(
                det['group'],
                age=det['age'],
                quality=det.get('quality', 1.0),
                cam_id=det.get('cam_id', cam_id)
            )

    if low_quality:
        logger.debug(f"Cam {cam_id}: {len(low_quality)} low-quality detection(s) skipped for vibe")

    return good


def _handle_playback(good_detections, vibe_engine, player):
    """
    Resume playback when detections occur — ONLY resume, never start new songs.
    Song transitions are handled by music_handover_loop (prevents race conditions).
    """
    if not good_detections or not player or not vibe_engine:
        return

    with _playback_lock:
        try:
            current_status = player.get_status()
            current_song = current_status.get('song', 'None')
            is_paused = current_status.get('paused', True)

            # ONLY resume if paused — don't start new songs (music_handover_loop does that)
            if current_song != 'None' and is_paused:
                player.toggle_pause()
                logger.info("Resuming playback on detection")
        except Exception as e:
            logger.warning(f"_handle_playback error (non-fatal): {e}")


def _draw_bounding_boxes(detections, cam_id, pipeline):
    """Draw annotated bounding boxes on the latest frame and store in annotated_frames dict."""
    try:
        # Get raw frame from camera pool
        raw_frame = pipeline.pool.latest_frames.get(cam_id)
        if raw_frame is None or not isinstance(raw_frame, np.ndarray):
            return

        annotated_frame = raw_frame.copy()
        h, w = annotated_frame.shape[:2]
        good_count = sum(1 for d in detections if d.get('is_good_quality', True))

        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            is_good = det.get('is_good_quality', True)
            quality = det.get('quality', 0)

            color = (0, 255, 0) if is_good else (0, 255, 255)
            thickness = 3 if is_good else 2

            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, thickness)

            label = f"Age:{det['age']} {det['group']} ({quality:.1f})"
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)

            cv2.rectangle(
                annotated_frame,
                (x1, y1 - label_h - 8),
                (x1 + label_w + 6, y1),
                color, -1
            )

            cv2.putText(
                annotated_frame, label,
                (x1 + 3, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
            )

        # Detection counter badge
        total = len(detections)
        if total > 0:
            counter_text = f"Faces: {good_count}/{total}"
            (cw, ch), _ = cv2.getTextSize(counter_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
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

        # Encode and store in annotated_frames (separate from raw camera frames)
        ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ret:
            pipeline.pool.annotated_frames[cam_id] = buffer.tobytes()
    except Exception as e:
        logger.warning(f"_draw_bounding_boxes error (non-fatal): {e}")


def process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry):
    """
    Process detections: delegate to specialized sub-functions.
    Music handover (song transitions) is handled by music_handover_loop() thread.
    All operations wrapped in try/except to prevent server crashes.
    """
    if not detections:
        return

    try:
        good_detections = _log_detections(detections, vibe_engine, cam_id)
        _handle_playback(good_detections, vibe_engine, player)
        _draw_bounding_boxes(detections, cam_id, pipeline)
    except Exception as e:
        logger.error(f"process_detections error (non-fatal): {e}")

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

        # Start vision processing loop (no loop argument needed — processing_loop doesn't use it)
        threading.Thread(target=processing_loop, daemon=True).start()

        # Start music handover monitor (independent of face detection — zero-gap transitions)
        threading.Thread(target=music_handover_loop, daemon=True).start()

        logger.info("[STARTUP] All core modules initialized.")
        
        # Set global references for API routes
        cameras.set_cam_pool(cam_pool)
        playback.set_refs(player, vibe_engine)
        vibe.set_refs(vibe_engine, player, cam_pool, face_registry)
        faces.set_refs(face_registry, face_vault)
    except Exception as e:
        logger.error(f"[STARTUP ERROR] Failed to initialize: {e}", exc_info=True)
        logger.error("[STARTUP ERROR] Server will start in degraded mode — check configuration")
        # Set safe defaults so routes don't crash
        cameras.set_cam_pool(None)
        playback.set_refs(None, None)
        vibe.set_refs(None, None, None, None)
        faces.set_refs(None, None)

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
# Configurable origins via CORS_ORIGINS env var (comma-separated)
# Defaults to localhost variants for development
cors_origins = os.getenv("CORS_ORIGINS", "")
allowed_origins = [o.strip() for o in cors_origins.split(",") if o.strip()] if cors_origins else [
    "http://127.0.0.1:5173", "http://127.0.0.1:8000",
    "http://localhost:5173", "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1b. Optional API Key Authentication
# If API_KEY env var is set, all endpoints (except /health, /docs, /feed) require it
API_KEY = os.getenv("API_KEY", "")

if API_KEY:
    from fastapi import Request
    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        # Skip auth for health, docs, and camera feeds
        skip_paths = ("/health", "/docs", "/openapi.json", "/feed/", "/ws", "/assets/", "/favicon.ico", "/placeholder.svg", "/robots.txt")
        if any(request.url.path.startswith(p) for p in skip_paths):
            return await call_next(request)

        # Check API key in header or query param
        provided_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not provided_key or provided_key != API_KEY:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        return await call_next(request)

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
    last_state_time = 0
    min_interval = 1.0  # Send state at most once per second (prevents flickering)

    try:
        while True:
            try:
                now = time.time()
                if now - last_state_time >= min_interval:
                    # Send state — throttled to prevent UI flickering
                    if vibe_engine:
                        cam_count = len(cam_pool.sources) if cam_pool else 0
                        face_count = face_registry.get_summary().get('total_unique', 0) if face_registry else 0
                        saved_count = face_registry.get_saved_count() if face_registry else 0

                        state = vibe_engine.get_state(
                            player=player,
                            camera_count=cam_count,
                            face_count=face_count
                        )
                        state['unique_faces'] = saved_count
                        state['active_cameras'] = cam_count
                    else:
                        state = {
                            "status": "initializing",
                            "detected_group": "None",
                            "current_vibe": "None",
                            "age": "...",
                            "average_age": 0,
                            "journal_count": 0,
                            "percent_pos": 0,
                            "is_playing": False,
                            "paused": True,
                            "shuffle": True,
                            "current_song": "",
                            "next_vibe": None,
                            "active_cameras": 0,
                            "unique_faces": 0,
                        }
                    await websocket.send_json(state)
                    last_state_time = now

                # Heartbeat — keeps connection alive without triggering re-renders
                await asyncio.sleep(0.5)
            except Exception:
                # Connection lost — exit loop, client will reconnect
                break
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)

# 4. MJPEG /feed/{cam_id} - Serves frames with bounding boxes
@app.get("/feed/{cam_id}")
async def camera_feed(cam_id: int):
    loop = asyncio.get_event_loop()
    executor = None  # default ThreadPoolExecutor

    async def generate():
        while True:
            try:
                if cam_pool:
                    # Priority: annotated frame (with bounding boxes) > raw frame
                    frame_data = cam_pool.get_latest_frame(cam_id)
                    if frame_data is not None:
                        if isinstance(frame_data, bytes):
                            # Already encoded (annotated frame with bounding boxes)
                            if len(frame_data) > 100:
                                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
                        elif isinstance(frame_data, np.ndarray):
                            # Raw frame from camera — encode in thread pool
                            _, buf = await loop.run_in_executor(
                                executor,
                                cv2.imencode, '.jpg', frame_data,
                                [cv2.IMWRITE_JPEG_QUALITY, 70, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
                            )
                            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                await asyncio.sleep(0.033)
            except Exception:
                # Client disconnected — exit generator gracefully
                return

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace;boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

# 4b. Health check endpoint (lightweight — no camera dependency)
@app.get("/health")
async def health():
    """Lightweight health check — always returns 200 if server is alive."""
    uptime = time.time() - app.state.start_time if hasattr(app.state, 'start_time') else 0
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime": round(uptime, 1),
        "pipeline_ready": pipeline is not None,
    }

# 4c. Camera status endpoint
@app.get("/api/cameras/status")
async def camera_status():
    """Returns connection status of all cameras."""
    if cam_pool:
        return {
            "ok": True,
            "cameras": cam_pool.get_status() if hasattr(cam_pool, 'get_status') else [
                {"id": i, "source": str(s), "connected": True}
                for i, s in enumerate(cam_pool.sources)
            ]
        }
    return {"ok": False, "cameras": []}

# 5. Static Files & SPA Catch-all
static_dir = Path(__file__).parent.parent / "static"

if static_dir.exists():
    logger.info(f"[STATIC] Serving static files from: {static_dir}")

    @app.get("/assets/{filename:path}")
    async def serve_assets(filename: str):
        """Serve JS/CSS assets with correct MIME types and cache headers."""
        file_path = static_dir / "assets" / filename
        if file_path.is_file():
            media_type = "text/javascript" if filename.endswith(".js") else "text/css" if filename.endswith(".css") else "application/octet-stream"
            # Hashed filenames can be cached aggressively (1 year)
            headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            return FileResponse(file_path, media_type=media_type, headers=headers)
        raise HTTPException(status_code=404)

    @app.get("/")
    async def serve_root():
        """Serve index.html for root path — no caching."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
            return FileResponse(index_file, headers=headers)
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve SPA routes — skip API, feeds, WS, and assets."""
        skip = ("api/", "feed/", "ws", "docs", "openapi", "assets/")
        if any(full_path.startswith(s) for s in skip):
            raise HTTPException(status_code=404)

        # Check if a specific static file exists (favicon.ico, placeholder.svg, etc.)
        target_file = static_dir / full_path
        if target_file.is_file():
            return FileResponse(target_file)

        # Serve index.html for SPA routes (React Router)
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        raise HTTPException(status_code=404)
else:
    @app.get("/")
    async def serve_root():
        return {"error": "Frontend not built. Run: cd frontend && npm run build"}
