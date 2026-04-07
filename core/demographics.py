"""
MiVOLO XX-Small: age + gender estimation from face crop + body crop.
Multi-input model handles occlusion better than face-only approaches.

Falls back to body-only if face crop is not usable.
Falls back to defaults if model file is missing entirely.

Input:  face_crop (any size, resized to 112x112 internally)
        body_crop (any size, resized to 192x256 internally)
Output: {age: float, gender: str, confidence: float}
"""
import cv2
import numpy as np
import os
import logging
import onnxruntime as ort

logger = logging.getLogger(__name__)

GENDER_LABELS = ["male", "female"]

# ImageNet normalization constants
_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]


class DemographicsEngine:
    def __init__(self):
        model_path = os.getenv("MIVOLO_MODEL", "models/mivolo_xxs.onnx")
        self._session = None
        self._input_names = None

        if os.path.exists(model_path):
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.inter_op_num_threads = 1
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

                self._session = ort.InferenceSession(
                    model_path,
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._input_names = [inp.name for inp in self._session.get_inputs()]
                logger.info(
                    f"DemographicsEngine loaded MiVOLO XX-Small "
                    f"(inputs: {self._input_names})"
                )
            except Exception as e:
                logger.warning(f"Failed to load MiVOLO model: {e} — demographics disabled")
                self._session = None
        else:
            logger.warning(
                f"MiVOLO model not found at {model_path} — demographics disabled. "
                f"Run: python scripts/download_models.py"
            )

    @staticmethod
    def _preprocess(img: np.ndarray, size: tuple) -> np.ndarray:
        """
        Resize, convert to RGB, normalize with ImageNet stats, return NCHW tensor.
        """
        img = cv2.resize(img, size)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = (img - _IMAGENET_MEAN) / _IMAGENET_STD
        return img.transpose(2, 0, 1)[np.newaxis]  # NCHW

    def estimate(self, face_crop: np.ndarray, body_crop: np.ndarray) -> dict:
        """
        Estimate age and gender from face+body crops.
        :param face_crop: BGR numpy array of face region.
        :param body_crop: BGR numpy array of body region.
        :returns: {age: float, gender: str, confidence: float}
        """
        if self._session is None:
            return {"age": 25.0, "gender": "unknown", "confidence": 0.0}

        if face_crop is None or face_crop.size == 0:
            # Try body-only fallback
            if body_crop is not None and body_crop.size > 0:
                face_crop = body_crop  # use body as proxy for face
            else:
                return {"age": 25.0, "gender": "unknown", "confidence": 0.0}

        try:
            face_in = self._preprocess(face_crop, (112, 112))
            body_in = self._preprocess(body_crop, (192, 256))

            # Build input dict based on model's expected input names
            feed = {}
            if len(self._input_names) >= 2:
                feed[self._input_names[0]] = face_in
                feed[self._input_names[1]] = body_in
            else:
                # Single-input MiVOLO variant (concatenated internally)
                feed[self._input_names[0]] = face_in

            outputs = self._session.run(None, feed)

            # Output 0 = age (scalar), Output 1 = gender logits (2 values)
            age = float(outputs[0][0])
            gender_logits = outputs[1][0]
            gender_idx = int(np.argmax(gender_logits))
            confidence = float(np.max(gender_logits))

            return {
                "age": max(0.0, min(100.0, age)),
                "gender": GENDER_LABELS[gender_idx],
                "confidence": float(np.clip(confidence, 0.0, 1.0)),
            }
        except Exception as e:
            logger.error(f"DemographicsEngine error: {e}")
            return {"age": 25.0, "gender": "unknown", "confidence": 0.0}
