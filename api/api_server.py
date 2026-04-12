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

# Stuck song detection state (module-level variable)
_stuck_song_start = None

# --- MUSIC HANDOVER MONITOR (Background Thread) ---
# Runs independently of face detection — ensures zero-gap song transitions.
# Monitors song position continuously, pre-loads next song before current ends.

def music_handover_loop():
    """
    Background thread that monitors song playback position.

    FIXED LOGIC:
    1. On startup: WAIT for face detections — do NOT start music without faces
    2. While song plays: Collect ALL face detections in a per-song buffer
    3. At song end (percent drops OR player clears current_song):
       a. Calculate target group from detections collected during THIS song only
       b. Use prepare_handover() + commit_handover() from vibe_engine
       c. Start ONE new song from the determined group
    4. NEVER start overlapping songs — only one song plays at a time
    5. If no faces detected during song: continue current folder (no random switching)
    6. NEVER auto-start without face detections — wait indefinitely
    """
    global vibe_engine, player

    has_played_once = False
    last_monitored_song = None
    last_percent = 0
    song_ending = False

    # ── Per-song detection tracking ──
    startup_time = time.time()
    song_detections = []  # List of (group, age, quality, timestamp) for CURRENT song
    song_start_time = time.time()

    logger.info("Music handover monitor started (per-song detection tracking)")
    logger.info("WAITING for face detections before starting first song...")

    while True:
        try:
            if not player or not vibe_engine:
                time.sleep(1)
                continue

            status = player.get_status()
            current_song = status.get('song', 'None')
            percent_pos = status.get('percent', 0)
            is_stopped = getattr(player, 'is_stopped', False)

            # ── CASE 0: User manually stopped the music ──
            # Do NOT auto-restart — wait for user to start again
            if is_stopped:
                time.sleep(1)
                continue

            # ── CASE 1: No song playing ──
            if current_song == 'None':
                should_start = False
                target_group = None

                if has_played_once:
                    # Song just ended — decide what to play next
                    target_group = _calculate_target_group_from_song(song_detections)
                    current_folder = getattr(player, 'current_folder', 'adults')
                    
                    # FIX: Only switch folders if a DIFFERENT age group is detected
                    # Otherwise, continue playing from the current folder
                    if target_group == current_folder:
                        logger.info(
                            f"Song ended. Same age group detected ({target_group}). "
                            f"Continuing from current folder: {current_folder}"
                        )
                        target_group = current_folder
                    else:
                        logger.info(
                            f"Song ended. Age group changed: {current_folder} -> {target_group}. "
                            f"Switching folders."
                        )
                    
                    song_detections = []  # Reset for next song
                    song_start_time = time.time()
                    should_start = True
                else:
                    # First boot — WAIT for face detections before starting
                    # NEVER start music without detecting faces first
                    current_face_count = 0
                    if hasattr(vibe_engine, 'quality_journal'):
                        current_face_count = len(vibe_engine.quality_journal)

                    time_since_startup = time.time() - startup_time

                    if current_face_count > 0:
                        target_group = _calculate_target_group_from_song(
                            list(vibe_engine.quality_journal)
                        )
                        logger.info(f"First boot: {current_face_count} face(s) detected -> target: {target_group}")
                        should_start = True
                    else:
                        # Log progress every 15 seconds
                        if int(time_since_startup) % 15 == 0 and int(time_since_startup) > 0:
                            logger.info(f"Waiting for face detections... ({int(time_since_startup)}s elapsed, no faces yet)")
                        time.sleep(1)
                        continue

                # Start the song
                if should_start and target_group:
                    try:
                        success = player.next(target_group)
                        if success:
                            time.sleep(0.5)
                            verify = player.get_status()
                            if verify.get('percent', 0) > 0:
                                has_played_once = True
                                last_monitored_song = verify.get('song', 'None')
                                last_percent = 0
                                # ── Commit handover to vibe_engine ──
                                if vibe_engine:
                                    vibe_engine.commit_handover()
                                logger.info(f"Next song started: {target_group}")
                                continue
                            else:
                                logger.warning(f"next() succeeded but percent=0, retrying in 3s")
                                time.sleep(3)
                                continue
                        else:
                            logger.warning(f"player.next() returned False, retrying in 2s")
                            time.sleep(2)
                            continue
                    except Exception as e:
                        logger.warning(f"Failed to start next song: {e}")
                        time.sleep(2)
                        continue

            # ── CASE 2: Song is playing — monitor for end ──
            if current_song != last_monitored_song:
                last_monitored_song = current_song
                last_percent = 0
                song_ending = False
                has_played_once = True
                # FIX: Reset per-song detection buffer IMMEDIATELY when new song starts
                # This must happen BEFORE _collect_song_detections is called
                song_detections = []
                song_start_time = time.time()
                logger.info(f"Now playing: {current_song} (detection buffer reset)")

            # Collect detections from vibe_engine for this song
            _collect_song_detections(song_detections, song_start_time)

            # Detect song ending: percent dropped from high to low
            if last_percent > 85 and percent_pos < 10 and not song_ending:
                song_ending = True
                logger.info(f"Song ending (was at {last_percent:.0f}%)")

            # Detect song stuck at 99%+ for 5+ seconds
            # FIX: Use module-level variable instead of fragile function attribute
            global _stuck_song_start
            if percent_pos >= 99 and not song_ending:
                if _stuck_song_start is None:
                    _stuck_song_start = time.time()
                elif time.time() - _stuck_song_start >= 5:
                    song_ending = True
                    logger.info(f"Song stuck at {percent_pos:.0f}% for 5s — ending")
                    _stuck_song_start = None
            else:
                _stuck_song_start = None

            last_percent = percent_pos
            time.sleep(0.2)

        except Exception as e:
            import traceback
            logger.error(f"Music handover error: {e}")
            logger.error(f"Handover traceback: {traceback.format_exc()}")
            # Don't sleep too long — keep monitoring
            time.sleep(0.5)


