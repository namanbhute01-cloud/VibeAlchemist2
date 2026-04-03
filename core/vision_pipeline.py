"""
Vision Pipeline V2 - Improved Age Detection Pipeline

Orchestrates: Motion Gating → Human Detection → Face Detection → Age Estimation → Identity Matching

Improvements over V1:
- Stricter human validation (aspect ratio, size, confidence)
- Face alignment before age/embedding extraction
- Temporal age smoothing (rolling average per face identity)
- Face quality scoring (blur, size, pose estimation)
- Better multi-camera deduplication with higher ArcFace threshold
- No duplicate detections between person-crop and direct detection paths
- Confidence-weighted age predictions with rejection of low-quality faces
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

        # ── Human Detector (YOLOv8-nano) ──
        self.person_model = self._load_yolo("yolov8n.onnx", "yolov8n.pt")

        # ── Face Detector (YOLOv8-face with Haar fallback) ──
        self.face_model = self._load_yolo("yolov8n-face.onnx", "yolov8n-face.pt")

        # Haar Cascade fallback
        self.haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        # ── Feature Extractors ──
        self.arcface_sess = self._load_onnx_session("arcface_r100.onnx")
        self.age_sess = self._load_onnx_session("dex_age.onnx")

        # ── Face Alignment (Dlib-style 5-point landmark model via Haar approx) ──
        # We use eye-detection approximation for alignment without extra model
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_eye.xml'
        )

        # ── Auto-enhancement state ──
        self.frame_brightness_history = []

        # ── Temporal age smoothing per face identity ──
        # face_id -> deque of recent age predictions
        self.age_history = {}
        self.age_smoothing_window = 5  # Average last 5 predictions per face

        # ── Detection deduplication within a single frame ──
        self.frame_nms_iou = 0.5  # IoU threshold for within-frame NMS

        # ── Face quality thresholds ──
        self.min_face_size = 50  # Minimum face width/height in pixels
        self.max_blur_score = 100  # Laplacian variance below this = blurry
        self.max_aspect_ratio = 2.0  # Face box aspect ratio limit

        # ── Human detection thresholds ──
        self.person_conf_threshold = 0.35  # Minimum confidence for person
        self.min_person_size = 80  # Minimum person box dimension
        self.max_person_aspect = 3.0  # Max width/height ratio

        logger.info("VisionPipeline V2 initialized with improved accuracy settings")

    # ═══════════════════════════════════════════════════════════════
    # Model Loading
    # ═══════════════════════════════════════════════════════════════

    def _load_yolo(self, onnx_name, pt_name):
        """Load YOLO model, preferring ONNX for CPU speed."""
        onnx_path = os.path.join(self.models_dir, onnx_name)
        pt_path = os.path.join(self.models_dir, pt_name)

        if os.path.exists(onnx_path):
            logger.info(f"Loading {onnx_name} (ONNX)")
            return YOLO(onnx_path, task="detect")
        elif os.path.exists(pt_path):
            logger.info(f"Loading {pt_name} (PyTorch)")
            return YOLO(pt_path, task="detect")
        else:
            logger.warning(f"Model {onnx_name} not found. Auto-downloading {pt_name}...")
            return YOLO(pt_name)

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
        """Enhance frame based on lighting analysis."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        mean_brightness = np.mean(l)
        self.frame_brightness_history.append(mean_brightness)
        if len(self.frame_brightness_history) > 30:
            self.frame_brightness_history.pop(0)

        avg_brightness = np.mean(self.frame_brightness_history)
        std_dev = np.std(l)

        # CLAHE for adaptive contrast
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
        Assess face quality for reliable age estimation.
        Returns (is_good, blur_score, brightness_score, size_score).
        """
        h, w = face_crop.shape[:2]
        size = min(h, w)

        # Size score: larger faces are better
        size_score = min(1.0, size / 100.0)

        # Blur detection via Laplacian variance
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        is_sharp = blur_score > self.max_blur_score

        # Brightness check
        brightness = np.mean(gray)
        brightness_score = 1.0 - abs(brightness - 127) / 127.0
        is_well_lit = 40 < brightness < 220

        # Overall quality
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
                    conf=0.30,     # Higher confidence threshold
                    iou=0.35,      # Stricter NMS
                    verbose=False,
                    augment=False,
                    half=False
                )
                for box in yolo_faces[0].boxes:
                    fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])

                    if conf < 0.30:
                        continue

                    gx1, gy1 = offset_x + fx1, offset_y + fy1
                    gx2, gy2 = offset_x + fx2, offset_y + fy2

                    face_w = gx2 - gx1
                    face_h = gy2 - gy1

                    # Minimum face size
                    if face_w < self.min_face_size or face_h < self.min_face_size:
                        continue

                    # Aspect ratio validation
                    aspect = max(face_w, face_h) / min(face_w, face_h)
                    if aspect > self.max_aspect_ratio:
                        continue

                    faces.append((gx1, gy1, gx2, gy2, conf))

                if faces:
                    return faces
            except Exception as e:
                logger.debug(f"YOLO face detection error: {e}")

        # ── Haar Cascade Fallback ──
        if self.haar_cascade is not None and not self.haar_cascade.empty():
            try:
                gray = cv2.cvtColor(person_crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)

                haar_faces = self.haar_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.08,
                    minNeighbors=5,
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
        Predict age with multi-crop approach and quality assessment.
        Returns (age, confidence).
        """
        if not self.age_sess:
            return 25, 0.0

        try:
            # Assess quality first
            is_good, blur, brightness, size = self.assess_face_quality(face)
            quality_score = (min(1.0, blur / 200.0) + brightness + size) / 3.0

            # Reject very low quality faces
            if not is_good:
                return 25, max(0.0, quality_score * 0.5)

            # Align face for better age estimation
            aligned_face = self.align_face(face)

            # Multi-crop approach
            age_predictions = []
            weights = []

            # Crop 1: Full face (weight: 1.0)
            crops = [(aligned_face, 1.0)]

            # Crop 2: Upper face (forehead to nose) - better for age (weight: 0.7)
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

                    # Confidence based on prediction sharpness
                    peak_prob = np.max(age_probs)
                    crop_conf = min(1.0, peak_prob * 5)  # Scale to 0-1

                    age_predictions.append(expected_age)
                    weights.append(weight * crop_conf)
                except Exception:
                    continue

            if not age_predictions:
                return 25, 0.0

            # Weighted average
            weights = np.array(weights)
            weights = weights / np.sum(weights)
            raw_age = int(np.average(age_predictions, weights=weights))

            # ── Age Correction Factor ──
            # DEX model systematically underestimates adult ages.
            # Apply correction based on detected age range:
            if raw_age < 12:
                # Children: slight upward correction
                corrected_age = int(raw_age * 1.1)
            elif raw_age < 18:
                # Teens: moderate correction
                corrected_age = int(raw_age * 1.15)
            elif raw_age < 30:
                # Young adults: significant correction (most common error range)
                # DEX often detects 25-40 year olds as 18-25
                corrected_age = int(raw_age * 1.35)
            elif raw_age < 45:
                # Middle adults: moderate correction
                corrected_age = int(raw_age * 1.2)
            elif raw_age < 60:
                # Older adults: slight correction
                corrected_age = int(raw_age * 1.1)
            else:
                # Seniors: minimal correction
                corrected_age = int(raw_age * 1.05)

            # Clamp to reasonable range
            final_age = min(80, max(16, corrected_age))

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
        Returns smoothed age.
        """
        if face_id not in self.age_history:
            self.age_history[face_id] = []

        history = self.age_history[face_id]
        history.append((raw_age, confidence))

        # Keep only recent predictions
        if len(history) > self.age_smoothing_window:
            history.pop(0)

        # Weighted average (more recent = higher weight)
        if len(history) == 0:
            return raw_age

        ages = [h[0] for h in history]
        confs = [max(0.1, h[1]) for h in history]

        # Exponential weighting: most recent gets highest weight
        time_weights = np.exp(np.linspace(0, 1, len(confs)))
        final_weights = np.array(confs) * time_weights
        final_weights = final_weights / np.sum(final_weights)

        smoothed_age = int(np.average(ages, weights=final_weights))

        # Clamp to reasonable range
        return min(75, max(16, smoothed_age))

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
        """Convert age to music group."""
        if age < 13:
            return "kids"
        elif age < 20:
            return "youths"
        elif age < 50:
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

        # ── STEP 0: Auto-enhance ──
        enhanced = self.auto_enhance_frame(frame)

        # ── STEP 1: Motion Gating ──
        mask = self.bg_subtractor.apply(enhanced)
        mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)[0]
        mask = cv2.dilate(mask, None, iterations=2)
        motion_pixels = cv2.countNonZero(mask)
        motion_detected = motion_pixels > 80

        results = []
        h, w = frame.shape[:2]

        # ── STEP 2: Human Detection (strict) ──
        persons = self.person_model(
            enhanced,
            classes=[0],       # Only person
            conf=self.person_conf_threshold,
            iou=0.45,
            verbose=False,
            augment=False,
            half=False
        )

        person_boxes = []
        for result in persons:
            for box in result.boxes:
                conf = float(box.conf[0])

                # Strict confidence check
                if conf < self.person_conf_threshold:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)

                box_w = x2 - x1
                box_h = y2 - y1

                # Size validation
                if box_w < self.min_person_size or box_h < self.min_person_size:
                    continue

                # Aspect ratio validation (humans are roughly vertical)
                aspect = max(box_w, box_h) / min(box_w, box_h)
                if aspect > self.max_person_aspect:
                    continue

                # Body proportion check: height should be > width for standing/sitting humans
                if box_h < box_w * 0.4:
                    continue  # Too wide, likely not a human

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
                        # New face - register
                        face_id = self.registry.register(embedding, group, cam_id, age=raw_age)

                    # ── STEP 6: Temporal Age Smoothing ──
                    final_age = self._smooth_age(face_id, raw_age, age_conf)
                    group = self._age_to_group(final_age)

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

        # ── STEP 7: Direct Face Detection Fallback ──
        # Only run if no persons detected but motion detected
        # This catches faces that person detection misses
        if not person_boxes and motion_detected:
            logger.debug(f"Direct face detection fallback (motion={motion_pixels})")
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
                        face_id = self.registry.register(embedding, group, cam_id, age=raw_age)

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
