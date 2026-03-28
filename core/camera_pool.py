import cv2
import threading
import time
import logging
import queue
import os
from typing import List, Union
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("CameraPool")

class CameraWorker(threading.Thread):
    """
    Worker thread for a single camera source.
    Reads frames, resizes them, and pushes to the shared queue.
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
        
        # Settings
        self.brightness = 0
        self.contrast = 1.0
        self.sharpness = 0

    def _connect(self):
        """Attempts to connect to the camera source."""
        if self.cap:
            self.cap.release()
        
        logger.info(f"[Cam {self.cam_id}] Connecting to source: {self.source}")
        self.cap = cv2.VideoCapture(self.source)
        
        # Optimize buffer size for low latency
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _preprocess(self, frame):
        """
        Basic preprocessing: Resize and user settings.
        """
        # Apply user settings
        if self.brightness != 0 or self.contrast != 1.0:
            frame = cv2.convertScaleAbs(frame, alpha=self.contrast, beta=self.brightness * 10)
        
        # Simple sharpness (Laplacian enhancement)
        if self.sharpness > 0:
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            sharpened = cv2.filter2D(frame, -1, kernel)
            frame = cv2.addWeighted(frame, 1-self.sharpness, sharpened, self.sharpness, 0)

        h, w = frame.shape[:2]
        if h > self.target_height:
            scale = self.target_height / h
            frame = cv2.resize(frame, (int(w * scale), self.target_height))
        
        return frame

    def run(self):
        self.running = True
        self._connect()
        
        while self.running:
            if not self.cap or not self.cap.isOpened():
                logger.warning(f"[Cam {self.cam_id}] Connection lost. Retrying in 5s...")
                time.sleep(5)
                self._connect()
                continue

            ret, frame = self.cap.read()
            if not ret:
                logger.warning(f"[Cam {self.cam_id}] Frame read failed.")
                self.cap.release()
                continue
            
            try:
                processed_frame = self._preprocess(frame)
                
                # Store in pool for direct access
                self.pool.latest_frames[self.cam_id] = processed_frame
                
                # Push to queue for pipeline
                if self.queue.full():
                    try:
                        self.queue.get_nowait() # Drop old frame
                    except queue.Empty:
                        pass
                
                self.queue.put({
                    "cam_id": self.cam_id,
                    "frame": processed_frame,
                    "timestamp": time.time()
                })
                
                # Cap frame rate to ~15 FPS to save CPU
                time.sleep(0.066) 

            except Exception as e:
                logger.error(f"[Cam {self.cam_id}] Error: {e}")

        if self.cap:
            self.cap.release()
        logger.info(f"[Cam {self.cam_id}] Worker stopped.")

    def stop(self):
        self.running = False

class CameraPool:
    """
    Manager for multiple CameraWorker threads.
    """
    def __init__(self, sources: List[Union[int, str]] = None, frame_queue: queue.Queue = None, target_height=720):
        # Step 1.1 — Fix camera source parsing
        if sources is None:
            raw = os.getenv("CAMERA_SOURCES", "0")
            sources_list = []
            for s in raw.split(","):
                s = s.strip()
                if not s:
                    continue
                if s.isdigit():
                    sources_list.append(int(s))   # USB camera — MUST be int
                else:
                    sources_list.append(s)         # RTSP/HTTP URL — keep as string
            self.sources = sources_list
        else:
            self.sources = sources
            
        self.queue = frame_queue
        self.target_height = target_height
        self.workers = []
        self.latest_frames = {}

    def start(self):
        logger.info(f"Starting CameraPool with {len(self.sources)} sources...")
        for i, source in enumerate(self.sources):
            worker = CameraWorker(source, i, self.queue, self, target_height=self.target_height)
            worker.start()
            self.workers.append(worker)

    # Step 1.2 — Add get_latest_frame
    def get_latest_frame(self, cam_id: int):
        return self.latest_frames.get(cam_id, None)

    # Step 1.3 — Add update_settings
    def update_settings(self, cam_id: int, settings: dict):
        if 0 <= cam_id < len(self.workers):
            worker = self.workers[cam_id]
            if hasattr(worker, 'brightness'): worker.brightness = settings.get('brightness', worker.brightness)
            if hasattr(worker, 'contrast'):   worker.contrast   = settings.get('contrast',   worker.contrast)
            if hasattr(worker, 'sharpness'):  worker.sharpness  = settings.get('sharpness',  worker.sharpness)

    def stop_all(self):
        logger.info("Stopping CameraPool...")
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.join(timeout=2)
        self.workers.clear()
        self.latest_frames.clear()
