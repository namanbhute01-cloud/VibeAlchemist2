"""
Motion gate: skip inference when nothing has moved in the frame.
This is the primary CPU-saving mechanism.

Compares current bounding boxes to previous boxes using IoU.
If all boxes overlap > threshold, inference is skipped.
Forces re-inference every N frames regardless to catch stale state.
"""
import numpy as np
from typing import List


def compute_iou(box1: np.ndarray, box2: np.ndarray) -> float:
    """Compute IoU between two [x1, y1, x2, y2] boxes."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


class MotionGate:
    """
    Decides whether to run expensive inference each frame.
    Returns True → run inference; False → skip (use cached results).
    """

    def __init__(self, iou_threshold: float = 0.90, force_every: int = 30):
        """
        :param iou_threshold: If all boxes have IoU > this, skip inference.
        :param force_every: Force re-inference every N frames regardless.
        """
        self._threshold = iou_threshold
        self._force_every = force_every
        self._prev_boxes: List[np.ndarray] = []
        self._frame_count = 0

    def should_run_inference(self, current_boxes: List[np.ndarray]) -> bool:
        """
        Returns True if inference should run this frame.
        Returns False if nothing has moved (save CPU).
        """
        self._frame_count += 1

        # Force re-inference every N frames regardless
        if self._frame_count >= self._force_every:
            self._frame_count = 0
            self._prev_boxes = list(current_boxes)
            return True

        # New person appeared or someone left
        if len(current_boxes) != len(self._prev_boxes):
            self._prev_boxes = list(current_boxes)
            return True

        # No detections in either frame
        if not current_boxes:
            return False

        # Check if any box moved significantly
        for cur, prev in zip(current_boxes, self._prev_boxes):
            if compute_iou(cur, prev) < self._threshold:
                self._prev_boxes = list(current_boxes)
                return True

        return False  # nothing moved — skip inference

    def reset(self):
        """Reset internal state (e.g., camera switch)."""
        self._prev_boxes = []
        self._frame_count = 0
