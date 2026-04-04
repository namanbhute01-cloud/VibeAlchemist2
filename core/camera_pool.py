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

    def _connect(self):
        """Connect to camera source with optimized settings."""
        if self.cap:
            self.cap.release()
            self.connected = False

        logger.info(f"[Cam {self.cam_id}] Connecting: {self.source}")

        if isinstance(self.source, str):
            # HTTP/RTSP stream — optimize for low latency
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            # Reduce buffer to 1 frame (lowest latency)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # Set timeouts for network streams
            self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        else:
            # USB webcam
            self.cap = cv2.VideoCapture(self.source)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        if self.cap.isOpened():
            self.connected = True
            logger.info(f"[Cam {self.cam_id}] Connected")
        else:
            logger.error(f"[Cam {self.cam_id}] Failed to open")

    def run(self):
        self.running = True
        self._connect()

        reconnect_delay = 2  # Start with 2s
        max_delay = 10

        while self.running:
            if not self.cap or not self.cap.isOpened():
                logger.warning(f"[Cam {self.cam_id}] Reconnecting in {reconnect_delay}s...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, max_delay)
                self._connect()
                continue

            ret, frame = self.cap.read()
            if not ret:
                logger.warning(f"[Cam {self.cam_id}] Read failed, reconnecting...")
                self.cap.release()
                self.connected = False
                time.sleep(1)
                continue

            # Reset reconnect delay on successful read
            reconnect_delay = 2

            try:
                # ── Lightweight resize only (no enhancement) ──
                h, w = frame.shape[:2]
                if h > self.target_height:
                    scale = self.target_height / h
                    frame = cv2.resize(frame, (int(w * scale), self.target_height),
                                       interpolation=cv2.INTER_LINEAR)

                # Store latest frame for MJPEG feed
                self.pool.latest_frames[self.cam_id] = frame

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
                    logger.debug(f"[Cam {self.cam_id}] {fps:.1f} FPS")
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
            self.cap.release()
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
        self.latest_frames = {}

    def start(self):
        logger.info(f"Starting CameraPool: {len(self.sources)} source(s)")
        for i, source in enumerate(self.sources):
            worker = CameraWorker(source, i, self.queue, self, target_height=self.target_height)
            worker.start()
            self.workers.append(worker)

    def get_latest_frame(self, cam_id: int):
        return self.latest_frames.get(cam_id, None)

    def get_status(self) -> list:
        """Return status of all cameras."""
        status = []
        for i, worker in enumerate(self.workers):
            status.append({
                "id": i,
                "source": str(worker.source),
                "connected": worker.connected,
                "frames": worker.frame_count
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
        self.latest_frames.clear()
