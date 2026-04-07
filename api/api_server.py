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
adaptive_pipeline = None  # V5 adaptive pipeline
adaptive_vibe = None      # V5 adaptive vibe controller

# --- MUSIC HANDOVER MONITOR (Background Thread) ---
# Runs independently of face detection — ensures zero-gap song transitions.
# Monitors song position continuously, pre-loads next song before current ends.

def music_handover_loop():
    """
    Background thread that monitors song playback position.

    FIXED LOGIC:
    1. On startup: Wait for face detections, then start first song
    2. While song plays: Collect ALL face detections in vibe_engine.journal
    3. At song end (percent drops OR player clears current_song):
       a. Calculate average age from all detections collected during this song
       b. Determine target group from that average age
       c. Start ONE new song from that group
    4. NEVER start overlapping songs — only one song plays at a time
    5. If no faces detected yet: use default 'adults' group after 30s timeout
    """
    global vibe_engine, player

    has_played_once = False  # Prevent auto-start on boot
    last_monitored_song = None
    last_percent = 0
    song_ending = False  # True when we've decided to end and are waiting for clean state
    end_attempted_time = 0
    startup_time = time.time()
    last_face_check_time = time.time()
    faces_detected_at_start = 0

    logger.info("Music handover monitor started (waits for faces before playing)")

    while True:
        try:
            if not player or not vibe_engine:
                time.sleep(1)
                continue

            status = player.get_status()
            current_song = status.get('song', 'None')
            percent_pos = status.get('percent', 0)

            # ── CASE 1: No song playing ──
            if current_song == 'None':
                # Start a song if:
                # a) We've played before AND a song just ended (percent was high)
                # b) OR it's first boot AND we have face detections (or timeout reached)
                should_start = False
                target_group = "adults"  # Default

                if has_played_once:
                    # Song just ended — calculate vibe from detections during this song
                    if last_percent > 50 or song_ending:
                        song_ending = False
                        target_group = _calculate_target_group()
                        logger.info(f"Song ended. Detections during song -> target: {target_group}")
                        should_start = True
                    else:
                        # No song and we're not ending one — idle
                        time.sleep(1)
                        continue
                else:
                    # First boot — wait for face detections before starting
                    # Check if we have any face detections in the journal
                    current_faces = vibe_engine.journal if hasattr(vibe_engine, 'journal') else []
                    current_face_count = len(current_faces) if current_faces else 0
                    
                    # Also check quality_journal
                    if hasattr(vibe_engine, 'quality_journal'):
                        current_face_count = len(vibe_engine.quality_journal)

                    time_since_startup = time.time() - startup_time
                    
                    # Start if we have faces OR timeout reached (30 seconds)
                    if current_face_count > 0:
                        target_group = _calculate_target_group()
                        logger.info(f"First boot: {current_face_count} face(s) detected -> target: {target_group}")
                        should_start = True
                    elif time_since_startup > 30:
                        # Timeout — start with default after 30 seconds
                        logger.info(f"First boot timeout (30s). No faces detected -> target: adults (default)")
                        target_group = "adults"
                        should_start = True
                    else:
                        # Still waiting for faces
                        time.sleep(1)
                        continue

                # Start the song
                if should_start:
                    with _playback_lock:
                        try:
                            success = player.next(target_group)
                            if success:
                                time.sleep(0.5)
                                verify = player.get_status()
                                if verify.get('percent', 0) > 0:
                                    has_played_once = True
                                    last_monitored_song = verify.get('song', 'None')
                                    last_percent = 0
                                    logger.info(f"Next song started: {target_group}")
                                    continue
                                else:
                                    logger.warning(f"next() succeeded but percent=0, retrying in 3s")
                                    time.sleep(3)
                                    continue
                        except Exception as e:
                            logger.warning(f"Failed to start next song: {e}")
                            time.sleep(2)
                            continue

            # ── CASE 2: Song is playing — monitor for end ──
            # Detect new song started (by user or by our handover)
            if current_song != last_monitored_song:
                last_monitored_song = current_song
                last_percent = 0
                song_ending = False
                has_played_once = True  # Mark that we've played at least once
                logger.info(f"Now playing: {current_song}")

            # Detect song ending: percent dropped from high to low
            if last_percent > 85 and percent_pos < 10 and not song_ending:
                song_ending = True
                logger.info(f"Song ending (was at {last_percent:.0f}%)")

            # Detect song stuck at 99%+ for 5+ seconds
            if percent_pos >= 99 and not song_ending:
                if not hasattr(music_handover_loop, '_stuck_start'):
                    music_handover_loop._stuck_start = time.time()
                elif time.time() - music_handover_loop._stuck_start >= 5:
                    song_ending = True
                    logger.info(f"Song stuck at {percent_pos:.0f}% for 5s — ending")
                    music_handover_loop._stuck_start = None
            else:
                music_handover_loop._stuck_start = None

            # ── CASE 3: Song ended naturally (player cleared it) ──
            # This is caught by CASE 1 on next iteration when current_song == 'None'

            last_percent = percent_pos

            # Poll every 200ms
            time.sleep(0.2)

        except Exception as e:
            logger.error(f"Music handover error: {e}")
            time.sleep(1)


