"""
Asynchronous Producer-Consumer Pipeline for VibeAlchemist V5.

Solves "Inference Lag" by decoupling frame capture from AI inference.

Architecture:
    Producer Thread:  Grabs frames at camera FPS (15-30 FPS), puts in ring buffer.
    Consumer Thread:  Pulls LATEST frame every 100ms, runs AI pipeline.
    Result Callback:   Detections are passed to a callback function (non-blocking).

This ensures:
  - Video stream stays at full FPS (no waiting for AI)
  - AI inference runs at ~10 FPS (every 100ms) on latest frame
  - UI and music never "wait" for the AI

Usage:
    pipeline = AsyncVisionPipeline(
        vision_pipeline=VisionPipeline(...),
        on_detections=process_detections_callback,
        inference_interval=0.1  # 100ms = 10 FPS inference
    )
    pipeline.start()
    pipeline.submit_frame(cam_id, frame)  # Called by camera pool
    pipeline.stop()
"""
import threading
import queue
import time
import logging
from collections import defaultdict
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AsyncVisionPipeline:
    """
    Producer-Consumer pattern for non-blocking vision inference.

    The producer (camera pool) calls submit_frame() at camera FPS.
    The consumer thread runs AI inference on the latest frame every N ms.
    Results are passed to on_detections callback.
    """

    def __init__(
        self,
        vision_pipeline,
        on_detections: Callable,
        inference_interval: float = 0.1,
        max_queue_size: int = 2,
    ):
        """
        :param vision_pipeline: VisionPipeline instance (the actual AI model).
        :param on_detections: Callback(detections, cam_id) for results.
        :param inference_interval: Seconds between inference runs (default 0.1s = 10 FPS).
        :param max_queue_size: Max frames to buffer per camera (default 2).
        """
        self._pipeline = vision_pipeline
        self._on_detections = on_detections
        self._inference_interval = inference_interval
        self._max_queue_size = max_queue_size

        # Per-camera frame buffers (ring buffer — only keep latest)
        self._frame_buffers: dict = defaultdict(lambda: None)
        self._frame_lock = threading.Lock()

        # Control
        self._running = False
        self._consumer_thread: Optional[threading.Thread] = None

        # Stats
        self._frames_submitted = 0
        self._frames_processed = 0
        self._last_process_time = 0.0

        logger.info(
            f"AsyncVisionPipeline initialized "
            f"(interval={inference_interval}s, max_queue={max_queue_size})"
        )

    def start(self):
        """Start the consumer thread."""
        self._running = True
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop, daemon=True, name="vision-consumer"
        )
        self._consumer_thread.start()
        logger.info("AsyncVisionPipeline consumer started")

    def stop(self):
        """Stop the consumer thread."""
        self._running = False
        if self._consumer_thread:
            self._consumer_thread.join(timeout=2.0)
            self._consumer_thread = None
        logger.info("AsyncVisionPipeline consumer stopped")

    def submit_frame(self, cam_id: int, frame):
        """
        Called by the camera pool (producer) for every captured frame.
        Only keeps the LATEST frame — older frames are discarded.
        This is the key to avoiding backpressure on the camera thread.
        """
        with self._frame_lock:
            self._frame_buffers[cam_id] = (time.time(), frame)
            self._frames_submitted += 1

    def _consumer_loop(self):
        """
        Consumer thread: pulls latest frames and runs AI inference.
        Runs at inference_interval (default 100ms = 10 FPS inference).
        """
        logger.info("Vision consumer loop started")

        while self._running:
            try:
                now = time.time()
                elapsed = now - self._last_process_time

                if elapsed >= self._inference_interval:
                    self._process_latest(now)

                # Sleep to maintain target inference rate
                sleep_time = max(0.001, self._inference_interval - (time.time() - now))
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Vision consumer error: {e}")
                time.sleep(0.5)

    def _process_latest(self, timestamp: float):
        """Process the latest available frame from any camera."""
        # Get latest frame across all cameras (round-robin)
        with self._frame_lock:
            if not self._frame_buffers:
                return

            # Pick camera with newest frame (fair scheduling)
            cam_id = None
            newest_time = 0
            for cid, (t, frame) in self._frame_buffers.items():
                if t > newest_time and frame is not None:
                    newest_time = t
                    cam_id = cid

            if cam_id is None:
                return

            _, frame = self._frame_buffers[cam_id]
            self._frame_buffers[cam_id] = None  # Consume frame

        if frame is None:
            return

        # Run AI inference (this is the blocking part)
        try:
            detections = self._pipeline.process_frame(frame, cam_id)
            self._frames_processed += 1
            self._last_process_time = timestamp

            # Pass results to callback (non-blocking)
            if detections and self._on_detections:
                self._on_detections(detections, cam_id)

        except Exception as e:
            logger.error(f"Inference error on camera {cam_id}: {e}")

    def get_stats(self) -> dict:
        """Get pipeline performance statistics."""
        return {
            "frames_submitted": self._frames_submitted,
            "frames_processed": self._frames_processed,
            "drop_rate": (
                1.0 - self._frames_processed / max(1, self._frames_submitted)
            )
            * 100,
            "inference_fps": (
                self._frames_processed / max(0.001, time.time() - self._last_process_time)
                if self._last_process_time > 0
                else 0
            ),
        }
