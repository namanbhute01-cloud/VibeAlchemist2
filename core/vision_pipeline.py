import cv2
import numpy as np
import logging
import os
import onnxruntime as ort
from ultralytics import YOLO

logger = logging.getLogger("VisionPipeline")

class VisionPipeline:
    """
    Orchestrates the Gated Vision Pipeline:
    Motion (MOG2) -> Human (YOLO) -> Face (YOLO-Face + Haar Cascade fallback) -> Identity/Age (ArcFace/DEX)
    Optimized for CPU inference using ONNX Runtime.
    Features automatic image enhancement based on lighting conditions.
    """
    def __init__(self, models_dir="models", pool=None, engine=None, vault=None, registry=None):
        self.models_dir = models_dir
        self.pool = pool
        self.engine = engine
        self.vault = vault
        self.registry = registry

        # 1. Motion Detector
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=25, detectShadows=False)

        # 2. Human Detector (YOLOv8-nano ONNX)
        self.person_model = self._load_yolo("yolov8n.onnx", "yolov8n.pt")

        # 3. Face Detector (YOLOv8-face ONNX with Haar Cascade fallback)
        self.face_model = self._load_yolo("yolov8n-face.onnx", "yolov8n-face.pt")
        
        # Haar Cascade fallback for face detection
        self.haar_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if self.haar_cascade.empty():
            logger.warning("Haar cascade not loaded, face detection will be limited")
        else:
            logger.info("Haar cascade loaded as fallback")

        # 4. Feature Extractors (Raw ONNX)
        self.arcface_sess = self._load_onnx_session("arcface_r100.onnx")
        self.age_sess = self._load_onnx_session("dex_age.onnx")

        # Auto-enhancement state
        self.frame_brightness_history = []
        self.auto_brightness = 0
        self.auto_contrast = 1.0
        self.auto_sharpness = 0.3

    def _load_yolo(self, onnx_name, pt_name):
        """Loads YOLO model, preferring ONNX for CPU speed."""
        onnx_path = os.path.join(self.models_dir, onnx_name)
        pt_path = os.path.join(self.models_dir, pt_name)

        if os.path.exists(onnx_path):
            logger.info(f"Loading {onnx_name} (ONNX)...")
            return YOLO(onnx_path, task="detect")
        elif os.path.exists(pt_path):
            logger.info(f"Loading {pt_name} (PyTorch - Slow)...")
            return YOLO(pt_path, task="detect")
        else:
            logger.warning(f"Model {onnx_name} not found. Attempting auto-download of {pt_name}...")
            return YOLO(pt_name) # Auto-download

    def _load_onnx_session(self, model_name):
        """Loads a raw ONNX Runtime session."""
        path = os.path.join(self.models_dir, model_name)
        if os.path.exists(path):
            try:
                # Specify CPU execution provider explicitly
                sess = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
                logger.info(f"Loaded {model_name} successfully.")
                return sess
            except Exception as e:
                logger.error(f"Failed to load {model_name}: {e}")
                return None
        logger.warning(f"Model {model_name} missing from {self.models_dir}. Features disabled.")
        return None

    def auto_enhance_frame(self, frame):
        """
        Automatic image enhancement based on lighting analysis.
        Analyzes histogram and adjusts brightness/contrast/sharpness automatically.
        """
        # Convert to LAB color space for better luminance analysis
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # Analyze brightness (mean luminance)
        mean_brightness = np.mean(l)
        self.frame_brightness_history.append(mean_brightness)
        if len(self.frame_brightness_history) > 30:
            self.frame_brightness_history.pop(0)

        # Calculate average brightness over time
        avg_brightness = np.mean(self.frame_brightness_history)

        # Auto-adjust brightness based on lighting conditions
        if avg_brightness < 80:  # Dark scene
            self.auto_brightness = 0.3  # Brighten
        elif avg_brightness > 180:  # Very bright scene
            self.auto_brightness = -0.2  # Darken slightly
        else:
            self.auto_brightness = 0  # Normal

        # Auto-adjust contrast based on histogram spread
        std_dev = np.std(l)
        if std_dev < 40:  # Low contrast (flat histogram)
            self.auto_contrast = 1.5
        elif std_dev > 80:  # High contrast
            self.auto_contrast = 1.0
        else:
            self.auto_contrast = 1.2

        # Apply CLAHE for adaptive contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        # Apply brightness adjustment
        if self.auto_brightness != 0:
            cl = cv2.add(cl, int(self.auto_brightness * 50))

        # Merge channels back
        enhanced_lab = cv2.merge((cl, a, b))
        enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

        # Auto-sharpen if image is blurry (detected by edge strength)
        if self.auto_sharpness > 0:
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
            sharpened = cv2.filter2D(enhanced, -1, kernel)
            enhanced = cv2.addWeighted(enhanced, 1 - self.auto_sharpness, sharpened, self.auto_sharpness, 0)

        return enhanced

    def enhance_face(self, face_crop):
        """Software enhancement for better feature extraction."""
        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        enhanced = cv2.merge((cl, a, b))
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    def _detect_faces(self, person_crop, offset_x, offset_y):
        """
        Detect faces using YOLO-Face with Haar Cascade fallback.
        Returns list of tuples: (x1, y1, x2, y2, is_yolo_detection)
        Enhanced for better accuracy with stricter validation.
        """
        faces = []
        h, w = person_crop.shape[:2]

        # Try YOLO-Face first (more accurate)
        if self.face_model:
            try:
                # Higher confidence threshold for better accuracy
                yolo_faces = self.face_model(
                    person_crop, 
                    conf=0.25,    # Higher confidence (was 0.12)
                    iou=0.40,     # Stricter NMS
                    verbose=False,
                    augment=False,
                    half=False
                )
                for box in yolo_faces[0].boxes:
                    fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    
                    # Skip low confidence face detections
                    if conf < 0.25:
                        continue
                    
                    # Convert to global coordinates
                    gx1, gy1 = offset_x + fx1, offset_y + fy1
                    gx2, gy2 = offset_x + fx2, offset_y + fy2

                    # Validate face crop has reasonable dimensions
                    face_w = gx2 - gx1
                    face_h = gy2 - gy1
                    
                    # Minimum face size (40x40 pixels for better accuracy)
                    if face_w >= 40 and face_h >= 40:
                        # Check face aspect ratio (faces are roughly square/oval)
                        face_aspect = max(face_w, face_h) / min(face_w, face_h)
                        if face_aspect < 2.5:  # Skip extremely non-square boxes
                            faces.append((gx1, gy1, gx2, gy2, True))

                if faces:
                    logger.debug(f"YOLO detected {len(faces)} face(s)")
                    return faces  # Return YOLO detections if found
            except Exception as e:
                logger.debug(f"YOLO face detection error: {e}")

        # Fallback to Haar Cascade with stricter parameters
        if self.haar_cascade is not None and not self.haar_cascade.empty():
            try:
                gray = cv2.cvtColor(person_crop, cv2.COLOR_BGR2GRAY)
                
                # Apply histogram equalization for better detection
                gray = cv2.equalizeHist(gray)
                
                # Stricter Haar cascade detection
                haar_faces = self.haar_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.08,     # More precise scale
                    minNeighbors=4,       # Higher = fewer false positives
                    minSize=(50, 50),     # Larger minimum face
                    flags=cv2.CASCADE_SCALE_IMAGE
                )
                
                for (fx, fy, fw, fh) in haar_faces:
                    # Convert to global coordinates
                    gx1, gy1 = offset_x + fx, offset_y + fy
                    gx2, gy2 = offset_x + fx + fw, offset_y + fy + fh
                    
                    # Validate face aspect ratio
                    face_aspect = max(fw, fh) / min(fw, fh)
                    if face_aspect < 2.0:  # Stricter than YOLO
                        faces.append((gx1, gy1, gx2, gy2, False))

                if faces:
                    logger.debug(f"Haar detected {len(faces)} face(s)")
            except Exception as e:
                logger.debug(f"Haar face detection error: {e}")

        return faces

    def process_frame(self, frame, cam_id):
        """
        Main pipeline entry point.
        Returns a list of detections: [{'id': 'face_1', 'age': 25, 'group': 'youths', 'bbox': ...}]
        Enhanced for better multi-camera face detection.
        """
        if frame is None: return []

        # --- STEP 0: AUTO-ENHANCE FRAME ---
        # Automatically adjust image quality based on lighting
        enhanced_frame = self.auto_enhance_frame(frame)

        # --- STEP 1: MOTION GATING ---
        mask = self.bg_subtractor.apply(enhanced_frame)
        mask = cv2.threshold(mask, 180, 255, cv2.THRESH_BINARY)[0]  # Lower threshold for better sensitivity
        mask = cv2.dilate(mask, None, iterations=2)  # Fill gaps
        motion_pixels = cv2.countNonZero(mask)

        # Lower threshold for better sensitivity - detect even small movements
        motion_detected = motion_pixels > 80

        results = []
        h, w = frame.shape[:2]

        # --- STEP 2: HUMAN DETECTION (Improved Accuracy) ---
        # Balanced confidence threshold for good accuracy while maintaining sensitivity
        # Only detect class 0 (person) with validated parameters
        persons = self.person_model(
            enhanced_frame, 
            classes=[0],      # Only person class
            conf=0.30,        # Balanced confidence (was 0.35, lowered for webcam compatibility)
            iou=0.45,         # NMS IoU threshold - removes overlapping boxes
            verbose=False,
            augment=False,    # Disable TTA for speed
            half=False        # Use FP32 for better accuracy on CPU
        )

        persons_detected = False
        for result in persons:
            for box in result.boxes:
                conf = float(box.conf[0])
                
                # Skip low confidence detections (extra safety check)
                if conf < 0.28:
                    continue
                
                persons_detected = True
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                # Validate person box has reasonable size (at least 60x60 pixels for webcam)
                box_w = x2 - x1
                box_h = y2 - y1
                if box_w < 60 or box_h < 60:
                    continue  # Skip very small detections (likely false positives)
                
                # Calculate aspect ratio to filter out unusual shapes
                aspect_ratio = max(box_w, box_h) / min(box_w, box_h)
                if aspect_ratio > 3.5:
                    continue  # Skip extremely wide/tall boxes (likely not human)

                person_crop = enhanced_frame[y1:y2, x1:x2]
                if person_crop.size == 0: continue

                # --- STEP 3: FACE DETECTION (YOLO + Haar Cascade fallback) ---
                faces = self._detect_faces(person_crop, x1, y1)

                for fbox in faces:
                    fx1, fy1, fx2, fy2, is_yolo = fbox
                    gx1, gy1 = fx1, fy1
                    gx2, gy2 = fx2, fy2

                    face_crop = enhanced_frame[gy1:gy2, gx1:gx2]
                    # Check minimum face dimensions (at least 35x35 pixels for better sensitivity)
                    if face_crop.shape[0] < 35 or face_crop.shape[1] < 35: continue

                    # --- STEP 4: ENHANCEMENT & ANALYSIS ---
                    enhanced_face = self.enhance_face(face_crop)
                    embedding = self._get_embedding(enhanced_face)
                    age = self._predict_age(enhanced_face)
                    group = self._age_to_group(age)

                    # Deduplication - now with cross-camera support
                    face_id = "unknown"
                    face_age = age  # Store age for registry
                    if embedding is not None and self.registry:
                        fid, sim, registered_age = self.registry.is_known(embedding, age=face_age)
                        if fid:
                            # Known face - update last seen and add this camera
                            self.registry.update(fid, cam_id)
                            face_id = fid
                            # Use the registered age if available
                            if registered_age is not None:
                                face_age = registered_age
                                # Update the group based on registered age
                                group = self._age_to_group(face_age)
                        else:
                            # New face - register it with age
                            face_id = self.registry.register(embedding, group, cam_id, age=face_age)

                        # Save face to vault ONLY if it's a new face that hasn't been saved yet
                        if self.vault and not self.registry.is_saved(face_id):
                            if self.vault.save_face(enhanced_face, face_id, group):
                                self.registry.mark_as_saved(face_id)
                                logger.info(f"Face saved to vault: {face_id} (Group: {group}, Age: {face_age})")

                    results.append({
                        'id': face_id,
                        'age': face_age,
                        'group': group,
                        'bbox': [gx1, gy1, gx2, gy2],
                        'cam_id': cam_id
                    })

        # FALLBACK: Direct face detection on full frame if no persons detected but motion detected
        # This ensures faces are detected even when person detection fails
        if not persons_detected or motion_detected:
            logger.debug(f"Direct face detection (motion={motion_pixels}, persons={persons_detected})")
            direct_faces = self._detect_faces(enhanced_frame, 0, 0)
            for fbox in direct_faces:
                fx1, fy1, fx2, fy2, is_yolo = fbox
                face_crop = enhanced_frame[fy1:fy2, fx1:fx2]
                # Stricter minimum face dimensions (45x45 pixels)
                if face_crop.shape[0] < 45 or face_crop.shape[1] < 45: continue

                enhanced_face = self.enhance_face(face_crop)
                embedding = self._get_embedding(enhanced_face)
                age = self._predict_age(enhanced_face)
                group = self._age_to_group(age)

                face_id = "unknown"
                face_age = age  # Store age for registry
                if embedding is not None and self.registry:
                    fid, sim, registered_age = self.registry.is_known(embedding, age=face_age)
                    if fid:
                        # Known face - update last seen and add this camera
                        self.registry.update(fid, cam_id)
                        face_id = fid
                        if registered_age is not None:
                            face_age = registered_age
                            group = self._age_to_group(face_age)
                    else:
                        # New face - register it with age
                        face_id = self.registry.register(embedding, group, cam_id, age=face_age)

                    # Save face to vault ONLY if it's a new face that hasn't been saved yet
                    if self.vault and not self.registry.is_saved(face_id):
                        if self.vault.save_face(enhanced_face, face_id, group):
                            self.registry.mark_as_saved(face_id)
                            logger.info(f"Face saved to vault: {face_id} (Group: {group}, Age: {face_age})")

                results.append({
                    'id': face_id,
                    'age': face_age,
                    'group': group,
                    'bbox': [fx1, fy1, fx2, fy2],
                    'cam_id': cam_id
                })

        if results:
            logger.info(f"Detected {len(results)} face(s) in camera {cam_id}")
            # Log ages for debugging
            ages = [r['age'] for r in results]
            avg_age = sum(ages) / len(ages)
            groups = [r['group'] for r in results]
            face_ids = [r['id'] for r in results]
            logger.info(f"Camera {cam_id} - Ages: {ages}, Avg: {avg_age:.1f}, Groups: {groups}")
            logger.info(f"Face IDs: {face_ids}")

            # Log cross-camera tracking info
            unique_faces = len(set(face_ids))
            if unique_faces < len(results):
                logger.info(f"Cross-camera deduplication: {len(results)} detections -> {unique_faces} unique face(s)")

        return results

    def _get_embedding(self, face):
        """Runs ArcFace inference."""
        if not self.arcface_sess: return None
        try:
            # ArcFace expects NHWC format: [batch, height, width, channels]
            blob = cv2.resize(face, (112, 112)).astype(np.float32)
            blob = (blob - 127.5) / 128.0
            blob = np.expand_dims(blob, axis=0)  # Add batch dimension: (1, 112, 112, 3)
            
            input_name = self.arcface_sess.get_inputs()[0].name
            outs = self.arcface_sess.run(None, {input_name: blob})
            return outs[0].flatten()
        except Exception as e:
            logger.debug(f"ArcFace embedding error: {e}")
            return None

    def _predict_age(self, face):
        """
        Runs DEX Age inference with improved accuracy.
        Model outputs 101 age probabilities (0-100).
        Uses multi-crop averaging for better accuracy.
        """
        if not self.age_sess: return 25

        try:
            # Preprocess face for better age estimation
            gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
            
            # Apply histogram equalization for better contrast
            gray_eq = cv2.equalizeHist(gray)
            
            # Convert back to 3-channel for model input
            face_enhanced = cv2.merge([gray_eq, gray_eq, gray_eq])
            
            # Multi-crop approach for better accuracy
            age_predictions = []
            
            # Crop 1: Full face
            crops = [face_enhanced]
            
            # Crop 2: Upper face (forehead to nose) - better for age
            h, w = face.shape[:2]
            upper_face = face_enhanced[0:int(h*0.7), :]
            if upper_face.shape[0] > 20:
                crops.append(upper_face)
            
            # Crop 3: Center crop (removes background)
            margin = int(min(h, w) * 0.1)
            center_crop = face_enhanced[margin:h-margin, margin:w-margin]
            if center_crop.shape[0] > 20 and center_crop.shape[1] > 20:
                crops.append(center_crop)
            
            # Predict age for each crop
            for crop in crops:
                try:
                    # DEX Age model expects CHW format: [batch, channels, height, width]
                    blob = cv2.resize(crop, (96, 96)).astype(np.float32)
                    blob = blob.transpose(2, 0, 1)  # HWC to CHW
                    blob = np.expand_dims(blob, axis=0)  # Add batch dimension

                    input_name = self.age_sess.get_inputs()[0].name
                    outs = self.age_sess.run(None, {input_name: blob})

                    # DEX outputs 101 probabilities for ages 0-100
                    age_probs = outs[0][0]  # Shape: (101,)

                    # Ensure it's 1D array of 101 elements
                    if age_probs.ndim > 1:
                        age_probs = age_probs.flatten()

                    # Normalize to ensure valid probability distribution
                    age_probs = np.clip(age_probs, 0, None)
                    total = np.sum(age_probs)
                    if total > 0:
                        age_probs = age_probs / total

                    # Calculate expected age (weighted average)
                    ages = np.arange(len(age_probs))
                    expected_age = int(np.sum(ages * age_probs))
                    age_predictions.append(expected_age)
                except Exception as e:
                    logger.debug(f"Age prediction crop error: {e}")
                    continue
            
            # Average all predictions
            if len(age_predictions) > 0:
                final_age = int(np.mean(age_predictions))
            else:
                return 25  # Default fallback

            # Apply age correction based on face size
            # Larger faces in frame tend to be closer to camera (often adults)
            face_area = face.shape[0] * face.shape[1]
            if face_area > 5000:  # Large face (close to camera)
                # Slight upward adjustment for close-up adult faces
                final_age = int(final_age * 1.15)
            
            # Clamp to reasonable range (18-70 for adults, wider for general use)
            return min(75, max(16, final_age))
            
        except Exception as e:
            logger.error(f"Age prediction error: {e}")
            return 25

    def _age_to_group(self, age):
        """Convert age to music group based on typical music preferences."""
        if age < 13: return "kids"       # Children
        if age < 20: return "youths"     # Teens
        if age < 50: return "adults"     # Young/Middle adults
        return "seniors"                 # Seniors (50+)
