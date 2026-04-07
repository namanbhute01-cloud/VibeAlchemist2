"""
RetinaFace: High-precision face detector robust to extreme angles,
profile views, occlusion, and low-light conditions.

Unlike YOLOv8n-face, RetinaFace detects faces at:
  - Profile views (up to 90 degrees)
  - Extreme pitch (looking up/down)
  - Heavy occlusion (partial face visible)
  - Low-light / high-noise conditions

Uses INT8-quantized ONNX for 3-4x speed on CPU.

Graceful degradation: Falls back to YOLOv8n-face if RetinaFace model missing.
"""
import cv2
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)


class RetinaFaceDetector:
    """
    RetinaFace face detector using ONNX Runtime.
    Supports both the standard RetinaFace output format and
    simplified Ultralytics-exported format.
    """

    def __init__(self):
        model_path = os.getenv(
            "RETINAFACE_MODEL", "models/retinaface_mobilenet_int8.onnx"
        )
        self._session = None
        self._use_retinaface = False

        # YOLO fallback
        self._yolo_model = None

        # Detection parameters
        self._conf_threshold = float(os.getenv("FACE_DETECTION_CONF", 0.5))
        self._nms_threshold = 0.4

        if os.path.exists(model_path):
            try:
                import onnxruntime as ort

                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.inter_op_num_threads = 1
                opts.graph_optimization_level = (
                    ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                )

                self._session = ort.InferenceSession(
                    model_path,
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._use_retinaface = True

                # Detect input format
                self._input_name = self._session.get_inputs()[0].name
                self._input_shape = self._session.get_inputs()[0].shape
                self._output_names = [o.name for o in self._session.get_outputs()]

                logger.info(
                    f"RetinaFaceDetector loaded: {model_path} "
                    f"(input={self._input_shape}, outputs={self._output_names})"
                )
            except Exception as e:
                logger.warning(f"Failed to load RetinaFace: {e}")
                self._use_retinaface = False
        else:
            logger.warning(
                f"RetinaFace model not found at {model_path}. "
                f"Falling back to YOLOv8n-face. "
                f"Run: python scripts/download_models.py"
            )

        # Load YOLO fallback if RetinaFace unavailable
        if not self._use_retinaface:
            self._load_yolo_fallback()

    def _load_yolo_fallback(self):
        """Load YOLOv8n-face as fallback detector."""
        try:
            from ultralytics import YOLO

            yolo_path = os.getenv("YOLO_FACE_MODEL", "models/yolov8n-face.pt")
            if os.path.exists(yolo_path):
                self._yolo_model = YOLO(yolo_path)
                logger.info("RetinaFaceDetector: using YOLOv8n-face fallback")
            else:
                # Try .onnx version
                onnx_path = yolo_path.replace(".pt", ".onnx")
                if os.path.exists(onnx_path):
                    self._yolo_model = YOLO(onnx_path)
                    logger.info(
                        "RetinaFaceDetector: using YOLOv8n-face ONNX fallback"
                    )
                else:
                    logger.warning(
                        "No face detector available - detection disabled"
                    )
        except Exception as e:
            logger.error(f"Failed to load YOLO fallback: {e}")

    def detect(self, image: np.ndarray) -> list:
        """
        Detect faces in image.
        :param image: BGR numpy array (any resolution).
        :returns: List of {bbox: [x1,y1,x2,y2], landmarks: 5pts,
                          confidence: float, face_crop: np.ndarray}
        """
        if image is None or image.size == 0:
            return []

        if self._use_retinaface:
            return self._detect_retinaface(image)
        else:
            return self._detect_yolo_fallback(image)

    def _detect_retinaface(self, image: np.ndarray) -> list:
        """Run RetinaFace detection with NMS."""
        try:
            h_orig, w_orig = image.shape[:2]

            # Resize to model input size
            input_shape = self._input_shape
            if isinstance(input_shape[2], int):
                target_h, target_w = input_shape[2], input_shape[3]
            else:
                # Dynamic input size - use 640x640
                target_h, target_w = 640, 640

            img_resized = cv2.resize(image, (target_w, target_h))
            img_blob = img_resized.astype(np.float32)

            # Normalize to [0, 1] if model expects it
            if img_blob.max() > 1.0:
                img_blob = img_blob / 255.0

            # Add batch dimension if needed
            if img_blob.ndim == 3:
                img_blob = np.expand_dims(img_blob, axis=0)

            # Transpose to NCHW if needed
            if self._input_name and "input" in self._session.get_inputs()[0].name:
                # Check if model expects NCHW
                input_info = self._session.get_inputs()[0]
                if len(input_info.shape) == 4 and input_info.shape[1] == 3:
                    img_blob = img_blob.transpose(0, 3, 1, 2)

            # Run inference
            outputs = self._session.run(None, {self._input_name: img_blob})

            # Parse outputs - handle different export formats
            detections = self._parse_outputs(
                outputs, h_orig, w_orig, target_h, target_w
            )

            # Apply NMS
            if len(detections) > 1:
                detections = self._nms(detections)

            return detections

        except Exception as e:
            logger.error(f"RetinaFace detection error: {e}")
            return self._detect_yolo_fallback(image)

    def _parse_outputs(
        self, outputs, h_orig, w_orig, target_h, target_w
    ) -> list:
        """
        Parse RetinaFace outputs - handles multiple export formats.
        Common formats:
          1. Ultralytics export: N x 6 (x1, y1, x2, y2, conf, class)
          2. Standard RetinaFace: [loc, conf, landms] separate outputs
          3. Simplified ONNX: N x 16 (x1, y1, x2, y2, conf, 5x landmarks)
        """
        detections = []
        scale_x = w_orig / target_w
        scale_y = h_orig / target_h

        if len(outputs) == 1 and outputs[0].ndim == 2:
            # Format 1 or 3: single output with N detections
            raw = outputs[0][0] if outputs[0].ndim == 3 else outputs[0]

            for det in raw:
                if len(det) < 5:
                    continue

                # Check if this is Ultralytics format (x1,y1,x2,y2,conf,class)
                if len(det) >= 6:
                    x1, y1, x2, y2, conf, cls = det[:6]
                    if conf < self._conf_threshold:
                        continue

                    # Scale back to original resolution
                    x1 = int(x1 * scale_x)
                    y1 = int(y1 * scale_y)
                    x2 = int(x2 * scale_x)
                    y2 = int(y2 * scale_y)
                elif len(det) >= 5:
                    x1, y1, x2, y2, conf = det[:5]
                    if conf < self._conf_threshold:
                        continue

                    x1 = int(x1 * scale_x)
                    y1 = int(y1 * scale_y)
                    x2 = int(x2 * scale_x)
                    y2 = int(y2 * scale_y)
                else:
                    continue

                # Clamp
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w_orig, x2)
                y2 = min(h_orig, y2)

                # Validate box
                bw, bh = x2 - x1, y2 - y1
                if bw < 20 or bh < 20:
                    continue

                # Extract landmarks if available (15 values after bbox+conf)
                landmarks = []
                if len(det) >= 15:
                    landmarks = [
                        (int(det[i] * scale_x), int(det[i + 1] * scale_y))
                        for i in range(5, 15, 2)
                    ]

                face_crop = image[y1:y2, x1:x2].copy()

                detections.append(
                    {
                        "bbox": np.array([x1, y1, x2, y2]),
                        "landmarks": landmarks,
                        "confidence": float(conf),
                        "face_crop": face_crop,
                        "face_size": max(bw, bh),
                    }
                )

        elif len(outputs) >= 2:
            # Format 2: separate loc, conf, landms outputs
            raw_boxes = outputs[0][0]
            raw_conf = outputs[1][0]

            for i in range(len(raw_conf)):
                conf = raw_conf[i]
                if conf < self._conf_threshold:
                    continue

                box = raw_boxes[i]
                if len(box) < 4:
                    continue

                x1, y1, x2, y2 = box[:4]
                x1 = int(x1 * scale_x)
                y1 = int(y1 * scale_y)
                x2 = int(x2 * scale_x)
                y2 = int(y2 * scale_y)

                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w_orig, x2)
                y2 = min(h_orig, y2)

                bw, bh = x2 - x1, y2 - y1
                if bw < 20 or bh < 20:
                    continue

                face_crop = image[y1:y2, x1:x2].copy()
                landmarks = []
                if len(outputs) >= 3:
                    raw_landms = outputs[2][0]
                    if i < len(raw_landms) and len(raw_landms[i]) >= 10:
                        lm = raw_landms[i]
                        landmarks = [
                            (int(lm[j] * scale_x), int(lm[j + 1] * scale_y))
                            for j in range(0, 10, 2)
                        ]

                detections.append(
                    {
                        "bbox": np.array([x1, y1, x2, y2]),
                        "landmarks": landmarks,
                        "confidence": float(conf),
                        "face_crop": face_crop,
                        "face_size": max(bw, bh),
                    }
                )

        return detections

    def _detect_yolo_fallback(self, image: np.ndarray) -> list:
        """Fallback to YOLOv8n-face detection."""
        if self._yolo_model is None:
            return []

        try:
            results = self._yolo_model(
                image, verbose=False, conf=self._conf_threshold
            )
            detections = []

            if results and results[0].boxes:
                h, w = image.shape[:2]
                for box in results[0].boxes:
                    conf = float(box.conf[0])
                    if conf < self._conf_threshold:
                        continue

                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = min(w, x2)
                    y2 = min(h, y2)

                    face_crop = image[y1:y2, x1:x2].copy()
                    bw, bh = x2 - x1, y2 - y1

                    detections.append(
                        {
                            "bbox": np.array([x1, y1, x2, y2]),
                            "landmarks": [],
                            "confidence": conf,
                            "face_crop": face_crop,
                            "face_size": max(bw, bh),
                        }
                    )

            return detections

        except Exception as e:
            logger.error(f"YOLO fallback detection error: {e}")
            return []

    @staticmethod
    def _nms(detections: list) -> list:
        """Non-Maximum Suppression to remove duplicate face detections."""
        if len(detections) <= 1:
            return detections

        boxes = np.array([d["bbox"] for d in detections], dtype=np.float32)
        scores = np.array([d["confidence"] for d in detections])

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(detections[i])

            if order.size == 1:
                break

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0, xx2 - xx1)
            h = np.maximum(0, yy2 - yy1)
            inter = w * h

            iou = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(iou <= 0.4)[0]
            order = order[inds + 1]

        return keep
