"""
Kalman Filter Age Smoother — prevents age "teleporting" between frames.

Instead of hard averaging or simple exponential smoothing, a Kalman filter
models both the estimated age (state) and the uncertainty (covariance).
This allows the system to:
  - Trust high-confidence predictions more
  - Ignore outlier predictions (bad lighting, occlusion)
  - Gradually "drift" toward the true age rather than jumping

Per-person Kalman filters are keyed by track_id or face identity.

Math:
    EstimatedAge_t = α × (NewPrediction) + (1-α) × (PreviousAge)
    where α is the Kalman gain, computed dynamically from confidence.
"""
import numpy as np
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class KalmanAgeSmoother:
    """
    Kalman filter for per-person age estimation.

    State: [age]
    Observation: new_age_prediction with associated confidence
    """

    def __init__(
        self,
        process_noise: float = 1.0,
        measurement_noise_base: float = 25.0,
        initial_estimate: float = 25.0,
        initial_uncertainty: float = 50.0,
    ):
        """
        :param process_noise: How much we expect age to change naturally (Q).
        :param measurement_noise_base: Base uncertainty in model predictions (R).
        :param initial_estimate: Starting age estimate.
        :param initial_uncertainty: How uncertain we are initially (P).
        """
        self._Q = process_noise  # Process noise covariance
        self._R_base = measurement_noise_base  # Base measurement noise
        self._x = initial_estimate  # State estimate
        self._P = initial_uncertainty  # Error covariance

    def update(self, measurement: float, confidence: float = 0.5) -> float:
        """
        Update the Kalman filter with a new age prediction.
        :param measurement: New age prediction from model.
        :param confidence: Model confidence (0.0 to 1.0).
        :returns: Smoothed age estimate.
        """
        # Measurement noise is inversely proportional to confidence
        # High confidence → low R → trust measurement more
        # Low confidence → high R → trust prediction more
        R = self._R_base / max(confidence, 0.05)

        # ── Prediction Step ──
        # State transition is identity (age doesn't change rapidly)
        x_pred = self._x
        P_pred = self._x + self._Q  # P_k = P_{k-1} + Q

        # ── Update Step ──
        # Kalman gain: K = P_pred / (P_pred + R)
        K = P_pred / (P_pred + R)

        # State update: x = x_pred + K * (measurement - x_pred)
        self._x = x_pred + K * (measurement - x_pred)

        # Covariance update: P = (1 - K) * P_pred
        self._P = (1 - K) * P_pred

        # Clamp to reasonable range
        self._x = max(3.0, min(90.0, self._x))

        return int(round(self._x))

    def get_estimate(self) -> float:
        """Return current smoothed age estimate."""
        return self._x

    def get_uncertainty(self) -> float:
        """Return current uncertainty (lower = more confident)."""
        return self._P

    def reset(self, initial_estimate: float = 25.0):
        """Reset the filter (e.g., new person detected)."""
        self._x = initial_estimate
        self._P = 50.0


class MultiPersonAgeSmoother:
    """
    Manages per-person Kalman filters keyed by track_id or identity.
    Automatically creates new filters for new persons.
    Prunes stale entries after timeout.
    """

    def __init__(
        self,
        process_noise: float = None,
        stale_timeout: int = 300,  # 5 minutes at 1 Hz
    ):
        self._filters: Dict[str, KalmanAgeSmoother] = {}
        self._last_update: Dict[str, float] = {}
        self._stale_timeout = stale_timeout

        # Allow override via env
        import os
        self._process_noise = float(
            os.getenv("KALMAN_PROCESS_NOISE", str(process_noise or 1.0))
        )
        self._alpha = float(os.getenv("KALMAN_ALPHA", "0.2"))  # Smoothing factor

        import time
        self._time_fn = time.time

        logger.info(
            f"MultiPersonAgeSmoother initialized "
            f"(Q={self._process_noise}, stale_timeout={stale_timeout}s)"
        )

    def update(
        self, person_id: str, raw_age: float, confidence: float = 0.5
    ) -> int:
        """
        Update age estimate for a person.
        :param person_id: Track ID or face identity string.
        :param raw_age: Raw age prediction from model.
        :param confidence: Model confidence (0.0 to 1.0).
        :returns: Smoothed age (integer).
        """
        import time

        now = self._time_fn()

        # Get or create Kalman filter
        if person_id not in self._filters:
            self._filters[person_id] = KalmanAgeSmoother(
                process_noise=self._process_noise,
                initial_estimate=raw_age,
            )

        # Update filter
        smoothed = self._filters[person_id].update(raw_age, confidence)
        self._last_update[person_id] = now

        return smoothed

    def get_estimate(self, person_id: str) -> Optional[float]:
        """Get current smoothed age for a person."""
        if person_id in self._filters:
            return self._filters[person_id].get_estimate()
        return None

    def get_uncertainty(self, person_id: str) -> Optional[float]:
        """Get current uncertainty for a person."""
        if person_id in self._filters:
            return self._filters[person_id].get_uncertainty()
        return None

    def prune_stale(self):
        """Remove filters for persons not seen recently."""
        import time

        now = self._time_fn()
        stale_ids = [
            pid
            for pid, last in self._last_update.items()
            if now - last > self._stale_timeout
        ]
        for pid in stale_ids:
            self._filters.pop(pid, None)
            self._last_update.pop(pid, None)

        if stale_ids:
            logger.debug(f"Pruned {len(stale_ids)} stale age filters")

    def reset_person(self, person_id: str):
        """Reset age filter for a specific person."""
        self._filters.pop(person_id, None)
        self._last_update.pop(person_id, None)

    def get_all_estimates(self) -> Dict[str, dict]:
        """Get all current age estimates with uncertainty."""
        return {
            pid: {
                "age": self._filters[pid].get_estimate(),
                "uncertainty": self._filters[pid].get_uncertainty(),
            }
            for pid in self._filters
        }
