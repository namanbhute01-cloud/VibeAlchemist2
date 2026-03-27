import cv2
import threading
import time
import logging
import queue
from typing import List, Union

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("CameraPool")

class CameraWorker(threading.Thread):
    """
    Worker thread for a single camera source.
    Reads frames, resizes them, and pushes to the shared queue.
    """
    def __init__(self, source: Union[int, str], cam_id: int, frame_queue: queue.Queue, target_height=720):
        super().__init__(daemon=True)
        self.source = source
        self.cam_id = cam_id
        self.queue = frame_queue
        self.target_height = target_height
        self.running = False
        self.cap = None

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
        Basic preprocessing: Resize and optional CLAHE.
        The main enhancement happens in the Vision Pipeline.
        """
        h, w = frame.shape[:2]
        scale = self.target_height / h
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), self.target_height))
        
        # Basic brightness normalization if too dark
        # (Save heavy CLAHE for later to conserve CPU on this thread)
        return frame

    def update_settings(self, settings: dict):
        """Live update of worker settings (brightness, etc.)"""
        if 'brightness' in settings and self.cap:
            self.cap.set(cv2.CAP_PROP_BRIGHTNESS, settings['brightness'])
        if 'contrast' in settings and self.cap:
            self.cap.set(cv2.CAP_PROP_CONTRAST, settings['contrast'])
        # Sharpness is usually software-based, skipping for low-level CAP_PROP

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
            
            # Preprocess
            try:
                processed_frame = self._preprocess(frame)
                
                # Push to queue (non-blocking, drop if full to maintain real-time)
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
        self.join()

class CameraPool:
    """
    Manager for multiple CameraWorker threads.
    """
    def __init__(self, sources: List[Union[int, str]], frame_queue: queue.Queue, target_height=720):
        self.sources = sources
        self.queue = frame_queue
        self.target_height = target_height
        self.workers = []

    def start(self):
        logger.info(f"Starting CameraPool with {len(self.sources)} sources...")
        for i, source in enumerate(self.sources):
            # Convert string digits to int (for USB cams)
            if isinstance(source, str) and source.isdigit():
                source = int(source)
            
            worker = CameraWorker(source, i, self.queue, target_height=self.target_height)
            worker.start()
            self.workers.append(worker)

    def update_settings(self, cam_id: int, settings: dict):
        if 0 <= cam_id < len(self.workers):
            self.workers[cam_id].update_settings(settings)

    def stop(self):
        logger.info("Stopping CameraPool...")
        for worker in self.workers:
            worker.stop()
        self.workers.clear()