def _collect_song_detections(song_detections, song_start_time):
    """
    Collect new detections from vibe_engine's quality_journal since song started.
    Appends to song_detections list (mutable, passed by reference).
    
    FIX: Use set for O(1) duplicate checking instead of O(N^2) list scan.
    FIX: Take snapshot of quality_journal to avoid concurrent modification.
    """
    if not vibe_engine or not hasattr(vibe_engine, 'quality_journal'):
        return

    # Build set of existing entry IDs for O(1) lookups
    existing_ids = set()
    for d in song_detections:
        entry_id = (d.get('group'), d.get('cam_id'), d.get('timestamp', 0))
        existing_ids.add(entry_id)

    # Take snapshot of quality_journal to avoid concurrent modification
    journal_snapshot = list(vibe_engine.quality_journal)
    
    # Get entries from quality_journal that occurred after song started
    for entry in journal_snapshot:
        ts = entry.get('timestamp', 0)
        if ts > song_start_time:
            # Check if we already have this entry (avoid duplicates)
            entry_id = (entry.get('group'), entry.get('cam_id'), ts)
            if entry_id not in existing_ids:
                song_detections.append(entry)
                existing_ids.add(entry_id)


def _calculate_target_group_from_song(song_detections) -> str:
    """
    Calculate the target music group from detections collected during the current song.
    Uses quality-weighted voting. Falls back to vibe_engine's prepare_handover().
    
    FIX: Added minimum dominance threshold to prevent marginal vote differences
    from triggering unwanted folder switches.
    """
    # Filter out old entries (before song start)
    valid_detections = [d for d in song_detections if isinstance(d, dict) and 'group' in d]

    if not valid_detections:
        # No detections during this song — use vibe_engine's handover logic
        logger.info("No face detections during song — using vibe_engine handover")
        if vibe_engine:
            return vibe_engine.prepare_handover()
        return "adults"

    # Quality-weighted voting
    quality_votes = {}
    total_quality = 0.0

    for entry in valid_detections:
        group = entry.get('group', 'adults')
        quality = entry.get('quality', 0.5)
        weight = max(0.1, min(1.0, quality))

        quality_votes[group] = quality_votes.get(group, 0) + weight
        total_quality += weight

    if not quality_votes:
        return "adults"

    # Get the winning group
    winner = max(quality_votes, key=quality_votes.get)
    winner_quality = quality_votes[winner]
    dominance_ratio = winner_quality / total_quality if total_quality > 0 else 0

    # FIX: Minimum dominance threshold — winner needs >50% of total quality
    # This prevents marginal differences from triggering folder switches
    if dominance_ratio < 0.5:
        # No clear winner — fallback to vibe_engine's current vibe
        logger.info(
            f"No clear winner (dominance: {dominance_ratio:.2f} < 0.50). "
            f"Using vibe_engine's current group."
        )
        if vibe_engine:
            return vibe_engine.get_current_group()
        return "adults"

    # Log the voting breakdown
    vote_summary = ", ".join(f"{g}: {q:.1f}" for g, q in sorted(quality_votes.items(), key=lambda x: -x[1]))
    logger.info(
        f"Song detection vote: {winner} wins ({vote_summary}) | "
        f"{len(valid_detections)} detections, dominance: {dominance_ratio:.2f}"
    )

    return winner


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
    - Explicit memory management (prevent frame accumulation leaks)
    """
    global pipeline, cam_pool, vibe_engine, face_vault, face_registry, player
    faces_detected_count = 0
    log_counter = 0
    frames_processed = 0
    last_gc_check = time.time()
    last_frame_processed_time = time.time()  # Watchdog: track when we last processed a frame

    # Per-camera rate limiting
    camera_last_process = {}
    base_process_interval = 0.5  # Process each camera every 500ms

    logger.info("Vision processing loop started")

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

            # ── Watchdog: Detect if processing loop is stuck ──
            # If no frames processed in 30 seconds but cameras are connected, something is wrong
            time_since_last_frame = current_time - last_frame_processed_time
            if time_since_last_frame > 30 and processed_any is False:
                # Check if cameras are actually connected
                connected_cams = sum(1 for w in cam_pool.workers if w.connected)
                if connected_cams > 0:
                    logger.warning(
                        f"⚠️ WATCHDOG: Processing loop appears stuck! "
                        f"No frames processed for {time_since_last_frame:.0f}s "
                        f"({connected_cams} cameras connected). Forcing frame check."
                    )
                    # Force check: clear and re-read latest_frames
                    for cam_id in range(num_cameras):
                        frame = cam_pool.latest_frames.get(cam_id)
                        if frame is not None and isinstance(frame, np.ndarray):
                            logger.info(f"Watchdog: Found stale frame for cam {cam_id}, processing now")
                            local_frame = frame.copy()
                            detections = pipeline.process_frame(local_frame, cam_id)
                            process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                            frames_processed += len(detections)
                            last_frame_processed_time = current_time
                            del local_frame
                            processed_any = True

            # ── STEP 1: Process frames from queue (newest frames per camera) ──
            try:
                # Drain queue but only process the latest frame per camera
                latest_per_cam = {}
                while not frame_queue.empty():
                    try:
                        item = frame_queue.get_nowait()
                        cam_id = item["cam_id"]
                        # If we already have a newer frame, discard the old one
                        if cam_id in latest_per_cam:
                            # Explicitly delete old frame reference to free memory
                            del latest_per_cam[cam_id]["frame"]
                        latest_per_cam[cam_id] = item  # Keep only latest
                    except queue.Empty:
                        break

                # Process latest frames from ALL cameras in queue
                for cam_id, item in latest_per_cam.items():
                    last_process = camera_last_process.get(cam_id, 0)
                    if current_time - last_process >= base_process_interval:
                        camera_last_process[cam_id] = current_time
                        frame = item["frame"]
                        detections = pipeline.process_frame(frame, cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)
                        frames_processed += 1
                        last_frame_processed_time = current_time  # Watchdog heartbeat
                        processed_any = True
                        # Explicitly release frame reference after processing
                        del frame
                        del item

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
                        # Make a local copy so the shared dict can be updated independently
                        local_frame = frame.copy()
                        detections = pipeline.process_frame(local_frame, cam_id)
                        process_detections(detections, cam_id, pipeline, vibe_engine, player, face_vault, face_registry)
                        faces_detected_count += len(detections)
                        frames_processed += 1
                        last_frame_processed_time = current_time  # Watchdog heartbeat
                        processed_any = True
                        # Explicitly release local frame reference
                        del local_frame

            # ── Memory Management: Periodic garbage collection ──
            # Run GC every 60 seconds to clean up accumulated numpy frames
            if current_time - last_gc_check > 60:
                import gc
                collected = gc.collect()
                last_gc_check = current_time
                if collected > 100:
                    logger.debug(f"GC collected {collected} objects (memory cleanup)")

            # ── Clean up stale annotated frames (older than 5 seconds) ──
            if cam_pool and hasattr(cam_pool, 'annotated_frames'):
                stale_threshold = current_time - 5.0
                stale_keys = [
                    k for k, v in cam_pool.annotated_frames.items()
                    if k not in cam_pool.latest_frames  # Clean up cameras that disconnected
                ]
                for k in stale_keys:
                    del cam_pool.annotated_frames[k]

            # Periodic status logging every ~30 cycles
            log_counter += 1
            if log_counter % 600 == 0:  # ~30 seconds at 0.05s sleep
                # Check camera health
                cam_health = []
                for w in cam_pool.workers:
                    status = "connected" if w.connected else "DISCONNECTED"
                    frame_age = f"last frame {time.time() - w.last_good_frame_time:.0f}s ago" if w.last_good_frame_time > 0 else "no frames yet"
                    cam_health.append(f"Cam {w.cam_id}: {status} ({frame_age})")

                logger.info(
                    f"Processing loop: {num_cameras} camera(s), "
                    f"{frames_processed} frames in last 30s ({frames_processed/30:.1f} fps), "
                    f"total faces: {faces_detected_count}, "
                    f"quality_journal: {len(vibe_engine.quality_journal) if vibe_engine else 0} | "
                    f"{' | '.join(cam_health)}"
                )
                faces_detected_count = 0  # Reset counter
                frames_processed = 0

            # Small sleep to prevent CPU spinning
            time.sleep(0.05)

        except Exception as e:
            logger.error(f"Processing loop error: {e}", exc_info=True)
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
    
    FIX: Removed _playback_lock to prevent nested lock deadlock risk.
    Player methods are already thread-safe with internal _lock.
    """
    if not detections or not player or not vibe_engine:
        return

    try:
        # Get status (thread-safe via player._lock internally)
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
            thickness = 2

            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, thickness)

            label = f"{det['age']} {det['group']}"
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)

            cv2.rectangle(
                annotated_frame,
                (x1, y1 - label_h - 4),
                (x1 + label_w + 4, y1),
                color, -1
            )

            cv2.putText(
                annotated_frame, label,
                (x1 + 2, y1 - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1
            )

        # Detection counter badge
        total = len(detections)
        if total > 0:
            counter_text = f"Faces: {total}"
            (cw, ch), _ = cv2.getTextSize(counter_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(
                annotated_frame,
                (w - cw - 16, 6),
                (w - 6, 6 + ch + 6),
                (0, 255, 0) if good_count == total else (0, 165, 255), -1
            )
            cv2.putText(
                annotated_frame, counter_text,
                (w - cw - 12, 6 + ch + 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
            )

        # Encode and store in annotated_frames (thread-safe, lower quality for speed)
        ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 75, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
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
        logger.debug(f"Processing {len(detections)} detection(s) from cam {cam_id}: "
                     f"groups={[d['group'] for d in detections]}, ages=[d['age'] for d in detections]")
        good_detections = _log_detections(detections, vibe_engine, cam_id)
        _handle_playback(good_detections, vibe_engine, player)
        _draw_bounding_boxes(detections, cam_id, pipeline)
    except Exception as e:
        logger.error(f"process_detections error (non-fatal): {e}", exc_info=True)

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

# 4. MJPEG /feed/{cam_id} - Serves frames with bounding boxes (low latency)
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
                            # Raw frame from camera — encode in thread pool (non-blocking)
                            _, buf = await loop.run_in_executor(
                                executor,
                                cv2.imencode, '.jpg', frame_data,
                                [cv2.IMWRITE_JPEG_QUALITY, 70, cv2.IMWRITE_JPEG_OPTIMIZE, 1, cv2.IMWRITE_JPEG_PROGRESSIVE, 0]
                            )
                            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                # 30fps target (33ms)
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
            "X-Frame-Rate": "30",
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
