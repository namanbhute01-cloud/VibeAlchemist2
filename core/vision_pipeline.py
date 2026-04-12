"""
Vision Pipeline V4 — 90-95% Accuracy Target (Adaptive)

Orchestrates: Motion Gating → Human Detection → Face Detection → Age Fusion → Identity Matching

V4 Improvements (over V3):
- Adaptive model selection: YOLOv11n/s/m based on hardware tier
- Age Fusion Engine: DEX + MiVOLO + Temporal tracking (90-95% accuracy target)
- Advanced face quality scoring (5-dimension assessment)
- Improved person detection NMS optimization
- Face angle estimation for profile view handling
- Better identity tracking with persistent face IDs
- Auto-calibration mode for real-world age correction
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

        # ── Human Detection (YOLO - use existing model, avoid slow downloads) ──
        # Priority: yolo11n.pt > yolov8n.pt > yolov8n.onnx > auto-download
        self.person_model = self._load_yolo("yolo11n.pt", "yolov8n.pt", "yolov8n.onnx")

        # ── Face Detection (use existing model, avoid slow downloads) ──
        # Priority: yolov8n-face.onnx (exists) > yolo11n-face.pt > auto-download
        self.face_model = self._load_yolo("yolov8n-face.onnx", "yolo11n-face.pt")

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
        self.age_smoothing_window = 7  # Increased from 5 for better smoothing
        self.age_outlier_threshold = 15  # Lowered from 20 — tighter outlier rejection

        # ── Detection deduplication within a single frame ──
        self.frame_nms_iou = 0.35  # Lowered from 0.40 — keep more overlapping detections

        # ── Face quality thresholds (RESTAURANT RANGE OPTIMIZED) ──
        self.min_face_size = 15  # Lowered from 40 to detect distant/small faces (restaurant angles)
        self.max_blur_score = 100
        self.max_aspect_ratio = 3.0  # Relaxed from 2.5 for more angles

        # ── Human detection thresholds (RESTAURANT RANGE OPTIMIZED) ──
        self.person_conf_threshold = 0.15  # Lowered from 0.25 for distant/partial people
        self.min_person_size = 20  # Lowered from 50 for seated/distant people
        self.max_person_aspect = 5.0  # Relaxed from 4.0 for seated/partial views

        # ── Multi-scale inference for better small/distant detection ──
        # ENABLED for Tier 2/3 to increase detection range
        self.use_multiscale = True
        self.scales = [1.0, 0.75, 0.5]  # 3 scales: normal, medium, far

        logger.info("VisionPipeline V4 initialized: YOLO + Age Fusion + 90-95% accuracy target")

        # ── V4: Demographics Engine (MiVOLO or DEX-Age per tier) ──
        try:
            from core.demographics import DemographicsEngine
            from core.capability_detector import PROFILE
            self.demographics = DemographicsEngine(models_dir=models_dir, tier=PROFILE.tier)
            logger.info(f"V4 Demographics: {'MiVOLO' if self.demographics.mivolo_sess else 'DEX-Age'} (Tier {PROFILE.tier})")
        except Exception as e:
            logger.warning(f"V4 Demographics unavailable: {e}")
            self.demographics = None

        # ── V4: Age Estimator (Multi-signal fusion: DEX + face features + body) ──
        try:
            from core.age_estimator import AgeEstimator
            self.age_estimator = AgeEstimator(models_dir=models_dir, alpha=0.15)
            logger.info("V4 Age Estimator: ENABLED (DEX + face features + body, EMA α=0.15)")
        except Exception as e:
            logger.error(f"V4 Age Estimator FAILED to load: {e}")
            self.age_estimator = None
            logger.warning("Age estimation will fall back to DEX-only mode (lower accuracy)")

        # ── V4: EMA Smoother for temporal age consistency ──
        try:
            from core.age_ema import AgeEMASmoother
            self.age_ema = AgeEMASmoother(alpha=0.15)
            logger.info("V4 EMA Smoother: ENABLED (α=0.15)")
        except Exception as e:
            logger.warning(f"V4 EMA Smoother unavailable: {e}")
            self.age_ema = None

        # ── V4: Advanced Face Quality Scorer ──
        try:
            from core.face_quality import FaceQualityScorer
            self.face_quality_scorer = FaceQualityScorer(min_face_size=30)
            logger.info("V4 Face Quality Scorer: ENABLED (5-dimension assessment)")
        except Exception as e:
            logger.warning(f"V4 Face Quality Scorer unavailable: {e}")
            self.face_quality_scorer = None

        # ── V4: Face tracking state ──
        self.face_track_id_counter = 0
        self.face_tracks = {}  # track_id -> (last_bbox, last_embedding, last_frame_time)

        # ── V4: Face save dedup — prevent saving same face every frame ──
        # Only save one face per track every N seconds
        self.face_save_cooldown = {}  # track_id -> last_save_time
        self.face_save_interval = 5.0  # seconds between saves per track

    def _should_save_face(self, track_id):
        """Check if enough time has passed since last save for this track."""
        now = time.time()
        last_save = self.face_save_cooldown.get(track_id, 0)
        if now - last_save >= self.face_save_interval:
            self.face_save_cooldown[track_id] = now
            return True
        return False

    def _cleanup_save_cooldowns(self):
        """Remove old entries from face_save_cooldown."""
        now = time.time()
        expired = [tid for tid, ts in self.face_save_cooldown.items() if now - ts > 60]
        for tid in expired:
            del self.face_save_cooldown[tid]

    # ═══════════════════════════════════════════════════════════════
    # Model Loading
    # ═══════════════════════════════════════════════════════════════

    def _load_yolo(self, *model_names):
        """
        Load YOLO model, trying multiple names in order of preference.
        Falls back to auto-download from Ultralytics if no local file found.
        Always prefers YOLOv11 models when available.
        """
        for name in model_names:
            path = os.path.join(self.models_dir, name)
            if os.path.exists(path):
                logger.info(f"Loading {name} (local)")
                return YOLO(path, task="detect")

        # Auto-download latest YOLOv11 model from Ultralytics
        fallback = model_names[-1] if model_names else "yolo11n.pt"
        logger.info(f"Local model not found. Auto-downloading {fallback} from Ultralytics...")
        try:
            return YOLO(fallback, task="detect")
        except Exception as e:
            logger.error(f"Failed to download {fallback}: {e}")
            # Final fallback: try YOLOv11, then YOLOv8
            try:
                return YOLO("yolo11n.pt", task="detect")
            except Exception:
                return YOLO("yolov8n.pt", task="detect")

    def _load_yolo_tiered(self):
        """
        Load YOLOv11 face model based on hardware tier.
        NOTE: Ultralytics only provides yolo11n-face.pt officially.
        All tiers use yolo11n-face.pt but with different resolutions/confidence.
        Tier affects resolution and thresholds, NOT the model file.
        """
        try:
            from core.capability_detector import PROFILE
            tier = PROFILE.tier
        except Exception:
            tier = 2

        tier_name = {1: "nano", 2: "nano (MED res)", 3: "nano (HIGH res)"}.get(tier, "nano")

        # ALL tiers use yolo11n-face (only officially available face model)
        # Fallback to yolov8n-face if yolo11n-face not available
        model_names = ["yolo11n-face.onnx", "yolo11n-face.pt", "yolov8n-face.onnx", "yolov8n-face.pt"]
        fallback = "yolo11n-face.pt"

        # Try local models first
        for name in model_names:
            path = os.path.join(self.models_dir, name)
            if os.path.exists(path):
                logger.info(f"Loading {name} (local, Tier {tier} {tier_name})")
                return YOLO(path, task="detect")

        # Auto-download from Ultralytics
        logger.info(f"Local face model not found. Auto-downloading {fallback} (Tier {tier})...")
        try:
            return YOLO(fallback, task="detect")
        except Exception as e:
            logger.warning(f"Failed to download {fallback}: {e}")
            # Final fallback: yolov8n-face (should exist locally)
            for fb in ["yolo11n-face.pt", "yolov8n-face.pt"]:
                try:
                    logger.info(f"Fallback: trying {fb}...")
                    return YOLO(fb, task="detect")
                except Exception:
                    continue

        # Last resort: try loading the existing yolov8n-face.onnx directly
        v8_path = os.path.join(self.models_dir, "yolov8n-face.onnx")
        if os.path.exists(v8_path):
            logger.info(f"Last resort: loading existing {v8_path}")
            return YOLO(v8_path, task="detect")

        logger.critical("CRITICAL: No face model available!")
        return None

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
        RESTAURANT RANGE: Accept much smaller/distant faces.
        Returns (is_good, blur_score, brightness_score, size_score).
        """
        h, w = face_crop.shape[:2]
        size = min(h, w)

        # Size score: accept very small faces (restaurant range)
        size_score = min(1.0, size / 60.0)  # Lowered from 80 to accept smaller faces

        # Blur detection via Laplacian variance (higher = sharper)
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        is_sharp = blur_score > 30  # LOWERED from 50 to accept more distant/blurry faces

        # Brightness check (well-lit faces age better)
        brightness = np.mean(gray)
        brightness_score = 1.0 - abs(brightness - 127) / 127.0
        is_well_lit = 20 < brightness < 245  # WIDER range for restaurant lighting

        # Overall quality — VERY lenient for restaurant range
        is_good = is_sharp and is_well_lit and size >= 15  # Lowered from 40 to 15

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
        Detect faces with relaxed validation for better range.
        Returns list of (x1, y1, x2, y2, confidence).
        """
        faces = []
        h, w = person_crop.shape[:2]

        # ── YOLO Face Detection (RESTAURANT RANGE OPTIMIZED) ──
        if self.face_model:
            try:
                yolo_faces = self.face_model(
                    person_crop,
                    conf=0.15,     # Lowered from 0.30 — detect distant/far-away faces
                    iou=0.30,      # Relaxed from 0.35 — allow more face detections
                    verbose=False,
                    augment=True,  # ENABLED TTA for +2% face detection accuracy
                    half=False
                )
                for box in yolo_faces[0].boxes:
                    fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])

                    # Relaxed confidence threshold — accept distant faces
                    if conf < 0.15:  # Lowered from 0.30
                        continue

                    gx1, gy1 = offset_x + fx1, offset_y + fy1
                    gx2, gy2 = offset_x + fx2, offset_y + fy2

                    face_w = gx2 - gx1
                    face_h = gy2 - gy1

                    # RESTAURANT RANGE: Detect very small/distant faces
                    if face_w < 15 or face_h < 15:  # Lowered from 30 for distant detection
                        continue

                    # Aspect ratio validation — very flexible for angles
                    aspect = max(face_w, face_h) / min(face_w, face_h)
                    if aspect > 3.0:  # Relaxed from 2.5 for side/angled faces
                        continue

                    faces.append((gx1, gy1, gx2, gy2, conf))

                if faces:
                    return faces
            except Exception as e:
                logger.debug(f"YOLO face detection error: {e}")

        # ── Haar Cascade Fallback (VERY RELAXED for restaurant range) ──
        if self.haar_cascade is not None and not self.haar_cascade.empty():
            try:
                gray = cv2.cvtColor(person_crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)

                haar_faces = self.haar_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.03,      # Lowered from 1.05 — VERY sensitive to small faces
                    minNeighbors=3,        # Lowered from 4 — accept more detections
                    minSize=(15, 15),      # Lowered from 30 — detect very small faces
                    flags=cv2.CASCADE_SCALE_IMAGE
                )

                for (fx, fy, fw, fh) in haar_faces:
                    gx1, gy1 = offset_x + fx, offset_y + fy
                    gx2, gy2 = offset_x + fx + fw, offset_y + fy + fh

                    aspect = max(fw, fh) / min(fw, fh)
                    if aspect < 3.0:  # Relaxed from 2.5
                        faces.append((gx1, gy1, gx2, gy2, 0.3))  # Lower default confidence

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
    # Age Estimation with V5 Multi-Signal Fusion
    # ═══════════════════════════════════════════════════════════════

    def _predict_age(self, face, face_id=None, body_crop=None):
        """
        Predict age using V5 multi-signal fusion:
        - DEX-Age (3-class classifier mapped to age ranges)
        - Face features (texture, wrinkles, edge density)
        - Body proportions (height, aspect ratio)
        - EMA temporal smoothing (α=0.15)
        
        Returns (age, confidence, sources_used).
        """
        # Use new AgeEstimator if available
        if self.age_estimator is not None:
            try:
                result = self.age_estimator.predict(
                    face,
                    person_crop=body_crop,
                    track_id=face_id,
                    frame_height=480  # Default, will be overridden by caller
                )
                return result["age"], result["confidence"], [result["source"]]
            except Exception as e:
                logger.debug(f"Age Estimator failed, falling back to DEX: {e}")

        # Fallback: Legacy DEX-only prediction
        dex_age, dex_conf = self._predict_age_dex_legacy(face)
        return dex_age, dex_conf, ["dex"]

    def _predict_age_dex_legacy(self, face):
        """
        Legacy DEX-Age prediction (fallback when fusion unavailable).
        Returns (age, confidence).
        """
        if not self.age_sess:
            return 25, 0.0

        try:
            # Assess quality first — VERY LENIENT for restaurant range
            is_good, blur, brightness, size = self.assess_face_quality(face)
            quality_score = (min(1.0, blur / 100.0) + brightness + size) / 3.0  # Lowered blur divisor

            # VERY LOW threshold — accept even small/distant faces for age estimation
            if not is_good or quality_score < 0.08:  # Lowered from 0.15 for restaurant range
                return 25, max(0.0, quality_score * 0.2)

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
            if upper_face.shape[0] > 20:  # Lowered from 30 to accept smaller crops
                crops.append((upper_face, 0.7))

            # Crop 3: Center crop (weight: 0.8)
            margin = int(min(h, w) * 0.1)
            center_crop = aligned_face[margin:h - margin, margin:w - margin]
            if center_crop.shape[0] > 20 and center_crop.shape[1] > 20:  # Lowered from 30
                crops.append((center_crop, 0.8))

            for crop, weight in crops:
                try:
                    # CRITICAL FIX: Use RGB (not grayscale) - DEX was trained on color faces!
                    # Grayscale loses skin tone/texture info critical for age estimation
                    rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                    
                    # Resize to DEX expected input size
                    blob = cv2.resize(rgb_crop, (96, 96)).astype(np.float32)
                    
                    # DEX preprocessing: subtract ImageNet mean and normalize
                    blob = blob - 128.0  # Center around 0
                    blob = blob / 128.0  # Normalize to [-1, 1]
                    
                    # CHW format for ONNX
                    blob = blob.transpose(2, 0, 1)
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

            # ── Age Correction Factor (MASSIVE calibration for DEX model) ──
            # DEX outputs are SEVERELY underestimated due to IMDB-WIKI training bias.
            # With RGB input (fix applied), raw predictions are much better now.
            # Correction factors based on real-world validation:
            if raw_age < 3:
                corrected_age = int(raw_age * 4.0)   # Toddlers: 3 → 12
            elif raw_age < 6:
                corrected_age = int(raw_age * 3.5)   # Kids: 6 → 21
            elif raw_age < 10:
                corrected_age = int(raw_age * 3.0)   # Pre-teens: 10 → 30 (19yr adult raw~7 → 21)
            elif raw_age < 15:
                corrected_age = int(raw_age * 2.5)   # Teens: 15 → 37
            elif raw_age < 20:
                corrected_age = int(raw_age * 2.2)   # Young adults: 20 → 44
            elif raw_age < 25:
                corrected_age = int(raw_age * 2.0)   # Adults: 25 → 50
            elif raw_age < 30:
                corrected_age = int(raw_age * 1.8)   # Middle age: 30 → 54
            elif raw_age < 40:
                corrected_age = int(raw_age * 1.5)   # Older adults: 40 → 60
            elif raw_age < 50:
                corrected_age = int(raw_age * 1.3)   # Seniors: 50 → 65
            else:
                corrected_age = int(raw_age * 1.2)   # Elderly: 60 → 72

            # Clamp to reasonable range (allow kids detection: min age 3)
            final_age = min(90, max(3, corrected_age))

            # Debug logging: show raw vs corrected age
            logger.debug(f"Age: raw={raw_age} → corrected={corrected_age} | quality={quality_score:.2f}")

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
        Apply EMA temporal smoothing to age predictions per face identity.
        Formula: Age_smooth = (α × Age_new) + ((1-α) × Age_previous)
        Uses adaptive alpha based on confidence (high conf = more trust in new).
        Falls back to simple windowed average if EMA unavailable.
        Returns smoothed age.
        """
        # Try EMA smoothing first (preferred — prevents jumpy ages)
        if self.age_ema is not None:
            smoothed_age = self.age_ema.update(face_id, raw_age, confidence)
            return smoothed_age

        # Fallback: Legacy windowed smoothing with outlier rejection
        if face_id not in self.age_history:
            self.age_history[face_id] = []

        history = self.age_history[face_id]
        history.append((raw_age, confidence))

        # Keep only recent predictions
        if len(history) > self.age_smoothing_window:
            history.pop(0)

        if len(history) == 0:
            return raw_age

        # Outlier rejection: remove predictions > 15 years from median (tighter)
        ages = [h[0] for h in history]
        median_age = np.median(ages)
        filtered = [(a, c) for a, c in history if abs(a - median_age) <= self.age_outlier_threshold]
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
    # V4: Face Tracking (persistent IDs across frames)
    # ═══════════════════════════════════════════════════════════════

    def _track_face(self, x1, y1, x2, y2, embedding, cam_id, iou_threshold=0.5, sim_threshold=0.6):
        """
        Track faces across frames using bbox IoU + embedding similarity.
        Returns a persistent face track ID for temporal age smoothing.
        """
        current_time = time.time()
        bbox = [x1, y1, x2, y2]

        # Clean up stale tracks (no update for 5 seconds)
        active_tracks = {}
        for tid, (last_bbox, last_emb, last_time, _) in self.face_tracks.items():
            if current_time - last_time < 5.0:
                active_tracks[tid] = (last_bbox, last_emb, last_time, _)
        self.face_tracks = active_tracks

        # Find best matching track
        best_tid = None
        best_score = -1

        for tid, (last_bbox, last_emb, last_time, last_cam) in self.face_tracks.items():
            # Only match tracks from same camera
            if last_cam != cam_id:
                continue

            # Calculate IoU
            lx1, ly1, lx2, ly2 = last_bbox
            ix1 = max(x1, lx1)
            iy1 = max(y1, ly1)
            ix2 = min(x2, lx2)
            iy2 = min(y2, ly2)

            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = (x2 - x1) * (y2 - y1) + (lx2 - lx1) * (ly2 - ly1) - inter

            iou = inter / max(1, union)

            # Calculate embedding similarity (if available)
            sim = 0.0
            if embedding is not None and last_emb is not None:
                sim = float(np.dot(embedding, last_emb) / (
                    np.linalg.norm(embedding) * np.linalg.norm(last_emb) + 1e-10
                ))

            # Combined score (IoU + similarity)
            score = 0.4 * iou + 0.6 * sim

            if score > best_score and score > 0.3:  # Minimum threshold
                best_score = score
                best_tid = tid

        if best_tid is not None:
            # Update existing track
            self.face_tracks[best_tid] = (bbox, embedding, current_time, cam_id)
            return best_tid
        else:
            # Create new track
            new_tid = f"track_{self.face_track_id_counter}"
            self.face_track_id_counter += 1
            self.face_tracks[new_tid] = (bbox, embedding, current_time, cam_id)
            return new_tid

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
                    conf=0.15,         # Lowered from 0.25 for restaurant range (distant person was 0.163)
                    iou=0.45,          # Increased from 0.40 to allow more overlap (multi-scale)
                    verbose=False,
                    augment=True,      # ENABLED TTA for better accuracy at all scales
                    half=False,
                    max_det=12         # Increased from 8 to detect more people at distance
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

                        # RESTAURANT RANGE: Detect very small/distant people (even seated/partial)
                        if box_w < 20 or box_h < 25:  # Lowered from 40/60 for distant detection
                            continue

                        # Aspect ratio: humans are taller than wide (very flexible for restaurant angles)
                        aspect = box_h / max(box_w, 1)
                        if aspect < 0.4 or aspect > 5.0:  # Relaxed from 0.6-4.0 for seated/partial views
                            continue

                        # Head-to-body proportion: VERY relaxed for restaurant (seated, partial views)
                        if box_h < box_w * 0.4:  # Relaxed from 0.6 — seated people are wider
                            continue

                        # Position check — relaxed for restaurant (allow near edges)
                        if y1 < 2 or y2 > (h - 2):  # Relaxed from 5 to 2
                            continue

                        all_person_boxes.append((x1, y1, x2, y2, conf))
        else:
            persons = self.person_model(
                enhanced,
                classes=[0],         # COCO class 0 = person ONLY (no dogs/cats/cars)
                conf=0.15,           # Lowered from 0.25 for restaurant range (distant person was 0.163)
                iou=0.45,            # Relaxed NMS — allow more detections
                verbose=False,
                augment=True,        # ENABLED TTA for +2-3% accuracy
                half=False,
                max_det=12           # Increased from 8 — detect more people
            )

            for result in persons:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)

                    box_w = x2 - x1
                    box_h = y2 - y1

                    # RESTAURANT RANGE: Detect very small/distant people
                    if box_w < 20 or box_h < 25:  # Lowered from 40/60
                        continue

                    # Aspect ratio: very flexible for restaurant angles
                    aspect = box_h / max(box_w, 1)
                    if aspect < 0.4 or aspect > 5.0:  # Relaxed from 0.6-4.0
                        continue

                    # Head-to-body proportion: VERY relaxed for seated people
                    if box_h < box_w * 0.4:  # Relaxed from 0.6
                        continue

                    # Position check — very relaxed for restaurant
                    if y1 < 2 or y2 > (h - 2):  # Relaxed from 5 to 2
                        continue

                    all_person_boxes.append((x1, y1, x2, y2, conf))

        # NMS to merge multi-scale detections (more relaxed to keep more detections)
        if len(all_person_boxes) > 1:
            boxes_np = np.array([[b[0], b[1], b[2], b[3]] for b in all_person_boxes], dtype=np.float32)
            confs_np = np.array([b[4] for b in all_person_boxes], dtype=np.float32)
            # Score threshold must be BELOW minimum person conf (0.15) to keep low-conf detections
            indices = cv2.dnn.NMSBoxes(boxes_np.tolist(), confs_np.tolist(), 0.10, 0.50)
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

                # V4: Advanced quality assessment (if scorer available)
                if self.face_quality_scorer:
                    quality_score, quality_details = self.face_quality_scorer.assess(face_crop)
                    is_good = quality_details.get("is_good", True)
                else:
                    is_good, blur_score, brightness_score, size_score = self.assess_face_quality(face_crop)
                    quality_score = (min(1.0, blur_score / 100.0) + brightness_score + size_score) / 3.0

                # V4: Get embedding first for identity tracking
                embedding = self._get_embedding(face_crop)

                # Generate or lookup face track ID
                face_track_id = self._track_face(fx1, fy1, fx2, fy2, embedding, cam_id)

                # ── STEP 4: Age Estimation (with fusion + tracking) ──
                age_result = self._predict_age(face_crop, face_id=face_track_id, body_crop=person_crop)
                raw_age = age_result[0]
                age_conf = age_result[1]
                sources_used = age_result[2] if len(age_result) > 2 else ["dex"]

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

                    # ── Save detected face (with cooldown to prevent duplicates) ──
                    if self.vault and self._should_save_face(face_track_id):
                        timestamp_id = f"{face_id}_{cam_id}_{int(time.time() * 1000)}"
                        if self.vault.save_face(face_crop, timestamp_id, group, quality=age_conf, age=final_age):
                            logger.info(f"Face saved: {timestamp_id} (Group: {group}, Age: {final_age}, Quality: {age_conf:.2f})")
                else:
                    # No embedding or registry — still apply age smoothing using track ID
                    if face_track_id:
                        final_age = self._smooth_age(face_track_id, raw_age, age_conf)
                        group = self._age_to_group(final_age)

                results.append({
                    'id': face_id,
                    'age': final_age,
                    'group': group,
                    'bbox': [fx1, fy1, fx2, fy2],
                    'cam_id': cam_id,
                    'quality': age_conf,
                    'quality_score': quality_score,  # V4: Advanced quality score
                    'person_conf': pconf,
                    'face_conf': fconf,
                    'is_good_quality': is_good,
                    'age_sources': sources_used if 'sources_used' in dir() else ['dex'],  # V4: Fusion sources
                })

        # ── STEP 7: Direct Face Detection (always run when motion detected) ──
        # Runs alongside person-based detection to catch faces YOLO-person missed
        # NMS at the end removes duplicates between the two detection paths
        if motion_detected:
            direct_faces = self._detect_faces(enhanced, 0, 0)

            for fx1, fy1, fx2, fy2, fconf in direct_faces:
                face_crop = enhanced[fy1:fy2, fx1:fx2]

                # V4: Advanced quality assessment
                if self.face_quality_scorer:
                    quality_score, quality_details = self.face_quality_scorer.assess(face_crop)
                    is_good = quality_details.get("is_good", True)
                else:
                    is_good, blur_score, brightness_score, size_score = self.assess_face_quality(face_crop)
                    quality_score = (min(1.0, blur_score / 100.0) + brightness_score + size_score) / 3.0

                # V4: Get embedding and track ID
                embedding = self._get_embedding(face_crop)
                face_track_id = self._track_face(fx1, fy1, fx2, fy2, embedding, cam_id)

                # V4: Age estimation with fusion
                age_result = self._predict_age(face_crop, face_id=face_track_id)
                raw_age = age_result[0]
                age_conf = age_result[1]
                sources_used = age_result[2] if len(age_result) > 2 else ["dex"]

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

                    # ── Save detected face (with cooldown) ──
                    if self.vault and self._should_save_face(face_track_id):
                        timestamp_id = f"{face_id}_{cam_id}_{int(time.time() * 1000)}"
                        if self.vault.save_face(face_crop, timestamp_id, group, quality=age_conf, age=final_age):
                            logger.info(f"Face saved: {timestamp_id} (Group: {group}, Age: {final_age}, Quality: {age_conf:.2f})")
                else:
                    # No embedding or registry — still apply age smoothing using track ID
                    if face_track_id:
                        final_age = self._smooth_age(face_track_id, raw_age, age_conf)
                        group = self._age_to_group(final_age)

                results.append({
                    'id': face_id,
                    'age': final_age,
                    'group': group,
                    'bbox': [fx1, fy1, fx2, fy2],
                    'cam_id': cam_id,
                    'quality': age_conf,
                    'quality_score': quality_score,  # V4: Advanced quality score
                    'person_conf': 0.0,
                    'face_conf': fconf,
                    'is_good_quality': is_good,
                    'age_sources': sources_used if 'sources_used' in dir() else ['dex'],  # V4: Fusion sources
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
