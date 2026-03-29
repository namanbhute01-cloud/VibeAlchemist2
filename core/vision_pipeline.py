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
    Motion (MOG2) -> Human (YOLO) -> Face (YOLO-Face) -> Identity/Age (ArcFace/DEX)
    Optimized for CPU inference using ONNX Runtime.
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
        
        # 3. Face Detector (YOLOv8-face ONNX)
        self.face_model = self._load_yolo("yolov8n-face.onnx", "yolov8n-face.pt")
        
        # 4. Feature Extractors (Raw ONNX)
        self.arcface_sess = self._load_onnx_session("arcface_r100.onnx")
        self.age_sess = self._load_onnx_session("dex_age.onnx")

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

    def enhance_face(self, face_crop):
        """Software enhancement for better feature extraction."""
        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        enhanced = cv2.merge((cl, a, b))
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    def process_frame(self, frame, cam_id):
        """
        Main pipeline entry point.
        Returns a list of detections: [{'id': 'face_1', 'age': 25, 'group': 'youths', 'bbox': ...}]
        """
        if frame is None: return []

        # --- STEP 1: MOTION GATING ---
        mask = self.bg_subtractor.apply(frame)
        motion_pixels = cv2.countNonZero(mask)
        
        # Lower threshold for better sensitivity (was 500)
        if motion_pixels < 200:
            return []

        results = []
        h, w = frame.shape[:2]

        # --- STEP 2: HUMAN DETECTION ---
        # Lower confidence threshold for better detection (was 0.4)
        persons = self.person_model(frame, classes=[0], conf=0.3, verbose=False)

        for result in persons:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)

                person_crop = frame[y1:y2, x1:x2]
                if person_crop.size == 0: continue

                # --- STEP 3: FACE DETECTION ---
                # Lower confidence for face detection (was 0.5)
                faces = self.face_model(person_crop, conf=0.3, verbose=False)

                for fbox in faces[0].boxes:
                    fx1, fy1, fx2, fy2 = map(int, fbox.xyxy[0])
                    gx1, gy1 = x1 + fx1, y1 + fy1
                    gx2, gy2 = x1 + fx2, y1 + fy2

                    face_crop = person_crop[fy1:fy2, fx1:fx2]
                    # Lower minimum face size (was 400)
                    if face_crop.size < 200: continue

                    # --- STEP 4: ENHANCEMENT & ANALYSIS ---
                    enhanced_face = self.enhance_face(face_crop)
                    embedding = self._get_embedding(enhanced_face)
                    age = self._predict_age(enhanced_face)
                    group = self._age_to_group(age)

                    # Deduplication
                    face_id = "unknown"
                    if embedding is not None and self.registry:
                        fid, sim = self.registry.is_known(embedding)
                        if fid:
                            self.registry.update(fid, cam_id)
                            face_id = fid
                        else:
                            face_id = self.registry.register(embedding, group, cam_id)
                            # Save new faces to vault
                            if self.vault:
                                self.vault.save_face(enhanced_face, face_id, group)
                                logger.info(f"Face saved to vault: {face_id} ({group})")

                    results.append({
                        'id': face_id,
                        'age': age,
                        'group': group,
                        'bbox': [gx1, gy1, gx2, gy2],
                        'cam_id': cam_id
                    })

        if results:
            logger.info(f"Detected {len(results)} face(s) in camera {cam_id}")
        
        return results

    def _get_embedding(self, face):
        """Runs ArcFace inference."""
        if not self.arcface_sess: return None
        blob = cv2.resize(face, (112, 112)).transpose(2, 0, 1).astype(np.float32)
        blob = np.expand_dims(blob, axis=0)
        blob = (blob - 127.5) / 128.0
        
        try:
            outs = self.arcface_sess.run(None, {self.arcface_sess.get_inputs()[0].name: blob})
            return outs[0].flatten()
        except:
            return None

    def _predict_age(self, face):
        """Runs DEX Age inference."""
        if not self.age_sess: return 25
        blob = cv2.resize(face, (224, 224)).transpose(2, 0, 1).astype(np.float32)
        blob = np.expand_dims(blob, axis=0)
        
        try:
            outs = self.age_sess.run(None, {self.age_sess.get_inputs()[0].name: blob})
            logits = outs[0][0]
            probs = np.exp(logits) / np.sum(np.exp(logits))
            age = np.sum(probs * np.arange(101))
            return int(age)
        except:
            return 25

    def _age_to_group(self, age):
        if age < 13: return "kids"
        if age < 25: return "youths"
        if age < 60: return "adults"
        return "seniors"
