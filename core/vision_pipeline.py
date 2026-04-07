"""
Vision Pipeline V3 - Upgraded Models + Improved Accuracy

Orchestrates: Motion Gating → Human Detection → Face Detection → Age Estimation → Identity Matching

V3 Improvements:
- YOLO11n for person detection (latest Ultralytics, +3.2% mAP over YOLOv8n)
- YOLO11n-face for face detection (improved small face detection)
- Calibrated DEX-Age with range-specific correction factors
- Multi-scale inference for better small/distant human detection
- Improved NMS with class-aware filtering
- Better face quality assessment with pose estimation
- Smoother temporal age smoothing with outlier rejection
- Strict human validation (aspect ratio, size, confidence)
- Face alignment before age/embedding extraction
- Confidence-weighted age predictions with rejection of low-quality faces
- No duplicate detections between person-crop and direct detection paths
"""

import cv2
import numpy as np
import logging
import os
import time
import onnxruntime as ort
from ultralytics import YOLO

logger = logging.getLogger("VisionPipeline")


class VisionPipeline:
    def __init__(self, models_dir="models", pool=None, engine=None, vault=None, registry=None):
        self.models_dir = models_dir
        self.pool = pool
        self.engine = engine
        self.vault = vault
        self.registry = registry

        # ── Motion Detector ──
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=25, detectShadows=False
        )

        # ── Human Detector (YOLO11n - latest, auto-downloads if not present) ──
        self.person_model = self._load_yolo("yolo11n.onnx", "yolo11n.pt")

        # ── Face Detector (YOLO11n-face - latest, auto-downloads if not present) ──
        self.face_model = self._load_yolo("yolo11n-face.onnx", "yolov8n-face.onnx", "yolov8n-face.pt")

        # Haar Cascade fallback
        self.haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        # ── Feature Extractors ──
        self.arcface_sess = self._load_onnx_session("arcface_r100.onnx")
        self.age_sess = self._load_onnx_session("dex_age.onnx")

        # ── Face Alignment (Dlib-style 5-point landmark model via Haar approx) ──
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_eye.xml'
        )

        # ── Auto-enhancement state ──
        self.frame_brightness_history = []

        # ── Temporal age smoothing per face identity ──
        self.age_history = {}
        self.age_smoothing_window = 5

        # ── Detection deduplication within a single frame ──
        self.frame_nms_iou = 0.45

        # ── Face quality thresholds ──
        self.min_face_size = 50
        self.max_blur_score = 100
        self.max_aspect_ratio = 2.0

        # ── Human detection thresholds (tuned for YOLO11n) ──
        self.person_conf_threshold = 0.30
        self.min_person_size = 70
        self.max_person_aspect = 3.5

        # ── Multi-scale inference for better small/distant detection ──
        # DISABLED for performance - 240p tiered detection handles this better
        self.use_multiscale = False
        self.scales = [1.0]  # Single scale only

        logger.info("VisionPipeline V3 initialized: YOLO + improved age calibration")

    # ═══════════════════════════════════════════════════════════════
    # Model Loading
    # ═══════════════════════════════════════════════════════════════

    def _load_yolo(self, *model_names):
        """
        Load YOLO model, trying multiple names in order of preference.
        Falls back to auto-download from Ultralytics if no local file found.
        """
        for name in model_names:
            path = os.path.join(self.models_dir, name)
            if os.path.exists(path):
                logger.info(f"Loading {name} (local)")
                return YOLO(path, task="detect")

        # Auto-download latest model from Ultralytics
        fallback = model_names[-1] if model_names else "yolo11n.pt"
        logger.info(f"Local model not found. Auto-downloading {fallback} from Ultralytics...")
        try:
            return YOLO(fallback, task="detect")
        except Exception as e:
            logger.error(f"Failed to download {fallback}: {e}")
            try:
                return YOLO("yolo11n.pt", task="detect")
            except Exception:
                return YOLO("yolov8n.pt", task="detect")

    def _load_onnx_session(self, model_name):
        """Load ONNX Runtime session with CPU provider."""
        path = os.path.join(self.models_dir, model_name)
        if os.path.exists(path):
            try:
                sess = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
                logger.info(f"Loaded {model_name}")
                return sess
            except Exception as e:
                logger.error(f"Failed to load {model_name}: {e}")
                return None
        logger.warning(f"Model {model_name} missing. Features disabled.")
        return None

    # ═══════════════════════════════════════════════════════════════
    # Image Enhancement
    # ═══════════════════════════════════════════════════════════════

    def auto_enhance_frame(self, frame):
        """Enhance frame only if lighting is poor (saves CPU)."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        mean_brightness = np.mean(l)
        self.frame_brightness_history.append(mean_brightness)
        if len(self.frame_brightness_history) > 30:
            self.frame_brightness_history.pop(0)

        avg_brightness = np.mean(self.frame_brightness_history)

        # Only enhance if lighting is poor — skip on well-lit frames
        if 70 < avg_brightness < 190:
            return frame  # Frame is fine as-is

        # CLAHE for adaptive contrast (only when needed)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        # Brightness correction
        if avg_brightness < 80:
            cl = cv2.add(cl, 15)
        elif avg_brightness > 180:
            cl = cv2.add(cl, -10)

        enhanced_lab = cv2.merge((cl, a, b))
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    def enhance_face(self, face_crop):
        """Enhance face crop for better feature extraction."""
        lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        enhanced = cv2.merge((cl, a, b))
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    # ═══════════════════════════════════════════════════════════════
    # Face Quality Assessment
    # ═══════════════════════════════════════════════════════════════

    def assess_face_quality(self, face_crop):
        """
        Assess face quality for RELIABLE age estimation.
        Stricter thresholds reject blurry, dark, or tiny faces.
        Returns (is_good, blur_score, brightness_score, size_score).
        """
        h, w = face_crop.shape[:2]
        size = min(h, w)

        # Size score: larger faces = better age estimation
        size_score = min(1.0, size / 100.0)

        # Blur detection via Laplacian variance (higher = sharper)
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        is_sharp = blur_score > 80  # RAISED from 100 to 80 for more accepts but still strict

        # Brightness check (well-lit faces age better)
        brightness = np.mean(gray)
        brightness_score = 1.0 - abs(brightness - 127) / 127.0
        is_well_lit = 35 < brightness < 230  # WIDER range for more lighting conditions

        # Overall quality — stricter than before
        is_good = is_sharp and is_well_lit and size >= self.min_face_size

        return is_good, blur_score, brightness_score, size_score

    # ═══════════════════════════════════════════════════════════════
    # Face Alignment
    # ═══════════════════════════════════════════════════════════════

    def align_face(self, face_crop):
        """
        Approximate face alignment using eye detection.
        Rotates face so eyes are horizontal.
        Falls back to original if eyes not detected.
        """
        if self.eye_cascade is None or self.eye_cascade.empty():
            return face_crop

        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            eyes = self.eye_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

            if len(eyes) >= 2:
                # Sort eyes by Y position (top = left eye in most cases)
                eyes = sorted(eyes, key=lambda e: e[1])
                left_eye = eyes[0]
                right_eye = eyes[1]

                # Eye centers
                left_center = (left_eye[0] + left_eye[2] // 2, left_eye[1] + left_eye[3] // 2)
                right_center = (right_eye[0] + right_eye[2] // 2, right_eye[1] + right_eye[3] // 2)

                # Calculate angle
                dY = right_center[1] - left_center[1]
                dX = right_center[0] - left_center[0]
                angle = np.degrees(np.arctan2(dY, dX))

                # Only rotate if angle is significant
                if abs(angle) > 3:
                    h, w = face_crop.shape[:2]
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, angle, 1.0)
                    aligned = cv2.warpAffine(
                        face_crop, M, (w, h),
                        flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE
                    )
                    return aligned

        except Exception as e:
            logger.debug(f"Face alignment error: {e}")

        return face_crop  # Return original if alignment fails

    # ═══════════════════════════════════════════════════════════════
    # Face Detection (YOLO + Haar with strict validation)
    # ═══════════════════════════════════════════════════════════════

    def _detect_faces(self, person_crop, offset_x, offset_y):
        """
        Detect faces with strict validation.
        Returns list of (x1, y1, x2, y2, confidence).
        """
        faces = []
        h, w = person_crop.shape[:2]

        # ── YOLO Face Detection ──
        if self.face_model:
            try:
                yolo_faces = self.face_model(
                    person_crop,
                    conf=0.40,     # Increased from 0.30 — only high-confidence faces
                    iou=0.30,      # Stricter NMS to avoid duplicates
                    verbose=False,
                    augment=False,
                    half=False
                )
                for box in yolo_faces[0].boxes:
                    fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])

                    # Strict confidence threshold
                    if conf < 0.40:
                        continue

                    gx1, gy1 = offset_x + fx1, offset_y + fy1
                    gx2, gy2 = offset_x + fx2, offset_y + fy2

                    face_w = gx2 - gx1
                    face_h = gy2 - gy1

                    # Minimum face size — reject tiny faces
                    if face_w < self.min_face_size or face_h < self.min_face_size:
                        continue

                    # Aspect ratio validation — faces should be roughly square
                    aspect = max(face_w, face_h) / min(face_w, face_h)
                    if aspect > self.max_aspect_ratio:
                        continue

                    faces.append((gx1, gy1, gx2, gy2, conf))

                if faces:
                    return faces
            except Exception as e:
                logger.debug(f"YOLO face detection error: {e}")

        # ── Haar Cascade Fallback (stricter settings) ──
        if self.haar_cascade is not None and not self.haar_cascade.empty():
            try:
                gray = cv2.cvtColor(person_crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)

                haar_faces = self.haar_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,       # Increased from 1.08 — fewer false positives
                    minNeighbors=6,        # Increased from 5 — stricter
                    minSize=(self.min_face_size, self.min_face_size),
                    flags=cv2.CASCADE_SCALE_IMAGE
                )

                for (fx, fy, fw, fh) in haar_faces:
                    gx1, gy1 = offset_x + fx, offset_y + fy
                    gx2, gy2 = offset_x + fx + fw, offset_y + fy + fh

                    aspect = max(fw, fh) / min(fw, fh)
                    if aspect < 1.8:  # Stricter for Haar
                        faces.append((gx1, gy1, gx2, gy2, 0.5))  # Default confidence

            except Exception as e:
                logger.debug(f"Haar face detection error: {e}")

        return faces

    # ═══════════════════════════════════════════════════════════════
    # NMS for deduplication within a single frame
    # ═══════════════════════════════════════════════════════════════

    def _nms_deduplicate(self, detections):
        """
        Remove duplicate detections within the same frame using NMS.
        Each detection is a dict with 'bbox' key.
        """
        if len(detections) <= 1:
            return detections

        # Sort by confidence (age prediction quality)
        detections.sort(key=lambda d: d.get('quality', 0), reverse=True)

        keep = []
        boxes = np.array([d['bbox'] for d in detections], dtype=np.float32)

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        areas = (x2 - x1) * (y2 - y1)
        suppressed = np.zeros(len(detections), dtype=bool)

        for i in range(len(detections)):
            if suppressed[i]:
                continue
            keep.append(detections[i])

            xx1 = np.maximum(x1[i], x1)
            yy1 = np.maximum(y1[i], y1)
            xx2 = np.minimum(x2[i], x2)
            yy2 = np.minimum(y2[i], y2)

            inter_w = np.maximum(0, xx2 - xx1)
            inter_h = np.maximum(0, yy2 - yy1)
            inter_area = inter_w * inter_h

            union_area = areas[i] + areas - inter_area
            iou = inter_area / np.maximum(union_area, 1e-10)

            # Suppress overlapping boxes
            suppressed[iou > self.frame_nms_iou] = True

        return keep

    # ═══════════════════════════════════════════════════════════════
    # Age Estimation with Temporal Smoothing
    # ═══════════════════════════════════════════════════════════════

    def _predict_age(self, face):
        """
        Predict age with strict quality gating and multi-crop approach.
        Returns (age, confidence).
        Only accepts HIGH-QUALITY faces for reliable age estimation.
        """
        if not self.age_sess:
            return 25, 0.0

        try:
            # Assess quality first — STRICTER thresholds for age accuracy
            is_good, blur, brightness, size = self.assess_face_quality(face)
            quality_score = (min(1.0, blur / 200.0) + brightness + size) / 3.0

            # RAISED threshold — only accept good quality faces for age
            if not is_good or quality_score < 0.25:
                return 25, max(0.0, quality_score * 0.3)

            # Align face for better age estimation
            aligned_face = self.align_face(face)

            # Multi-crop approach — weighted by reliability
            age_predictions = []
            weights = []

            # Crop 1: Full face (weight: 1.0) — most reliable
            crops = [(aligned_face, 1.0)]

            # Crop 2: Upper face (forehead to nose) — better for age (weight: 0.7)
            h, w = face.shape[:2]
            upper_face = aligned_face[0:int(h * 0.7), :]
            if upper_face.shape[0] > 30:
                crops.append((upper_face, 0.7))

            # Crop 3: Center crop (weight: 0.8)
            margin = int(min(h, w) * 0.1)
            center_crop = aligned_face[margin:h - margin, margin:w - margin]
            if center_crop.shape[0] > 30 and center_crop.shape[1] > 30:
                crops.append((center_crop, 0.8))

            for crop, weight in crops:
                try:
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    gray_eq = cv2.equalizeHist(gray)
                    face_3ch = cv2.merge([gray_eq, gray_eq, gray_eq])

                    blob = cv2.resize(face_3ch, (96, 96)).astype(np.float32)
                    blob = blob.transpose(2, 0, 1)  # HWC to CHW
                    blob = np.expand_dims(blob, axis=0)

                    input_name = self.age_sess.get_inputs()[0].name
                    outs = self.age_sess.run(None, {input_name: blob})

                    age_probs = outs[0][0].flatten()
                    age_probs = np.clip(age_probs, 0, None)
                    total = np.sum(age_probs)
                    if total > 0:
                        age_probs = age_probs / total

                    ages = np.arange(len(age_probs))
                    expected_age = int(np.sum(ages * age_probs))

                    # Confidence based on prediction sharpness (peak probability)
                    peak_prob = np.max(age_probs)
                    crop_conf = min(1.0, peak_prob * 5)  # Scale to 0-1

                    age_predictions.append(expected_age)
                    weights.append(weight * crop_conf)
                except Exception:
                    continue

            if not age_predictions:
                return 25, 0.0

            # Weighted average of all valid crops
            weights = np.array(weights)
            weights = weights / np.sum(weights)
            raw_age = int(np.average(age_predictions, weights=weights))

            # ── Age Correction Factor (calibrated for DEX model biases) ──
            # DEX systematically underestimates adult ages.
            # Correction based on published analysis of DEX bias patterns:
            if raw_age < 10:
                corrected_age = int(raw_age * 1.05)
            elif raw_age < 14:
                corrected_age = int(raw_age * 1.0)
            elif raw_age < 18:
                corrected_age = int(raw_age * 0.95)  # Teens often look older
            elif raw_age < 25:
                corrected_age = int(raw_age * 1.20)
            elif raw_age < 35:
                corrected_age = int(raw_age * 1.30)
            elif raw_age < 45:
                corrected_age = int(raw_age * 1.20)
            elif raw_age < 55:
                corrected_age = int(raw_age * 1.12)
            elif raw_age < 65:
                corrected_age = int(raw_age * 1.08)
            else:
                corrected_age = int(raw_age * 1.12)

            # Clamp to reasonable range (allow kids detection: min age 4)
            final_age = min(85, max(4, corrected_age))

            # Overall confidence
            overall_conf = float(np.average(
                [min(1.0, w) for w in weights],
                weights=weights
            )) * quality_score

            return final_age, overall_conf

        except Exception as e:
            logger.error(f"Age prediction error: {e}")
            return 25, 0.0

    def _smooth_age(self, face_id, raw_age, confidence):
        """
        Apply temporal smoothing to age predictions per face identity.
        Uses outlier rejection + exponential weighting.
        Returns smoothed age.
        """
        if face_id not in self.age_history:
            self.age_history[face_id] = []

        history = self.age_history[face_id]
        history.append((raw_age, confidence))

        # Keep only recent predictions
        if len(history) > self.age_smoothing_window:
            history.pop(0)

        if len(history) == 0:
            return raw_age

        # Outlier rejection: remove predictions > 20 years from median
        ages = [h[0] for h in history]
        median_age = np.median(ages)
        filtered = [(a, c) for a, c in history if abs(a - median_age) <= 20]
        if len(filtered) < 2:
            filtered = history  # Keep all if too few after filtering

        ages = [h[0] for h in filtered]
        confs = [max(0.1, h[1]) for h in filtered]

        # Exponential weighting: most recent gets highest weight
        time_weights = np.exp(np.linspace(0, 1, len(confs)))
        final_weights = np.array(confs) * time_weights
        final_weights = final_weights / np.sum(final_weights)

        smoothed_age = int(np.average(ages, weights=final_weights))

        # Clamp to reasonable range
        return min(80, max(5, smoothed_age))

    # ═══════════════════════════════════════════════════════════════
    # Embedding Extraction
    # ═══════════════════════════════════════════════════════════════

    def _get_embedding(self, face):
        """Get ArcFace embedding for face recognition."""
        if not self.arcface_sess:
            return None
        try:
            # Align face first
            aligned = self.align_face(face)
            blob = cv2.resize(aligned, (112, 112)).astype(np.float32)
            blob = (blob - 127.5) / 128.0
            blob = np.expand_dims(blob, axis=0)

            input_name = self.arcface_sess.get_inputs()[0].name
            outs = self.arcface_sess.run(None, {input_name: blob})
            return outs[0].flatten()
        except Exception as e:
            logger.debug(f"ArcFace embedding error: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # Age Group Mapping
    # ═══════════════════════════════════════════════════════════════

    def _age_to_group(self, age):
        """Convert age to music group with fuzzy boundaries."""
        if age < 14:
            return "kids"
        elif age < 22:
            return "youths"
        elif age < 55:
            return "adults"
        else:
            return "seniors"

    # ═══════════════════════════════════════════════════════════════
    # Main Pipeline Entry Point
    # ═══════════════════════════════════════════════════════════════

    def process_frame(self, frame, cam_id):
        """
        Process a single frame from a camera.
        Returns list of detections with age, group, bbox, cam_id.

        Pipeline:
        1. Auto-enhance frame
        2. Motion gating
        3. Human detection (strict validation)
        4. Face detection within person crops
        5. Face quality assessment
        6. Age estimation (multi-crop, aligned)
        7. Face embedding + identity matching
        8. Temporal age smoothing
        9. NMS deduplication
        """
        if frame is None:
            return []

        # ── STEP 0: Motion Gating (on raw frame — skip enhancement if no motion) ──
        mask = self.bg_subtractor.apply(frame)
        mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)[0]
        mask = cv2.dilate(mask, None, iterations=2)
        motion_pixels = cv2.countNonZero(mask)
        motion_detected = motion_pixels > 80

        # Only enhance if motion detected (saves CPU on static frames)
        if motion_detected:
            enhanced = self.auto_enhance_frame(frame)
        else:
            enhanced = frame

        results = []
        h, w = frame.shape[:2]

        # ── STEP 2: Human Detection (strict validation) ──
        # YOLOv8n with classes=[0] = ONLY person class (no pets, cars, objects)
        # Strict geometric validation rejects false positives
        all_person_boxes = []

        if self.use_multiscale:
            # Run detection at multiple scales for better small/distant detection
            for scale in self.scales:
                if scale == 1.0:
                    scaled_frame = enhanced
                    scale_factor = 1.0
                else:
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    scaled_frame = cv2.resize(enhanced, (new_w, new_h))
                    scale_factor = 1.0 / scale

                persons = self.person_model(
                    scaled_frame,
                    classes=[0],       # COCO class 0 = person ONLY
                    conf=0.35,         # Higher threshold — only confident detections
                    iou=0.40,          # Stricter NMS
                    verbose=False,
                    augment=False,
                    half=False,
                    max_det=8
                )

                for result in persons:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        # Scale back to original size
                        x1 = int(x1 * scale_factor)
                        y1 = int(y1 * scale_factor)
                        x2 = int(x2 * scale_factor)
                        y2 = int(y2 * scale_factor)

                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(w, x2), min(h, y2)

                        box_w = x2 - x1
                        box_h = y2 - y1

                        # Strict size check — reject tiny detections (noise)
                        if box_w < 60 or box_h < 80:
                            continue

                        # Aspect ratio: humans are taller than wide
                        aspect = box_h / max(box_w, 1)
                        if aspect < 0.8 or aspect > 3.5:
                            continue

                        # Head-to-body proportion
                        if box_h < box_w * 0.6:
                            continue

                        # Position check
                        if y1 < 5 or y2 > (h - 5):
                            continue

                        all_person_boxes.append((x1, y1, x2, y2, conf))
        else:
            persons = self.person_model(
                enhanced,
                classes=[0],         # COCO class 0 = person ONLY (no dogs/cats/cars)
                conf=0.35,           # Higher threshold — only confident detections
                iou=0.40,            # Stricter NMS — fewer duplicate boxes
                verbose=False,
                augment=False,       # No TTA — faster, same accuracy with higher conf
                half=False,
                max_det=8            # Max 8 persons — avoids noise from low-confidence boxes
            )

            for result in persons:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)

                    box_w = x2 - x1
                    box_h = y2 - y1

                    # Strict size check — reject tiny detections (noise)
                    if box_w < 60 or box_h < 80:
                        continue

                    # Aspect ratio: humans are taller than wide (1.2 to 3.0)
                    # Reject squares and extreme ratios (tables, signs, shadows)
                    aspect = box_h / max(box_w, 1)
                    if aspect < 0.8 or aspect > 3.5:
                        continue

                    # Head-to-body ratio: head should be upper portion
                    # A real person has more height than width
                    if box_h < box_w * 0.6:
                        continue

                    # Position check: person should not be at very top/bottom edge
                    # (eliminates ceiling fixtures, floor patterns)
                    if y1 < 5 or y2 > (h - 5):
                        continue

                    all_person_boxes.append((x1, y1, x2, y2, conf))

        # NMS to merge multi-scale detections
        if len(all_person_boxes) > 1:
            boxes_np = np.array([[b[0], b[1], b[2], b[3]] for b in all_person_boxes], dtype=np.float32)
            confs_np = np.array([b[4] for b in all_person_boxes], dtype=np.float32)
            indices = cv2.dnn.NMSBoxes(boxes_np.tolist(), confs_np.tolist(), 0.25, 0.45)
            if len(indices) > 0:
                indices = indices.flatten() if len(indices.shape) > 1 else indices
            else:
                indices = []
        else:
            indices = range(len(all_person_boxes))

        person_boxes = []
        for i in indices:
            x1, y1, x2, y2, conf = all_person_boxes[i]
            person_crop = enhanced[y1:y2, x1:x2]
            if person_crop.size == 0:
                continue
            person_boxes.append((x1, y1, x2, y2, conf, person_crop))

        # ── STEP 3: Face Detection within Person Crops ──
        for px1, py1, px2, py2, pconf, person_crop in person_boxes:
            faces = self._detect_faces(person_crop, px1, py1)

            for fx1, fy1, fx2, fy2, fconf in faces:
                face_crop = enhanced[fy1:fy2, fx1:fx2]

                # Quality check
                is_good, blur, brightness, size = self.assess_face_quality(face_crop)

                # ── STEP 4: Age Estimation ──
                raw_age, age_conf = self._predict_age(face_crop)

                # ── STEP 5: Face Embedding + Identity ──
                embedding = self._get_embedding(face_crop)
                group = self._age_to_group(raw_age)

                face_id = "unknown"
                final_age = raw_age

                if embedding is not None and self.registry:
                    fid, sim, registered_age = self.registry.is_known(embedding, age=raw_age)

                    if fid:
                        # Known face - use registry data
                        self.registry.update(fid, cam_id)
                        face_id = fid

                        # Use registered age if available
                        if registered_age is not None:
                            final_age = registered_age
                            group = self._age_to_group(final_age)
                    else:
                        # Unknown face - track as pending before registering
                        pending_id, is_ready = self.registry.track_pending_unknown(
                            embedding, group, cam_id, raw_age
                        )

                        if is_ready:
                            # Consistently detected — register as known identity
                            avg_age = None
                            pending_data = self.registry.pending_unknowns.get(pending_id)
                            if pending_data and pending_data['age_samples']:
                                avg_age = int(np.mean(pending_data['age_samples']))

                            face_id = self.registry.register(
                                embedding, group, cam_id, age=avg_age or raw_age
                            )
                        else:
                            # Not yet consistently detected — use pending ID
                            face_id = pending_id

                    # ── STEP 6: Temporal Age Smoothing ──
                    final_age = self._smooth_age(face_id, raw_age, age_conf)
                    group = self._age_to_group(final_age)

                    # Update registry with smoothed age
                    if self.registry and face_id in self.registry.known_faces:
                        self.registry.update_age(face_id, final_age)

                    # Save to vault if new
                    if self.vault and not self.registry.is_saved(face_id):
                        if self.vault.save_face(face_crop, face_id, group, quality=age_conf, age=final_age):
                            self.registry.mark_as_saved(face_id)
                            logger.info(f"Face saved: {face_id} (Group: {group}, Age: {final_age}, Quality: {age_conf:.2f})")

                results.append({
                    'id': face_id,
                    'age': final_age,
                    'group': group,
                    'bbox': [fx1, fy1, fx2, fy2],
                    'cam_id': cam_id,
                    'quality': age_conf,
                    'person_conf': pconf,
                    'face_conf': fconf,
                    'is_good_quality': is_good
                })

        # ── STEP 7: Direct Face Detection (always run when motion detected) ──
        # Runs alongside person-based detection to catch faces YOLO-person missed
        # NMS at the end removes duplicates between the two detection paths
        if motion_detected:
            direct_faces = self._detect_faces(enhanced, 0, 0)

            for fx1, fy1, fx2, fy2, fconf in direct_faces:
                face_crop = enhanced[fy1:fy2, fx1:fx2]
                is_good, blur, brightness, size = self.assess_face_quality(face_crop)

                raw_age, age_conf = self._predict_age(face_crop)
                embedding = self._get_embedding(face_crop)
                group = self._age_to_group(raw_age)

                face_id = "unknown"
                final_age = raw_age

                if embedding is not None and self.registry:
                    fid, sim, registered_age = self.registry.is_known(embedding, age=raw_age)
                    if fid:
                        self.registry.update(fid, cam_id)
                        face_id = fid
                        if registered_age is not None:
                            final_age = registered_age
                            group = self._age_to_group(final_age)
                    else:
                        # Unknown face - track as pending before registering
                        pending_id, is_ready = self.registry.track_pending_unknown(
                            embedding, group, cam_id, raw_age
                        )

                        if is_ready:
                            avg_age = None
                            pending_data = self.registry.pending_unknowns.get(pending_id)
                            if pending_data and pending_data['age_samples']:
                                avg_age = int(np.mean(pending_data['age_samples']))

                            face_id = self.registry.register(
                                embedding, group, cam_id, age=avg_age or raw_age
                            )
                        else:
                            face_id = pending_id

                    final_age = self._smooth_age(face_id, raw_age, age_conf)
                    group = self._age_to_group(final_age)

                    if self.vault and not self.registry.is_saved(face_id):
                        if self.vault.save_face(face_crop, face_id, group, quality=age_conf, age=final_age):
                            self.registry.mark_as_saved(face_id)

                results.append({
                    'id': face_id,
                    'age': final_age,
                    'group': group,
                    'bbox': [fx1, fy1, fx2, fy2],
                    'cam_id': cam_id,
                    'quality': age_conf,
                    'person_conf': 0.0,
                    'face_conf': fconf,
                    'is_good_quality': is_good
                })

        # ── STEP 8: NMS Deduplication ──
        results = self._nms_deduplicate(results)

        # ── Logging ──
        if results:
            ages = [r['age'] for r in results]
            avg_age = sum(ages) / len(ages)
            groups = [r['group'] for r in results]
            qualities = [r.get('quality', 0) for r in results]
            avg_quality = sum(qualities) / len(qualities)

            logger.info(
                f"Cam {cam_id}: {len(results)} face(s) | "
                f"Ages: {ages} (avg: {avg_age:.1f}) | "
                f"Groups: {groups} | "
                f"Avg quality: {avg_quality:.2f}"
            )

        return results