def _calculate_target_group() -> str:
    """
    Calculate the target music group from all face detections collected
    during the current song. Uses vibe_engine's journal and average_age.
    """
    avg_age = vibe_engine.average_age

    if avg_age and avg_age > 0:
        logger.info(f"Average age during song: {avg_age:.1f}")
    else:
        logger.info("No faces detected during song — using default 'adults'")
        return "adults"

    # Map average age to group with fuzzy boundaries
    if avg_age < 14:
        return "kids"
    elif avg_age < 22:
        return "youths"
    elif avg_age < 55:
        return "adults"
    else:
        return "seniors"


# --- VISION PROCESSING LOOP ---
def processing_loop():
    """
    Multi-camera processing loop with fair scheduling.

    CRITICAL FIX: Process ALL cameras every cycle, not just one!
    - Process frames from queue (all cameras)
    - Fall back to latest_frames for ALL active cameras
    - Per-camera rate limiting with adaptive intervals
    - No race conditions with face registry (single-threaded)
    - Graceful handling of camera disconnects
    """
    global pipeline, cam_pool, vibe_engine, face_vault, face_registry, player
    faces_detected_count = 0

    # Per-camera rate limiting
    camera_last_process = {}
    base_process_interval = 0.5  # Process each camera every 500ms

    while True:
        try:
            if not pipeline or not cam_pool:
                time.sleep(1)
                continue

            num_cameras = len(cam_pool.sources)
            if num_cameras == 0:
                time.sleep(1)
                continue

            current_time = time.time()
            processed_any = False

            # ── STEP 1: Process frames from queue (newest frames per camera) ──
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

                # Process latest frames from ALL cameras in queue
                for cam_id, item in latest_per_cam.items():
                    last_process = camera_last_process.get(cam_id, 0)
                    if current_time - last_process >= base_process_interval:
                        camera_last_process[cam_id] = current_time
                        detections = pipeline.process_frame(item["frame"], cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)
                        processed_any = True

            except queue.Empty:
                pass

            # ── STEP 2: Process ALL cameras from latest_frames (fallback) ──
            # Process EVERY camera that has a frame available
            for cam_id in range(num_cameras):
                last_process = camera_last_process.get(cam_id, 0)
                if current_time - last_process >= base_process_interval:
                    # Get raw frame only (numpy array) — NOT annotated bytes
                    frame = cam_pool.latest_frames.get(cam_id)
                    if frame is not None and isinstance(frame, np.ndarray):
                        camera_last_process[cam_id] = current_time
                        detections = pipeline.process_frame(frame, cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)
                        processed_any = True

            # Small sleep to prevent CPU spinning
            time.sleep(0.05)

        except Exception as e:
            logger.error(f"Processing loop error: {e}")
            time.sleep(1)

# Global lock to prevent race condition between handover loop and detection loop
# when starting/switching songs
_playback_lock = threading.Lock()


