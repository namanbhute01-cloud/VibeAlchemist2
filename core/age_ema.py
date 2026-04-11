"""
Age EMA Smoother — Exponential Moving Average for stable age predictions

Instead of believing the AI's latest guess 100%, EMA only lets the new
guess influence the result by a small percentage (α).

Formula:
    Age_smooth(t) = (α × Age_new) + ((1-α) × Age_smooth(t-1))

Where α = 0.1 means:
- 10% of new detection
- 90% of previous smoothed age
- Very stable, prevents "jumpy" age changes

This prevents the "Vibe" from jumping if the model briefly misidentifies
a teenager as an adult for a single frame.
"""
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("AgeEMA")


class AgeEMASmoother:
    """
    Per-track EMA age smoothing.

    Usage:
        smoother = AgeEMASmoother(alpha=0.1)
        smoothed_age = smoother.update(track_id="person_1", new_age=28, confidence=0.8)
    """

    def __init__(self, alpha: float = 0.1, max_age: int = 90, min_age: int = 3):
        """
        Args:
            alpha: Sensitivity (0.1 = stable, 0.9 = jumpy)
            max_age: Maximum age to clamp to
            min_age: Minimum age to clamp to
        """
        self.alpha = alpha
        self.max_age = max_age
        self.min_age = min_age

        # Per-track state: track_id -> {smoothed_age, confidence, last_update, frame_count}
        self.tracks: Dict[str, dict] = {}

        logger.info(f"AgeEMA initialized: alpha={alpha}, stable smoothing")

    def update(self, track_id: str, new_age: float, confidence: float = 0.5) -> float:
        """
        Update EMA for a specific track.

        Args:
            track_id: Unique identifier for the tracked person
            new_age: New age prediction from the model
            confidence: Confidence of the new prediction (0.0-1.0)

        Returns:
            Smoothed age (clamped to min/max)
        """
        # Clamp input
        new_age = max(self.min_age, min(self.max_age, int(new_age)))

        if track_id not in self.tracks:
            # First detection — initialize with new age
            self.tracks[track_id] = {
                "smoothed_age": new_age,
                "confidence": confidence,
                "last_update": time.time(),
                "frame_count": 1,
                "age_history": [new_age],
            }
            return new_age

        track = self.tracks[track_id]

        # Adaptive alpha: higher confidence = more weight to new prediction
        # If confidence is low, trust the smoothed value more
        adaptive_alpha = self.alpha * max(0.5, min(1.0, confidence * 2.0))

        # EMA formula: Age_smooth = (α × Age_new) + ((1-α) × Age_previous)
        smoothed = (adaptive_alpha * new_age) + ((1 - adaptive_alpha) * track["smoothed_age"])
        smoothed = int(round(smoothed))

        # Clamp to valid range
        smoothed = max(self.min_age, min(self.max_age, smoothed))

        # Update state
        track["smoothed_age"] = smoothed
        track["confidence"] = confidence
        track["last_update"] = time.time()
        track["frame_count"] += 1
        track["age_history"].append(new_age)

        # Keep history manageable (last 30 predictions)
        if len(track["age_history"]) > 30:
            track["age_history"] = track["age_history"][-30:]

        return smoothed

    def get_smoothed_age(self, track_id: str) -> Optional[float]:
        """Get the current smoothed age for a track."""
        if track_id in self.tracks:
            return self.tracks[track_id]["smoothed_age"]
        return None

    def get_median_age(self, track_id: str) -> Optional[float]:
        """
        Get median age over the tracking history.
        More robust to outliers than mean.
        """
        if track_id not in self.tracks:
            return None

        history = self.tracks[track_id]["age_history"]
        if not history:
            return None

        sorted_ages = sorted(history)
        n = len(sorted_ages)
        if n % 2 == 0:
            return (sorted_ages[n // 2 - 1] + sorted_ages[n // 2]) / 2
        else:
            return sorted_ages[n // 2]

    def get_track_info(self, track_id: str) -> Optional[dict]:
        """Get full tracking info for a track."""
        if track_id not in self.tracks:
            return None

        track = self.tracks[track_id]
        history = track["age_history"]

        return {
            "smoothed_age": track["smoothed_age"],
            "median_age": self.get_median_age(track_id),
            "confidence": track["confidence"],
            "frame_count": track["frame_count"],
            "age_range": (min(history), max(history)) if history else None,
            "last_update": track["last_update"],
        }

    def cleanup_stale_tracks(self, max_age_seconds: float = 30.0):
        """Remove tracks that haven't been updated recently."""
        now = time.time()
        stale_ids = []

        for track_id, track in self.tracks.items():
            if now - track["last_update"] > max_age_seconds:
                stale_ids.append(track_id)

        for track_id in stale_ids:
            del self.tracks[track_id]

        if stale_ids:
            logger.debug(f"Cleaned up {len(stale_ids)} stale tracks")

    def reset(self):
        """Clear all tracking state."""
        self.tracks.clear()
        logger.info("EMA state reset")

    def get_status(self) -> dict:
        """Get EMA smoother status."""
        self.cleanup_stale_tracks()

        active_tracks = len(self.tracks)
        avg_confidence = 0.0
        if active_tracks > 0:
            avg_confidence = sum(t["confidence"] for t in self.tracks.values()) / active_tracks

        return {
            "alpha": self.alpha,
            "active_tracks": active_tracks,
            "average_confidence": round(avg_confidence, 3),
            "smoothing": f"{int((1 - self.alpha) * 100)}% previous / {int(self.alpha * 100)}% new",
        }
