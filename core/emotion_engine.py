"""
MobileNet-V2 FER: 7-class emotion detection with temporal smoothing.
Smoothing prevents "emotion flicker" from causing constant music changes.

Input:  face_crop (BGR numpy array, any size)
Output: {emotion: str, scores: dict[str, float], energy: float}

Emotion labels: angry, disgust, fear, happy, neutral, sad, surprise
Energy = weighted sum of happy (0.6) + surprise (0.4), clamped [0, 1].

Uses a rolling average over EMOTION_SMOOTHING_FRAMES (default 5) to stabilize.
Only emits a new dominant emotion if it persists for 3+ consecutive detections.
"""
import cv2
import numpy as np
import os
import logging
from collections import deque
import onnxruntime as ort

logger = logging.getLogger(__name__)

EMOTION_LABELS = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]


class EmotionEngine:
    def __init__(self):
        model_path = os.getenv("FER_MODEL", "models/mobilenet_fer_int8.onnx")
        self._session = None
        self._input_name = None

        smooth_n = int(os.getenv("EMOTION_SMOOTHING_FRAMES", 5))
        self._history: deque = deque(maxlen=smooth_n)

        # Persistence counter to prevent flicker
        self._last_stable_emotion = "neutral"
        self._persistence_count = 0
        self._min_persistence = 3

        if os.path.exists(model_path):
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

                self._session = ort.InferenceSession(
                    model_path,
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._input_name = self._session.get_inputs()[0].name
                logger.info("EmotionEngine loaded MobileNet FER")
            except Exception as e:
                logger.warning(f"Failed to load FER model: {e} — emotion disabled")
                self._session = None
        else:
            logger.warning(
                f"FER model not found at {model_path} — emotion disabled. "
                f"Run: python scripts/download_models.py"
            )

    def detect(self, face_crop: np.ndarray) -> dict:
        """
        Detect emotion from face crop with temporal smoothing.
        :param face_crop: BGR numpy array of face region.
        :returns: {emotion: str, scores: dict, energy: float}
        """
        if self._session is None:
            return {"emotion": "neutral", "scores": {}, "energy": 0.5}

        if face_crop is None or face_crop.size == 0:
            return {"emotion": self._last_stable_emotion, "scores": {}, "energy": 0.5}

        try:
            # Convert to grayscale, resize to 48x48, normalize
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (48, 48)).astype(np.float32) / 255.0
            inp = gray[np.newaxis, np.newaxis]  # NCHW grayscale

            out = self._session.run(None, {self._input_name: inp})[0][0]
            scores = dict(zip(EMOTION_LABELS, out.tolist()))
            self._history.append(scores)

            # Temporal smoothing: average scores over history
            avg = {}
            for label in EMOTION_LABELS:
                avg[label] = sum(s[label] for s in self._history) / len(self._history)

            best = max(avg, key=avg.get)

            # Persistence check: only switch if emotion persists 3+ frames
            if best == self._last_stable_emotion:
                self._persistence_count += 1
            else:
                self._persistence_count = 0
                if self._persistence_count >= self._min_persistence - 1:
                    # Just reached threshold — allow switch
                    self._last_stable_emotion = best
                    self._persistence_count = 0
                # else: keep using last_stable_emotion

            # Use the stable emotion for the return value
            emotion_to_return = self._last_stable_emotion

            # Energy = happy + surprise weighted sum (0 to 1)
            energy = min(1.0, avg.get("happy", 0) * 0.6 + avg.get("surprise", 0) * 0.4)

            return {"emotion": emotion_to_return, "scores": avg, "energy": energy}

        except Exception as e:
            logger.error(f"EmotionEngine error: {e}")
            return {"emotion": "neutral", "scores": {}, "energy": 0.5}