def _log_detections(detections, vibe_engine, cam_id):
    """Log ALL detections to vibe engine (including low-quality, but weighted)."""
    for det in detections:
        if vibe_engine:
            # Pass quality to vibe_engine — it weights detections by quality
            # Low-quality detections still count, just with less weight
            vibe_engine.log_detection(
                det['group'],
                age=det['age'],
                quality=det.get('quality', 0.3),  # Low-quality gets 0.3 default
                cam_id=det.get('cam_id', cam_id)
            )

    return detections


def _handle_playback(detections, vibe_engine, player):
    """
    Resume playback when detections occur — ONLY resume, never start new songs.
    Song transitions are handled by music_handover_loop (prevents race conditions).
    """
    if not detections or not player or not vibe_engine:
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

        # Encode and store in annotated_frames (thread-safe)
        ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ret:
            with pipeline.pool._frame_lock:
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
    global adaptive_pipeline, adaptive_vibe
    logger.info("Initializing Vibe Alchemist V5 Systems...")
    app.state.start_time = time.time()

    music_dir = Path(os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback"))
    for group in ["kids", "youths", "adults", "seniors", "default"]:
        (music_dir / group).mkdir(parents=True, exist_ok=True)
    Path(os.getenv("FACE_TEMP_DIR", "./temp_faces")).mkdir(exist_ok=True)

    try:
        from core.camera_pool import CameraPool
        from core.vision_pipeline import VisionPipeline
        from core.vibe_engine import VibeEngine
        from core.face_vault import FaceVault
        from core.alchemist_player import AlchemistPlayer
        from core.face_registry import FaceRegistry

        # V5: Import adaptive modules
        from core.capability_detector import PROFILE
        from core.adaptive_pipeline import AdaptivePipeline
        from core.adaptive_vibe_controller import AdaptiveVibeController

        vibe_engine = VibeEngine()
        player = AlchemistPlayer(music_root=str(music_dir))
        face_registry = FaceRegistry()
        face_vault = FaceVault(temp_dir=os.getenv("FACE_TEMP_DIR", "temp_faces"))
        pipeline = VisionPipeline(models_dir=os.getenv("MODELS_DIR", "models"), pool=None, engine=vibe_engine, vault=face_vault, registry=face_registry)

        # V5: Initialize adaptive pipeline
        adaptive_pipeline = AdaptivePipeline()
        logger.info(f"V5 AdaptivePipeline: Tier {PROFILE.tier} ({PROFILE.summary()['tier_name']})")
        logger.info(f"V5 AdaptiveVibeController: fuzzy={'ON' if PROFILE.tier >= 2 else 'OFF'}")

        cam_pool = CameraPool(
            target_height=int(os.getenv("TARGET_HEIGHT", "720")),
            frame_queue=frame_queue
        )
        
        # Verify cameras were loaded
        if len(cam_pool.sources) == 0:
            logger.error("NO CAMERA SOURCES CONFIGURED! Check CAMERA_SOURCES in .env")
        else:
            logger.info(f"CameraPool configured with {len(cam_pool.sources)} source(s): {cam_pool.sources}")
        
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
    # Validate camera ID
    if cam_pool and cam_id >= len(cam_pool.sources):
        raise HTTPException(status_code=404, detail=f"Camera {cam_id} not found")

    loop = asyncio.get_event_loop()
    executor = None  # default ThreadPoolExecutor

    async def generate():
        while True:
            try:
                if cam_pool:
                    # Get annotated frame (JPEG bytes with bounding boxes) or raw frame
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
                                [cv2.IMWRITE_JPEG_QUALITY, 85, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
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

# 4d. V5 System tier info endpoint
@app.get("/api/system/tier")
async def system_tier_info():
    """Returns hardware profile and adaptive tier information."""
    if adaptive_pipeline:
        return {
            "ok": True,
            **adaptive_pipeline.get_tier_info()
        }
    # Fallback: return basic profile info
    from core.capability_detector import PROFILE
    return {
        "ok": True,
        **PROFILE.summary(),
        "note": "AdaptivePipeline not initialized"
    }

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
