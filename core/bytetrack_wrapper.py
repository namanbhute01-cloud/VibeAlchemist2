"""
ByteTrack wrapper: persistent person tracking without re-running
recognition every frame. Associates track_id → identity.

Preserves identity when face is temporarily hidden (occlusion, profile view).
Maps track_id → person name from face recognition vault.

Input:  list of detections from TieredDetector
        [{bbox_full, confidence, ...}, ...]
Output: list of [{track_id, bbox, name}, ...] with persistent IDs

If bytetracker is not installed, falls back to sequential per-frame IDs.
"""
import numpy as np
import logging

logger = logging.getLogger(__name__)

try:
    from bytetracker import BYTETracker

    _BYTETRACK_AVAILABLE = True
except ImportError:
    _BYTETRACK_AVAILABLE = False
    logger.warning(
        "bytetracker not installed — tracking disabled, fallback to per-frame IDs. "
        "Install: pip install bytetracker"
    )


class PersonTracker:
    def __init__(self):
        self._id_to_name: dict = {}
        self._next_id = 0

        if _BYTETRACK_AVAILABLE:
            try:
                self._tracker = BYTETracker(
                    track_thresh=0.5,
                    track_buffer=30,
                    match_thresh=0.8,
                    frame_rate=15,
                )
                logger.info("PersonTracker: ByteTrack initialized")
            except Exception as e:
                logger.warning(f"ByteTrack initialization failed: {e}")
                self._tracker = None
        else:
            self._tracker = None

    def update(self, detections: list, frame_shape: tuple) -> list:
        """
        Update tracker with new detections.
        :param detections: list of {bbox_full, confidence, ...} from TieredDetector.
        :param frame_shape: (height, width, channels) of current frame.
        :returns: list of {track_id, bbox, name} with persistent IDs.
        """
        if not detections:
            return []

        if self._tracker is None:
            # Fallback: assign sequential IDs, no persistence across frames
            results = []
            for i, d in enumerate(detections):
                tid = self._next_id
                self._next_id += 1
                results.append(
                    {
                        "track_id": tid,
                        "bbox": d["bbox_full"],
                        "name": self._id_to_name.get(tid, "unknown"),
                    }
                )
            return results

        # ByteTrack expects: [x1, y1, x2, y2, confidence] for each detection
        boxes = np.array(
            [[*d["bbox_full"], d["confidence"]] for d in detections]
        )

        try:
            tracks = self._tracker.update(boxes, frame_shape)
        except Exception as e:
            logger.error(f"ByteTrack update failed: {e}")
            # Fallback to per-frame IDs
            return [
                {"track_id": i, "bbox": d["bbox_full"], "name": "unknown"}
                for i, d in enumerate(detections)
            ]

        results = []
        for track in tracks:
            tid = int(track[4])
            bbox = track[:4].astype(int)
            results.append(
                {
                    "track_id": tid,
                    "bbox": bbox,
                    "name": self._id_to_name.get(tid, "unknown"),
                }
            )
        return results

    def assign_name(self, track_id: int, name: str):
        """Call when face recognition confirms an identity."""
        if name and name != "unknown":
            self._id_to_name[track_id] = name

    def clear_name(self, track_id: int):
        """Remove name association for a track ID."""
        self._id_to_name.pop(track_id, None)

    def get_name(self, track_id: int) -> str:
        """Get current name for a track ID."""
        return self._id_to_name.get(track_id, "unknown")

    def reset(self):
        """Reset all state (e.g., camera switch)."""
        self._id_to_name.clear()
        self._next_id = 0
        if self._tracker is not None:
            try:
                self._tracker = BYTETracker(
                    track_thresh=0.5,
                    track_buffer=30,
                    match_thresh=0.8,
                    frame_rate=15,
                )
            except Exception:
                self._tracker = None
