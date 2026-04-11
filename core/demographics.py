"""
Demographics Module — Age + Gender Estimation

Supports:
- MiVOLO (face + body dual-input fusion) — best accuracy
- DEX-Age (face only) — fallback when MiVOLO unavailable
- EMA smoothing for stable, non-jumpy age predictions
- Per-track state with median calculation

The "Multi-Input" Secret:
  Input A (Face): Fine details like wrinkles, skin texture, eye shape
  Input B (Body): Height, clothing style, posture

  Cross-Attention weighting: If face is blurry, relies more on body data.
  Weighted Regression: Calculates probability distribution across all ages.

Usage:
    demo = DemographicsEngine(models_dir="models", tier=2)
    result = demo.predict(face_crop, body_crop=None)
    # Returns: {"age": 32, "gender": "male", "confidence": 0.75, "source": "dex"}
"""
import os
import cv2
import numpy as np
import logging
import time
from collections import deque

logger = logging.getLogger("Demographics")


class DemographicsEngine:
    """
    Age + gender estimation with tier-based model selection.
    Graceful fallback: MiVOLO → DEX-Age.
    """

    def __init__(self, models_dir="models", tier=2):
        self.models_dir = models_dir
        self.tier = tier
        self.mivolo_sess = None
        self.dex_sess = None
        self.gender_sess = None  # Separate gender model if MiVOLO unavailable

        # Tier-based model selection
        if tier == 1:
            # Tier 1: DEX-Age only (lightweight)
            self.use_mivolo = False
            logger.info("Demographics: Tier 1 — DEX-Age only (lightweight)")
        elif tier == 2:
            # Tier 2: Try MiVOLO XXS, fallback to DEX
            self.use_mivolo = True
            self.mivolo_path = os.path.join(models_dir, "mivolo_xxs.onnx")
            logger.info("Demographics: Tier 2 — MiVOLO XXS (fallback: DEX-Age)")
        else:
            # Tier 3: Try MiVOLO Full, fallback to DEX
            self.use_mivolo = True
            self.mivolo_path = os.path.join(models_dir, "mivolo_full.onnx")
            logger.info("Demographics: Tier 3 — MiVOLO Full (fallback: DEX-Age)")

        # Load models
        self._load_mivolo()
        if self.dex_sess is None:
            self._load_dex()

        # Temporal smoothing for stable predictions
        self.age_history = deque(maxlen=7)
        self.gender_history = deque(maxlen=7)

        logger.info(
            f"DemographicsEngine: MiVOLO={'ON' if self.mivolo_sess else 'OFF'}, "
            f"DEX-Age={'ON' if self.dex_sess else 'OFF'}"
        )

    def _load_mivolo(self):
        """Load MiVOLO ONNX model if available."""
        if not self.use_mivolo:
            return

        if not os.path.exists(self.mivolo_path):
            logger.warning(f"MiVOLO model not found: {self.mivolo_path} — using DEX-Age fallback")
            self._load_dex()
            return

        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            self.mivolo_sess = ort.InferenceSession(
                self.mivolo_path,
                providers=['CPUExecutionProvider'],
                sess_options=opts
            )

            # Check model input names
            inputs = self.mivolo_sess.get_inputs()
            input_names = [i.name for i in inputs]
            logger.info(f"MiVOLO loaded: inputs={input_names}")

            # Also load DEX as secondary (for validation/fallback)
            self._load_dex()

        except Exception as e:
            logger.warning(f"MiVOLO load failed: {e} — falling back to DEX-Age")
            self.mivolo_sess = None
            self._load_dex()

    def _load_dex(self):
        """Load DEX-Age ONNX model."""
        dex_path = os.path.join(self.models_dir, "dex_age.onnx")
        if not os.path.exists(dex_path):
            logger.warning(f"DEX-Age model not found: {dex_path}")
            return

        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            self.dex_sess = ort.InferenceSession(
                dex_path,
                providers=['CPUExecutionProvider'],
                sess_options=opts
            )
            logger.info(f"DEX-Age loaded: {dex_path}")
        except Exception as e:
            logger.error(f"DEX-Age load failed: {e}")

    def predict_mivolo(self, face_crop, body_crop=None):
        """
        Predict age + gender using MiVOLO (face + body).
        Returns {"age": float, "gender": str, "confidence": float}.
        """
        if self.mivolo_sess is None:
            return None

        try:
            def prep(img, size):
                img = cv2.resize(img, size)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                mean = [0.485, 0.456, 0.406]
                std = [0.229, 0.224, 0.225]
                img = (img - mean) / std
                return img.transpose(2, 0, 1)[np.newaxis, :]

            face_input = prep(face_crop, (112, 112))

            if body_crop is not None and body_crop.size > 0:
                body_input = prep(body_crop, (192, 256))
            else:
                body_input = prep(face_crop, (192, 256))

            inputs = {
                self.mivolo_sess.get_inputs()[0].name: face_input,
                self.mivolo_sess.get_inputs()[1].name: body_input,
            }

            outs = self.mivolo_sess.run(None, inputs)

            # MiVOLO outputs: [age_logits, gender_logits]
            age_logits = outs[0][0]
            gender_logits = outs[1][0]

            # Softmax age
            age_probs = np.exp(age_logits - np.max(age_logits))
            age_probs = age_probs / np.sum(age_probs)
            expected_age = float(np.sum(np.arange(len(age_probs)) * age_probs))

            # Confidence from peak probability
            peak_prob = np.max(age_probs)
            age_conf = min(1.0, peak_prob * 8)

            # Gender
            gender_probs = np.exp(gender_logits - np.max(gender_logits))
            gender_probs = gender_probs / np.sum(gender_probs)
            gender = "male" if np.argmax(gender_probs) == 0 else "female"
            gender_conf = float(np.max(gender_probs))

            return {
                "age": max(0, min(90, expected_age)),
                "gender": gender,
                "age_confidence": age_conf,
                "gender_confidence": gender_conf,
                "confidence": (age_conf + gender_conf) / 2,
                "source": "mivolo"
            }

        except Exception as e:
            logger.debug(f"MiVOLO prediction failed: {e}")
            return None

    def predict_dex(self, face_crop):
        """
        Predict age using DEX-Age (face only).
        Returns {"age": int, "gender": str, "confidence": float}.
        """
        if self.dex_sess is None:
            return {"age": 25, "gender": "unknown", "confidence": 0.0, "source": "none"}

        try:
            rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
            blob = cv2.resize(rgb, (96, 96)).astype(np.float32)
            blob = (blob - 128.0) / 128.0
            blob = blob.transpose(2, 0, 1)[np.newaxis, :]

            input_name = self.dex_sess.get_inputs()[0].name
            outs = self.dex_sess.run(None, {input_name: blob})

            probs = outs[0][0].flatten()
            probs = np.clip(probs, 0, None)
            total = np.sum(probs)
            if total > 0:
                probs = probs / total

            expected_age = int(np.sum(np.arange(len(probs)) * probs))
            peak_prob = np.max(probs)
            confidence = min(1.0, peak_prob * 5)

            # Apply calibration (same as vision_pipeline)
            calibrated_age = self._calibrate_age(expected_age)

            return {
                "age": calibrated_age,
                "gender": "unknown",  # DEX doesn't predict gender
                "age_confidence": confidence,
                "gender_confidence": 0.0,
                "confidence": confidence * 0.8,  # Slightly lower than MiVOLO
                "source": "dex"
            }

        except Exception as e:
            logger.debug(f"DEX prediction failed: {e}")
            return {"age": 25, "gender": "unknown", "confidence": 0.0, "source": "error"}

    def _calibrate_age(self, raw_age):
        """Apply DEX age calibration (same as vision_pipeline)."""
        calibration = [
            (0, 3, 4.0), (3, 6, 3.5), (6, 10, 3.0), (10, 15, 2.5),
            (15, 20, 2.2), (20, 25, 2.0), (25, 30, 1.8), (30, 40, 1.5),
            (40, 50, 1.3), (50, 90, 1.2),
        ]
        for low, high, multiplier in calibration:
            if low <= raw_age < high:
                return max(3, min(90, int(raw_age * multiplier)))
        return max(3, min(90, int(raw_age * 1.2)))

    def _smooth_prediction(self, age, gender, confidence):
        """Apply temporal smoothing for stable predictions."""
        self.age_history.append((age, confidence))
        if gender != "unknown":
            self.gender_history.append(gender)

        if len(self.age_history) < 3:
            return age, gender, confidence

        # Exponential temporal weighting
        ages = []
        confs = []
        time_weights = []

        for i, (a, c) in enumerate(self.age_history):
            w = np.exp(i / len(self.age_history))
            ages.append(a)
            confs.append(max(0.1, c))
            time_weights.append(w)

        combined_weights = np.array(confs) * np.array(time_weights)
        combined_weights = combined_weights / np.sum(combined_weights)
        smoothed_age = int(np.average(ages, weights=combined_weights))

        # Outlier rejection
        median_age = np.median(ages)
        if abs(smoothed_age - median_age) > 15:
            smoothed_age = int(median_age)

        # Gender: most common recent
        if self.gender_history:
            from collections import Counter
            gender_counts = Counter(self.gender_history)
            smoothed_gender = gender_counts.most_common(1)[0][0]
        else:
            smoothed_gender = gender

        return max(3, min(90, smoothed_age)), smoothed_gender, confidence

    def predict(self, face_crop, body_crop=None):
        """
        Main prediction entry point.
        Tries MiVOLO first, falls back to DEX-Age.
        Applies temporal smoothing for stable output.

        Args:
            face_crop: Face image (BGR numpy array)
            body_crop: Optional body image (for MiVOLO)

        Returns:
            {"age": int, "gender": str, "confidence": float, "source": str}
        """
        if face_crop is None or face_crop.size == 0:
            return {"age": 25, "gender": "unknown", "confidence": 0.0, "source": "no_input"}

        # Try MiVOLO first (if tier 2/3 and model loaded)
        if self.mivolo_sess is not None:
            result = self.predict_mivolo(face_crop, body_crop)
            if result is not None and result["confidence"] > 0.1:
                age, gender, conf = self._smooth_prediction(
                    result["age"], result["gender"], result["confidence"]
                )
                result["age"] = age
                result["gender"] = gender
                result["confidence"] = conf
                return result

        # Fallback to DEX-Age
        result = self.predict_dex(face_crop)
        age, gender, conf = self._smooth_prediction(
            result["age"], result["gender"], result["confidence"]
        )
        result["age"] = age
        result["gender"] = gender
        result["confidence"] = conf
        return result

    def reset_history(self):
        """Clear temporal smoothing history."""
        self.age_history.clear()
        self.gender_history.clear()

    def get_status(self):
        """Get engine status."""
        return {
            "tier": self.tier,
            "mivolo_available": self.mivolo_sess is not None,
            "dex_available": self.dex_sess is not None,
            "primary_source": "mivolo" if self.mivolo_sess else "dex",
            "age_history_length": len(self.age_history),
        }
