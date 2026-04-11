"""
Auto-Calibration Engine V4 — Learns from real-world age corrections

Continuously adjusts age prediction calibration based on user feedback
and known-age identity registrations.

Usage:
    cal = AutoCalibration(models_dir="models")
    
    # Record a manual age correction (from user input or known identity)
    cal.record_correction(predicted_age=25, actual_age=30, confidence=0.8)
    
    # Get calibrated age
    calibrated_age, confidence = cal.calibrate(raw_age=25, base_confidence=0.7)
    
    # Save/load calibration data
    cal.save("calibration_data.json")
    cal.load("calibration_data.json")
"""
import os
import json
import numpy as np
import logging
from collections import defaultdict

logger = logging.getLogger("AutoCalibration")


class AutoCalibration:
    """
    Learns age correction factors from real-world data.
    
    Instead of using fixed correction multipliers, this engine:
    1. Collects (predicted_age, actual_age) pairs
    2. Bins them by age range
    3. Computes optimal correction factor per bin
    4. Interpolates for ages between bins
    """

    def __init__(self, models_dir="models", min_samples_per_bin=5):
        self.models_dir = models_dir
        self.min_samples_per_bin = min_samples_per_bin

        # Age bins (boundaries) — 10 bins for fine granularity
        self.age_bins = [0, 5, 10, 15, 20, 25, 30, 40, 50, 65, 90]

        # Correction data: bin_index -> list of (predicted, actual) pairs
        self.corrections = defaultdict(list)

        # Global correction factors (fallback)
        self.global_multiplier = 1.0
        self.global_offset = 0.0

        # Confidence adjustment based on sample count
        self.base_confidence = 0.7
        self.max_confidence = 0.95

        # Track calibration version
        self.calibration_version = 2
        self.total_corrections = 0

        logger.info(
            f"AutoCalibration V4: {len(self.age_bins)-1} age bins, "
            f"min samples/bin: {min_samples_per_bin}"
        )

    def record_correction(self, predicted_age, actual_age, confidence=0.5, source="manual"):
        """
        Record a single age correction data point.
        
        Args:
            predicted_age: Age predicted by the model
            actual_age: True age (from user input or known identity)
            confidence: Confidence in the actual age (0.0-1.0)
            source: Source of correction ("manual", "identity", "benchmark")
        """
        # Find the appropriate age bin (based on PREDICTED age)
        bin_idx = self._find_bin(predicted_age)
        if bin_idx is None:
            return

        # Store correction with metadata
        self.corrections[bin_idx].append({
            "predicted": predicted_age,
            "actual": actual_age,
            "confidence": confidence,
            "source": source,
        })

        self.total_corrections += 1

        # Recalculate calibration factors
        self._recalculate_factors()

        logger.debug(
            f"Recorded correction: predicted={predicted_age}, actual={actual_age} "
            f"(bin {bin_idx}, total corrections: {self.total_corrections})"
        )

    def _find_bin(self, age):
        """Find the age bin index for a given age."""
        for i in range(len(self.age_bins) - 1):
            if self.age_bins[i] <= age < self.age_bins[i + 1]:
                return i
        return len(self.age_bins) - 2  # Last bin

    def _recalculate_factors(self):
        """Recalculate correction factors for all bins."""
        for bin_idx in range(len(self.age_bins) - 1):
            samples = self.corrections.get(bin_idx, [])
            if len(samples) < self.min_samples_per_bin:
                continue  # Not enough data

            # Weight samples by confidence
            weighted_predictions = []
            weighted_actuals = []
            weights = []

            for sample in samples:
                w = max(0.1, sample["confidence"])
                weighted_predictions.append(sample["predicted"] * w)
                weighted_actuals.append(sample["actual"] * w)
                weights.append(w)

            avg_predicted = sum(weighted_predictions) / max(0.001, sum(weights))
            avg_actual = sum(weighted_actuals) / max(0.001, sum(weights))

            # Calculate correction factor
            if avg_predicted > 0:
                multiplier = avg_actual / avg_predicted
                offset = avg_actual - avg_predicted

                # Clamp to reasonable ranges
                multiplier = max(0.5, min(5.0, multiplier))
                offset = max(-30, min(30, offset))

                logger.debug(
                    f"Bin {bin_idx} ({self.age_bins[bin_idx]}-{self.age_bins[bin_idx+1]}): "
                    f"multiplier={multiplier:.2f}, offset={offset:.1f} "
                    f"({len(samples)} samples)"
                )

    def calibrate(self, raw_age, base_confidence=0.7):
        """
        Calibrate a raw age prediction using learned correction factors.
        
        Returns:
            (calibrated_age, adjusted_confidence)
        """
        bin_idx = self._find_bin(raw_age)
        if bin_idx is None:
            return raw_age, base_confidence

        samples = self.corrections.get(bin_idx, [])

        if len(samples) < self.min_samples_per_bin:
            # Not enough data — use global factors
            calibrated_age = int(raw_age * self.global_multiplier + self.global_offset)
            confidence = base_confidence * 0.8  # Reduce confidence
        else:
            # Use bin-specific factors
            # Weight recent samples more heavily
            recent_samples = samples[-min(20, len(samples)):]

            weighted_pred_sum = 0
            weighted_act_sum = 0
            weight_sum = 0

            for i, sample in enumerate(recent_samples):
                # Exponential weighting for recency
                w = max(0.1, sample["confidence"]) * np.exp(i / len(recent_samples))
                weighted_pred_sum += sample["predicted"] * w
                weighted_act_sum += sample["actual"] * w
                weight_sum += w

            if weight_sum > 0:
                avg_pred = weighted_pred_sum / weight_sum
                avg_act = weighted_act_sum / weight_sum

                if avg_pred > 0:
                    multiplier = avg_act / avg_pred
                    calibrated_age = int(raw_age * multiplier)
                else:
                    calibrated_age = raw_age
            else:
                calibrated_age = raw_age

            # Adjust confidence based on sample count and consistency
            sample_confidence = min(1.0, len(samples) / 30.0)  # Max at 30 samples
            consistency = self._calculate_consistency(samples)
            confidence = base_confidence * sample_confidence * consistency
            confidence = min(self.max_confidence, max(0.1, confidence))

        # Clamp to reasonable range
        calibrated_age = min(90, max(3, calibrated_age))

        return calibrated_age, confidence

    def _calculate_consistency(self, samples):
        """
        Calculate how consistent the correction samples are.
        Returns 0.0-1.0 (1.0 = very consistent).
        """
        if len(samples) < 3:
            return 0.5  # Not enough data to judge

        # Calculate prediction errors
        errors = [abs(s["actual"] - s["predicted"]) for s in samples]

        # Low variance = high consistency
        mean_error = np.mean(errors)
        std_error = np.std(errors)

        # Consistency decreases with variance
        consistency = max(0.0, 1.0 - std_error / 30.0)

        return consistency

    def get_calibration_status(self):
        """Get current calibration status."""
        bin_stats = {}
        for bin_idx in range(len(self.age_bins) - 1):
            samples = self.corrections.get(bin_idx, [])
            bin_stats[f"{self.age_bins[bin_idx]}-{self.age_bins[bin_idx+1]}"] = {
                "samples": len(samples),
                "sufficient": len(samples) >= self.min_samples_per_bin,
            }

        return {
            "version": self.calibration_version,
            "total_corrections": self.total_corrections,
            "bins": bin_stats,
            "global_multiplier": round(self.global_multiplier, 3),
            "global_offset": round(self.global_offset, 2),
            "bins_ready": sum(
                1 for bin_idx in range(len(self.age_bins) - 1)
                if len(self.corrections.get(bin_idx, [])) >= self.min_samples_per_bin
            ),
            "total_bins": len(self.age_bins) - 1,
        }

    def save(self, filepath):
        """Save calibration data to JSON."""
        data = {
            "version": self.calibration_version,
            "age_bins": self.age_bins,
            "corrections": {str(k): v for k, v in self.corrections.items()},
            "global_multiplier": self.global_multiplier,
            "global_offset": self.global_offset,
            "total_corrections": self.total_corrections,
        }

        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Calibration data saved to {filepath}")

    def load(self, filepath):
        """Load calibration data from JSON."""
        if not os.path.exists(filepath):
            logger.warning(f"Calibration file not found: {filepath}")
            return False

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            self.calibration_version = data.get("version", 1)
            self.age_bins = data.get("age_bins", self.age_bins)
            self.corrections = defaultdict(list, {
                int(k): v for k, v in data.get("corrections", {}).items()
            })
            self.global_multiplier = data.get("global_multiplier", 1.0)
            self.global_offset = data.get("global_offset", 0.0)
            self.total_corrections = data.get("total_corrections", 0)

            self._recalculate_factors()

            logger.info(
                f"Calibration data loaded from {filepath} "
                f"(v{self.calibration_version}, {self.total_corrections} corrections)"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load calibration data: {e}")
            return False

    def batch_record(self, correction_list):
        """
        Record multiple corrections at once.
        
        Args:
            correction_list: List of (predicted_age, actual_age, confidence, source) tuples
        """
        for predicted, actual, conf, source in correction_list:
            self.record_correction(predicted, actual, conf, source)

        logger.info(f"Batch recorded {len(correction_list)} corrections")

    def reset(self):
        """Reset all calibration data."""
        self.corrections.clear()
        self.global_multiplier = 1.0
        self.global_offset = 0.0
        self.total_corrections = 0
        logger.info("Calibration data reset")
