"""
Motion Gate — Skip inference when nothing moves

Compares current frame to previous frame using background subtraction.
If motion is below threshold, skip heavy inference (face recognition,
demographics, emotion) and use cached results from previous frame.

Saves ~50% CPU on static/low-motion scenes.

Usage:
    gate = MotionGate(history=500, var_threshold=25, min_motion_pixels=80)
    if gate.has_motion(frame):
        # Run heavy inference
        result = pipeline.process_frame(frame)
        gate.update_cache(result)
    else:
        # Use cached result
        result = gate.get_cached_result()
"""
import cv2
import numpy as np
import logging
import time

logger = logging.getLogger("MotionGate")


class MotionGate:
    """
    Motion-based inference gating.
    Uses OpenCV MOG2 background subtractor.
    """

    def __init__(self, history=500, var_threshold=25, min_motion_pixels=80,
                 forced_reinfer_frames=30):
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history,
            varThreshold=var_threshold,
            detectShadows=False
        )
        self.min_motion_pixels = min_motion_pixels
        self.forced_reinfer_frames = forced_reinfer_frames
        self.frame_count = 0
        self.cached_result = None
        self.cached_timestamp = 0

    def has_motion(self, frame):
        """
        Check if frame has enough motion to warrant re-inference.

        Args:
            frame: BGR numpy array

        Returns:
            bool: True if motion detected, False if should use cached result
        """
        self.frame_count += 1

        # Force re-inference every N frames regardless of motion
        if self.frame_count >= self.forced_reinfer_frames:
            self.frame_count = 0
            logger.debug("Forced re-inference (frame counter reset)")
            return True

        if frame is None or frame.size == 0:
            return True

        try:
            mask = self.bg_subtractor.apply(frame)
            mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)[0]
            mask = cv2.dilate(mask, None, iterations=2)
            motion_pixels = cv2.countNonZero(mask)

            if motion_pixels > self.min_motion_pixels:
                return True
            else:
                return False
        except Exception as e:
            logger.debug(f"Motion gate error: {e}")
            return True  # Default to inference on error

    def update_cache(self, result):
        """Cache the latest inference result."""
        self.cached_result = result
        self.cached_timestamp = time.time()

    def get_cached_result(self):
        """Get cached result from last inference."""
        if self.cached_result is not None:
            # Update timestamp so consumer knows result is fresh
            self.cached_result = dict(self.cached_result)
            self.cached_result['cached'] = True
            self.cached_result['cache_age'] = time.time() - self.cached_timestamp
            return self.cached_result
        return None

    def reset(self):
        """Reset motion gate state."""
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=25, detectShadows=False
        )
        self.frame_count = 0
        self.cached_result = None
        self.cached_timestamp = 0

    def get_status(self):
        """Get motion gate status."""
        return {
            "frame_count": self.frame_count,
            "forced_reinfer_at": self.forced_reinfer_frames,
            "min_motion_pixels": self.min_motion_pixels,
            "has_cached_result": self.cached_result is not None,
            "cache_age_sec": time.time() - self.cached_timestamp if self.cached_result else None,
        }
