"""
Tiered detection: run fast detector on 240p, extract ROI from full-res.
Saves ~60% CPU vs running on full resolution.

Supports two backends:
  1. RetinaFace (default, if model available) - robust to profile views
  2. YOLOv8n-face (fallback) - fast but less accurate on extreme angles

Workflow:
    1. Downscale full frame to DETECTION_SCALE height (default 240p)
    2. Run detector on downscaled frame (fast)
    3. Scale bounding boxes back to original resolution
    4. Extract face_crop and body_crop from full-res frame

Returns list of dicts:
    {bbox_full, face_crop, body_crop, confidence, landmarks}
"""
import cv2
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)


class TieredDetector:
    def __init__(self):
        self._scale_height = int(os.getenv("DETECTION_SCALE", 240))
        self._detector_type = "none"

        # Try RetinaFace first (superior accuracy, profile view support)
        self._retinaface = None
        self._yolo_model = None

        retinaface_path = os.getenv(
            "RETINAFACE_MODEL", "models/retinaface_mobilenet_int8.onnx"
        )
        if os.path.exists(retinaface_path):
            try:
                from core.retinaface_detector import RetinaFaceDetector

                self._retinaface = RetinaFaceDetector()
                if self._retinaface._use_retinaface:
                    self._detector_type = "retinaface"
                    logger.info(
                        f"TieredDetector: using RetinaFace "
                        f"(scale={self._scale_height}px height)"
                    )
                else:
                    self._detector_type = "none"
            except Exception as e:
                logger.warning(f"RetinaFace init failed: {e}")

        # Fallback to YOLOv8n-face
        if self._detector_type == "none":
            yolo_path = os.getenv("YOLO_FACE_MODEL", "models/yolov8n-face.pt")

            # Try .pt first, then .onnx fallback
            if not os.path.exists(yolo_path):
                onnx_path = yolo_path.replace(".pt", ".onnx")
                if os.path.exists(onnx_path):
                    yolo_path = onnx_path

            if os.path.exists(yolo_path):
                try:
                    from ultralytics import YOLO

                    self._yolo_model = YOLO(yolo_path)
                    self._detector_type = "yolo"
                    logger.info(
                        f"TieredDetector: using YOLOv8n-face fallback "
                        f"(scale={self._scale_height}px height)"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load YOLO fallback: {e}")
            else:
                logger.warning(
                    f"TieredDetector: no face detector available. "
                    f"Run: python scripts/download_models.py"
                )

    def detect(self, full_frame: np.ndarray) -> list:
        """
        Run detection on downscaled frame.
        :param full_frame: Original resolution frame (BGR numpy array).
        :returns: List of dicts with bbox_full, face_crop, body_crop, confidence.
                  Returns empty list if model not loaded or no detections.
        """
        if full_frame is None or full_frame.size == 0:
            return []

        if self._detector_type == "retinaface" and self._retinaface:
            return self._detect_retinaface(full_frame)
        elif self._detector_type == "yolo" and self._yolo_model:
            return self._detect_yolo(full_frame)
        else:
            return []

    def _detect_retinaface(self, full_frame: np.ndarray) -> list:
        """Use RetinaFace for detection (supports profile views)."""
        try:
            detections = self._retinaface.detect(full_frame)
            results = []

            for det in detections:
                x1, y1, x2, y2 = det["bbox"]
                h, w = full_frame.shape[:2]

                # Clamp
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w, x2)
                y2 = min(h, y2)

                bw, bh = x2 - x1, y2 - y1
                if bw < 20 or bh < 20:
                    continue

                body_crop = full_frame[y1:y2, x1:x2]

                # Face crop = face bounding box (RetinaFace gives tight face box)
                face_crop = det.get("face_crop", body_crop)
                if face_crop.size == 0:
                    face_crop = body_crop

                results.append(
                    {
                        "bbox_full": np.array([x1, y1, x2, y2]),
                        "face_crop": face_crop,
                        "body_crop": body_crop,
                        "confidence": det["confidence"],
                        "landmarks": det.get("landmarks", []),
                    }
                )

            # Sort by bbox area (largest face first)
            results.sort(
                key=lambda d: (d["bbox_full"][2] - d["bbox_full"][0])
                * (d["bbox_full"][3] - d["bbox_full"][1]),
                reverse=True,
            )
            return results

        except Exception as e:
            logger.error(f"RetinaFace tiered detection error: {e}")
            return []

    def _detect_yolo(self, full_frame: np.ndarray) -> list:
        """Use YOLOv8n-face for detection (fallback)."""
        h, w = full_frame.shape[:2]
        if h == 0 or w == 0:
            return []

        scale = self._scale_height / h
        small = cv2.resize(full_frame, (int(w * scale), self._scale_height))

        # classes=[0] = person class in COCO
        results = self._yolo_model(small, verbose=False, classes=[0])
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
            face_crop = full_frame[y1 : y1 + face_h, x1:x2]

            if body_crop.size == 0 or face_crop.size == 0:
                continue

            detections.append(
                {
                    "bbox_full": np.array([x1, y1, x2, y2]),
                    "face_crop": face_crop,
                    "body_crop": body_crop,
                    "confidence": conf,
                    "landmarks": [],
                }
            )

        # Sort by bbox area (largest person first - primary subject)
        detections.sort(
            key=lambda d: (d["bbox_full"][2] - d["bbox_full"][0])
            * (d["bbox_full"][3] - d["bbox_full"][1]),
            reverse=True,
        )
        return detections
