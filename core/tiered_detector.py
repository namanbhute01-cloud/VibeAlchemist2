"""
Tiered detection: run fast detector on 240p, extract ROI from full-res.
Saves ~60% CPU vs running on full resolution.

Workflow:
    1. Downscale full frame to DETECTION_SCALE height (default 240p)
    2. Run YOLOv8n-face on downscaled frame (fast)
    3. Scale bounding boxes back to original resolution
    4. Extract face_crop (upper ~40%) and body_crop (full bbox) from full-res frame

Returns list of dicts:
    {bbox_full, face_crop, body_crop, confidence}
"""
import cv2
import numpy as np
import os
import logging
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class TieredDetector:
    def __init__(self):
        model_path = os.getenv("YOLO_FACE_MODEL", "models/yolov8n-face.pt")

        # Try .pt first, then .onnx fallback
        if not os.path.exists(model_path):
            onnx_path = model_path.replace(".pt", ".onnx")
            if os.path.exists(onnx_path):
                model_path = onnx_path
                logger.info(f"TieredDetector: using ONNX fallback {onnx_path}")
            else:
                logger.warning(
                    f"TieredDetector: model not found at {model_path} — "
                    "detection disabled. Run scripts/download_models.py"
                )
                self._model = None
                self._scale_height = int(os.getenv("DETECTION_SCALE", 240))
                return

        self._model = YOLO(model_path)
        self._scale_height = int(os.getenv("DETECTION_SCALE", 240))
        logger.info(
            f"TieredDetector loaded: {model_path} "
            f"(scale={self._scale_height}px height)"
        )

    def detect(self, full_frame: np.ndarray) -> list:
        """
        Run detection on downscaled frame.
        :param full_frame: Original resolution frame (BGR numpy array).
        :returns: List of dicts with bbox_full, face_crop, body_crop, confidence.
                  Returns empty list if model not loaded or no detections.
        """
        if self._model is None:
            return []

        h, w = full_frame.shape[:2]
        if h == 0 or w == 0:
            return []

        scale = self._scale_height / h
        small = cv2.resize(full_frame, (int(w * scale), self._scale_height))

        # classes=[0] = person class in COCO
        results = self._model(small, verbose=False, classes=[0])
        detections = []

        if not results or not results[0].boxes:
            return detections

        for box in results[0].boxes:
            conf = float(box.conf[0])
            min_conf = float(os.getenv("PERSON_DETECTION_CONF", 0.4))
            if conf < min_conf:
                continue

            # Scale bbox back to full resolution
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            x1 = int(x1 / scale)
            y1 = int(y1 / scale)
            x2 = int(x2 / scale)
            y2 = int(y2 / scale)

            # Clamp to frame boundaries
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)

            # Validate box size
            if x2 - x1 < 10 or y2 - y1 < 10:
                continue

            body_crop = full_frame[y1:y2, x1:x2]

            # Face crop = upper 40% of body box (approximate face region)
            face_h = int((y2 - y1) * 0.40)
            face_crop = full_frame[y1:y1 + face_h, x1:x2]

            if body_crop.size == 0 or face_crop.size == 0:
                continue

            detections.append({
                "bbox_full": np.array([x1, y1, x2, y2]),
                "face_crop": face_crop,
                "body_crop": body_crop,
                "confidence": conf,
            })

        # Sort by bbox area (largest person first — primary subject)
        detections.sort(
            key=lambda d: (d["bbox_full"][2] - d["bbox_full"][0])
            * (d["bbox_full"][3] - d["bbox_full"][1]),
            reverse=True,
        )
        return detections
