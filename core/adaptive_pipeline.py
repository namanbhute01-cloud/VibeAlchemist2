"""
AdaptivePipeline — the central coordinator for VibeAlchemist V5.
On init it reads PROFILE.tier and builds the right combination of
detectors, recognizers, demographics engines, and trackers.

Replaces: separate detector + recognizer + demographics + emotion + tracker.
All other modules call pipeline.process(frame) and get back a result.
"""
import cv2
import numpy as np
import logging
import time
from core.capability_detector import PROFILE
from core.model_registry import (
    get_detection_config, get_face_recognition_config,
    get_demographics_config, get_emotion_config,
    get_tracking_config, get_pipeline_schedule,
    get_onnx_providers, get_onnx_session_options,
)

logger = logging.getLogger(__name__)


class AdaptivePipeline:
    def __init__(self):
        self._frame_n = 0
        self._schedule = get_pipeline_schedule()
        self._last_result = self._empty_result()

        logger.info(f"AdaptivePipeline: Tier {PROFILE.tier} — "
                    f"{PROFILE.summary()['tier_name']}")
        logger.info(f"Schedule: {self._schedule}")

        self._init_detector()
        self._init_recognizer()
        self._init_demographics()
        self._init_emotion()
        self._init_tracker()

        # Face vault for enrolling known faces
        self._vault: dict = {}  # name -> embedding

    def _empty_result(self) -> dict:
        return {
            "persons": [],
            "primary_name": "unknown",
            "age": 25.0,
            "gender": "unknown",
            "emotion": "neutral",
            "energy": 0.5,
            "crowd_size": 0,
            "tier": PROFILE.tier,
            "latency_ms": 0.0,
        }

    # ── Component init with graceful fallback ───────────────────────────────
    def _init_detector(self):
        cfg = get_detection_config()
        try:
            from ultralytics import YOLO
            self._detector = YOLO(cfg["model"])
            self._det_imgsz = cfg["imgsz"]
            self._det_conf = cfg["conf"]
            logger.info(f"Detector: YOLOv8n-face @ {self._det_imgsz}p, conf={self._det_conf}")
        except Exception as e:
            logger.error(f"Detector init failed: {e} — detection disabled")
            self._detector = None
            self._det_imgsz = 240
            self._det_conf = 0.45

    def _init_recognizer(self):
        cfg = get_face_recognition_config()
        self._recognizer = None

        if cfg["backend"] == "insightface":
            try:
                import insightface
                app = insightface.app.FaceAnalysis(
                    name=cfg["model_name"], root=cfg["models_dir"])
                app.prepare(ctx_id=-1, det_size=(640, 640))
                self._recognizer = ("insightface", app)
                logger.info("Recognizer: InsightFace buffalo_l (Tier 1 fallback)")
            except Exception as e:
                logger.error(f"InsightFace init failed: {e}")
        else:
            # Try EdgeFace ONNX
            import onnxruntime as ort
            for path_key in ("model_path", "fallback_model"):
                model_path = cfg.get(path_key, "")
                if model_path and os.path.exists(model_path):
                    try:
                        sess = ort.InferenceSession(
                            model_path,
                            sess_options=get_onnx_session_options(),
                            providers=get_onnx_providers()
                        )
                        self._recognizer = ("edgeface", sess)
                        logger.info(f"Recognizer: EdgeFace ONNX @ {model_path}")
                        break
                    except Exception as e:
                        logger.warning(f"EdgeFace load failed ({path_key}): {e}")

            if self._recognizer is None:
                logger.warning("No EdgeFace model found — falling back to InsightFace")
                self._init_recognizer_insightface_fallback(cfg)

    def _init_recognizer_insightface_fallback(self, cfg):
        try:
            import insightface
            app = insightface.app.FaceAnalysis(
                name="buffalo_l", root=cfg.get("models_dir", "models"))
            app.prepare(ctx_id=-1, det_size=(640, 640))
            self._recognizer = ("insightface", app)
            logger.info("Recognizer: InsightFace buffalo_l (fallback)")
        except Exception as e:
            logger.error(f"InsightFace fallback also failed: {e}")

    def _init_demographics(self):
        cfg = get_demographics_config()
        self._demographics = None
        if not cfg["enabled"]:
            logger.info("Demographics: DISABLED (Tier 1)")
            return
        import os, onnxruntime as ort
        if os.path.exists(cfg["model_path"]):
            try:
                self._demographics = ort.InferenceSession(
                    cfg["model_path"],
                    sess_options=get_onnx_session_options(),
                    providers=get_onnx_providers()
                )
                logger.info(f"Demographics: MiVOLO @ {cfg['model_path']}")
            except Exception as e:
                logger.warning(f"Demographics init failed: {e} — disabled")
        else:
            logger.warning(f"Demographics model not found: {cfg['model_path']} — disabled")

    def _init_emotion(self):
        cfg = get_emotion_config()
        self._emotion = None
        self._emotion_history = []
        self._emotion_smooth = cfg.get("smooth_frames", 5)
        if not cfg["enabled"]:
            logger.info("Emotion: DISABLED (Tier 1)")
            return
        import os, onnxruntime as ort
        if os.path.exists(cfg["model_path"]):
            try:
                self._emotion = ort.InferenceSession(
                    cfg["model_path"],
                    sess_options=get_onnx_session_options(),
                    providers=get_onnx_providers()
                )
                logger.info(f"Emotion: MobileNet FER @ {cfg['model_path']}")
            except Exception as e:
                logger.warning(f"Emotion init failed: {e} — disabled")
        else:
            logger.warning(f"Emotion model not found: {cfg['model_path']} — disabled")

    def _init_tracker(self):
        cfg = get_tracking_config()
        self._tracker = None
        self._track_id_to_name: dict = {}
        if cfg["backend"] == "bytetrack":
            try:
                from bytetracker import BYTETracker
                self._tracker = BYTETracker(
                    track_thresh=cfg["track_thresh"],
                    track_buffer=cfg["track_buffer"],
                    match_thresh=cfg["match_thresh"],
                    frame_rate=cfg["frame_rate"],
                )
                logger.info("Tracker: ByteTrack")
            except ImportError:
                logger.warning("ByteTrack not installed — using IoU fallback")
        else:
            logger.info("Tracker: simple IoU (Tier 1)")

    # ── Main process entry point ────────────────────────────────────────────
    def process(self, frame: np.ndarray) -> dict:
        """
        Called every frame from WebSocket handler (in executor thread).
        Returns result dict. Uses cached result when skipping inference.
        """
        t0 = time.perf_counter()
        self._frame_n += 1
        result = dict(self._last_result)  # start from cached

        # Always run detection (fast, low-res)
        detections = self._detect(frame)
        result["crowd_size"] = len(detections)
        result["persons"] = [{"bbox": d["bbox"].tolist()} for d in detections]

        # Recognition — run every N frames
        sched = self._schedule
        if detections and self._frame_n % sched["recognition_every"] == 0:
            name = self._recognize(detections[0]["face_crop"])
            result["primary_name"] = name

        # Demographics — run every N frames (disabled on Tier 1)
        if (detections and sched["demographics_every"] > 0
                and self._frame_n % sched["demographics_every"] == 0):
            demo = self._estimate_demographics(
                detections[0]["face_crop"], detections[0]["body_crop"])
            result["age"] = demo["age"]
            result["gender"] = demo["gender"]

        # Emotion — run every N frames (disabled on Tier 1)
        if (detections and sched["emotion_every"] > 0
                and self._frame_n % sched["emotion_every"] == 0):
            emo = self._detect_emotion(detections[0]["face_crop"])
            result["emotion"] = emo["emotion"]
            result["energy"] = emo["energy"]

        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self._last_result = result
        return result

    # ── Internal inference helpers ──────────────────────────────────────────
    def _detect(self, frame: np.ndarray) -> list:
        if self._detector is None:
            return []
        h, w = frame.shape[:2]
        scale = self._det_imgsz / h
        small = cv2.resize(frame, (int(w * scale), self._det_imgsz))
        try:
            res = self._detector(small, verbose=False, classes=[0], conf=self._det_conf)
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return []
        out = []
        if res and res[0].boxes:
            for box in res[0].boxes:
                x1, y1, x2, y2 = [int(v / scale) for v in box.xyxy[0].tolist()]
                x1 = max(0, x1); y1 = max(0, y1); x2 = min(w, x2); y2 = min(h, y2)
                body = frame[y1:y2, x1:x2]
                face_h = int((y2 - y1) * 0.42)
                face = frame[y1:y1 + face_h, x1:x2]
                if body.size > 0 and face.size > 0:
                    out.append({
                        "bbox": np.array([x1, y1, x2, y2]),
                        "face_crop": face,
                        "body_crop": body,
                        "conf": float(box.conf[0]),
                    })
        return out

    def _recognize(self, face_crop: np.ndarray) -> str:
        if self._recognizer is None:
            return "unknown"
        try:
            backend, model = self._recognizer
            if backend == "edgeface":
                img = cv2.resize(face_crop, (112, 112))
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
                img = (img - 127.5) / 127.5
                inp = img.transpose(2, 0, 1)[np.newaxis]
                emb = model.run(None, {"input": inp})[0][0]
            else:  # insightface
                faces = model.get(face_crop)
                if not faces:
                    return "unknown"
                emb = faces[0].embedding
            emb = emb / (np.linalg.norm(emb) + 1e-6)
            return self._match_vault(emb)
        except Exception as e:
            logger.error(f"Recognition error: {e}")
            return "unknown"

    def _match_vault(self, embedding: np.ndarray) -> str:
        threshold = float(
            __import__("os").getenv("FACE_SIMILARITY_THRESHOLD", 0.65))
        best_name, best_sim = "unknown", -1.0
        for name, stored in self._vault.items():
            sim = float(np.dot(embedding, stored))
            if sim > best_sim:
                best_sim, best_name = sim, name
        return best_name if best_sim >= threshold else "unknown"

    def enroll_face(self, name: str, face_crop: np.ndarray):
        """Public: call from /faces/enroll endpoint."""
        emb_raw = self._recognize_raw(face_crop)
        if emb_raw is not None:
            self._vault[name] = emb_raw / (np.linalg.norm(emb_raw) + 1e-6)
            logger.info(f"Enrolled: {name}")

    def _recognize_raw(self, face_crop):
        try:
            backend, model = self._recognizer
            if backend == "edgeface":
                img = cv2.resize(face_crop, (112, 112))
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
                img = (img - 127.5) / 127.5
                return model.run(None, {"input": img.transpose(2, 0, 1)[np.newaxis]})[0][0]
            else:
                faces = model.get(face_crop)
                return faces[0].embedding if faces else None
        except Exception:
            return None

    def _estimate_demographics(self, face_crop, body_crop) -> dict:
        if self._demographics is None:
            return {"age": 25.0, "gender": "unknown"}
        try:
            def prep(img, sz):
                img = cv2.resize(img, sz)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                img = (img - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
                return img.transpose(2, 0, 1)[np.newaxis]
            outs = self._demographics.run(None, {
                "face": prep(face_crop, (112, 112)),
                "body": prep(body_crop, (192, 256))
            })
            age = float(max(0, min(100, outs[0][0])))
            gender = ["male", "female"][int(np.argmax(outs[1][0]))]
            return {"age": age, "gender": gender}
        except Exception as e:
            logger.error(f"Demographics error: {e}")
            return {"age": 25.0, "gender": "unknown"}

    def _detect_emotion(self, face_crop) -> dict:
        LABELS = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]
        if self._emotion is None:
            return {"emotion": "neutral", "energy": 0.5}
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (48, 48)).astype(np.float32) / 255.0
            out = self._emotion.run(None, {"input": gray[np.newaxis, np.newaxis]})[0][0]
            self._emotion_history.append(out)
            if len(self._emotion_history) > self._emotion_smooth:
                self._emotion_history.pop(0)
            avg = np.mean(self._emotion_history, axis=0)
            scores = dict(zip(LABELS, avg.tolist()))
            best = max(scores, key=scores.get)
            energy = min(1.0, scores.get("happy", 0) * 0.6 + scores.get("surprise", 0) * 0.4)
            return {"emotion": best, "energy": energy, "scores": scores}
        except Exception as e:
            logger.error(f"Emotion error: {e}")
            return {"emotion": "neutral", "energy": 0.5}

    def get_tier_info(self) -> dict:
        return {
            **PROFILE.summary(),
            "schedule": self._schedule,
            "recognizer": self._recognizer[0] if self._recognizer else "none",
            "demographics_active": self._demographics is not None,
            "emotion_active": self._emotion is not None,
            "tracker": "bytetrack" if self._tracker else "iou",
        }
