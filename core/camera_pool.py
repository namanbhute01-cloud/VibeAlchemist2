import cv2
import threading
import time
import logging
import queue
import os
from typing import List, Union
import numpy as np

logger = logging.getLogger("CameraPool")


class CameraWorker(threading.Thread):
    """
    Worker thread for a single camera source.
    Lightweight: just capture, resize, and push.
    Enhancement is done ONCE in vision_pipeline (not here).

    Improvements:
    - RTSP stream health monitoring (detects stale streams)
    - Forced reconnection after N seconds without a good frame
    - Frame timestamp tracking for lag detection
    - Periodic connection health logging
    """

    def __init__(self, source: Union[int, str], cam_id: int, frame_queue: queue.Queue, pool, target_height=720):
        super().__init__(daemon=True)
        self.source = source
        self.cam_id = cam_id
        self.queue = frame_queue
        self.pool = pool
        self.target_height = target_height
        self.running = False
        self.cap = None
        self.connected = False
        self.frame_count = 0
        self.last_log = time.time()

        # ── RTSP Health Monitoring ──
        self.last_good_frame_time = 0.0  # Timestamp of last successfully read frame
        self.stale_stream_threshold = 15.0  # Seconds without a frame = stream is dead
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 50  # Unlimited retries (reset on success)

    def _connect(self):
        """Connect to camera source with optimized settings."""
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.connected = False

        self.reconnect_attempts += 1
        logger.info(f"[Cam {self.cam_id}] Connecting (attempt {self.reconnect_attempts}): {self.source}")

        if isinstance(self.source, str):
            # HTTP/RTSP stream — optimize for low latency
            # CRITICAL: Use FFMPEG backend for network streams with aggressive timeout settings
            cap = None
            # Try FFMPEG backend first with explicit buffer and timeout options
            try:
                cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    # CRITICAL: Set FFMPEG-specific options to prevent buffering
                    # These must be set AFTER opening the stream
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Only keep latest frame
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                    # FFMPEG-specific: reduce internal buffer
                    cap.set(cv2.CAP_PROP_FPS, 15)  # Cap at 15fps to prevent backlog
            except Exception:
                logger.debug(f"[Cam {self.cam_id}] CAP_FFMPEG unavailable, using default backend")
                cap = None

            # Fallback to default backend
            if cap is None or not cap.isOpened():
                if cap:
                    cap.release()
                cap = cv2.VideoCapture(self.source)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            self.cap = cap
        else:
            # USB webcam
            self.cap = cv2.VideoCapture(self.source)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        if self.cap and self.cap.isOpened():
            self.connected = True
            self.last_good_frame_time = time.time()
            logger.info(f"[Cam {self.cam_id}] Connected successfully")
        else:
            self.connected = False
            logger.error(f"[Cam {self.cam_id}] Failed to open")

    def run(self):
        self.running = True
        self._connect()

        reconnect_delay = 2  # Start with 2s
        max_delay = 10
        last_stale_check = time.time()

        while self.running:
            # ── Stale Stream Detection (for network streams) ──
            # If we haven't received a good frame in N seconds, force reconnect
            if self.connected and isinstance(self.source, str):
                time_since_frame = time.time() - self.last_good_frame_time
                if time_since_frame > self.stale_stream_threshold:
                    logger.warning(
                        f"[Cam {self.cam_id}] STALE STREAM DETECTED: "
                        f"No frames for {time_since_frame:.0f}s — forcing reconnect"
                    )
                    self.cap.release()
                    self.connected = False
                    reconnect_delay = 2  # Reset delay on forced reconnect
                    continue

                # Periodic health check log (every 60s)
                now = time.time()
                if now - last_stale_check > 60:
                    logger.debug(
                        f"[Cam {self.cam_id}] Health: OK (last frame {time_since_frame:.1f}s ago, "
                        f"reconnects: {self.reconnect_attempts})"
                    )
                    last_stale_check = now

            if not self.cap or not self.cap.isOpened():
                logger.warning(f"[Cam {self.cam_id}] Reconnecting in {reconnect_delay}s...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, max_delay)
                self._connect()
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                logger.warning(f"[Cam {self.cam_id}] Read failed, reconnecting...")
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.connected = False
                time.sleep(1)
                continue

            # ── Frame received — update health tracking ──
            self.last_good_frame_time = time.time()
            self.reconnect_attempts = 0  # Reset on success
            reconnect_delay = 2  # Reset delay

            try:
                # ── Lightweight resize only (no enhancement) ──
                h, w = frame.shape[:2]
                if h > self.target_height:
                    scale = self.target_height / h
                    frame = cv2.resize(frame, (int(w * scale), self.target_height),
                                       interpolation=cv2.INTER_LINEAR)

                # Store latest frame for MJPEG feed (thread-safe)
                with self.pool._frame_lock:
                    self.pool.latest_frames[self.cam_id] = frame.copy()

                # Push to processing queue (drop oldest if full)
                if self.queue.full():
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        pass

                self.queue.put({
                    "cam_id": self.cam_id,
                    "frame": frame,
                    "timestamp": time.time()
                })

                self.frame_count += 1

                # Log FPS every 10 seconds
                now = time.time()
                if now - self.last_log > 10:
                    fps = self.frame_count / (now - self.last_log)
                    logger.info(f"[Cam {self.cam_id}] {fps:.1f} FPS (connected: {self.connected})")
                    self.frame_count = 0
                    self.last_log = now

                # Adaptive sleep based on FRAME_RATE_LIMIT env var
                frame_rate_limit = int(os.getenv("FRAME_RATE_LIMIT", "15"))
                if frame_rate_limit > 0:
                    time.sleep(1.0 / frame_rate_limit)

            except Exception as e:
                logger.error(f"[Cam {self.cam_id}] Error: {e}")
                time.sleep(1)

        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        logger.info(f"[Cam {self.cam_id}] Stopped")

    def stop(self):
        self.running = False


class CameraPool:
    """Manager for multiple CameraWorker threads."""

    def __init__(self, sources: List[Union[int, str]] = None, frame_queue: queue.Queue = None, target_height=720):
        if sources is None:
            raw = os.getenv("CAMERA_SOURCES", "0")
            sources_list = []
            for s in raw.split(","):
                s = s.strip()
                if not s:
                    continue
                if s.isdigit():
                    sources_list.append(int(s))
                else:
                    sources_list.append(s)
            self.sources = sources_list
        else:
            self.sources = sources

        self.queue = frame_queue
        self.target_height = target_height
        self.workers = []
        self.latest_frames = {}       # Raw frames from camera workers (numpy arrays)
        self.annotated_frames = {}    # Annotated frames with bounding boxes (JPEG bytes)
        self._frame_lock = threading.Lock()  # Thread safety for shared dicts

    def start(self):
        logger.info(f"Starting CameraPool: {len(self.sources)} source(s)")
        for i, source in enumerate(self.sources):
            logger.info(f"  Camera {i}: {source}")
            worker = CameraWorker(source, i, self.queue, self, target_height=self.target_height)
            worker.start()
            self.workers.append(worker)
        
        logger.info(f"CameraPool started: {len(self.workers)} cameras active")
        logger.info(f"  All cameras will be processed independently")
        logger.info(f"  Person detection: HUMANS ONLY (COCO class 0)")
        logger.info(f"  Face detection: Multi-scale with Haar fallback")

    def get_latest_frame(self, cam_id: int):
        """
        Return annotated frame if available (with bounding boxes),
        otherwise return raw camera frame.
        Returns a COPY to prevent caller mutation of shared state.
        Thread-safe via _frame_lock.
        """
        with self._frame_lock:
            # First check for annotated frame (with face bounding boxes)
            annotated = self.annotated_frames.get(cam_id)
            if annotated is not None:
                return annotated  # bytes are immutable

            # Fall back to raw camera frame (return copy)
            raw = self.latest_frames.get(cam_id)
            if raw is not None:
                return raw.copy()
            return None

    def get_status(self) -> list:
        """Return status of all cameras with health metrics."""
        status = []
        now = time.time()
        for i, worker in enumerate(self.workers):
            time_since_frame = now - worker.last_good_frame_time if worker.last_good_frame_time > 0 else -1
            is_stale = time_since_frame > worker.stale_stream_threshold if time_since_frame > 0 else False
            status.append({
                "id": i,
                "source": str(worker.source),
                "connected": worker.connected,
                "frames": worker.frame_count,
                "last_frame_age_sec": round(time_since_frame, 1) if time_since_frame > 0 else None,
                "stale": is_stale,
                "reconnect_attempts": worker.reconnect_attempts,
            })
        return status

    def update_settings(self, cam_id: int, settings: dict):
        pass  # Auto-enhancement handles this now

    def stop_all(self):
        logger.info("Stopping CameraPool...")
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.join(timeout=2)
        self.workers.clear()
        with self._frame_lock:
            self.latest_frames.clear()
            self.annotated_frames.clear()
