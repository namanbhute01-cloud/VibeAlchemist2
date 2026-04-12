"""
Model Registry — maps Tier → model configs.
All modules import from here. Never hardcode model paths elsewhere.

V5 Adaptive Model Selection:
- Tier 1 (LOW):    YOLOv11n-face (384p)  — nano, lightweight
- Tier 2 (MEDIUM): YOLOv11s-face (512p)  — small, balanced
- Tier 3 (HIGH):   YOLOv11m-face (720p)  — medium, maximum accuracy

Base model family is ALWAYS YOLOv11. Tier only controls size variant.
"""
import os
from core.capability_detector import PROFILE


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def get_detection_config() -> dict:
    """
    YOLOv11 face/person detector config per tier.
    
    IMPROVED FOR RESTAURANT RANGE:
    - ALL tiers use lower confidence thresholds for maximum detection range
    - Resolution optimized for distant/small face detection
    - Multi-scale inference enabled for ALL tiers (in vision_pipeline.py)
    """
    model = _env("YOLO_FACE_MODEL", "models/yolov8n-face.onnx")
    
    # CRITICAL: Use yolov8n-face.onnx which EXISTS, not yolo11n-face.pt which doesn't
    if not os.path.exists(model):
        # Try alternative paths
        for fallback in ["models/yolov8n-face.onnx", "models/yolo11n-face.pt"]:
            if os.path.exists(fallback):
                model = fallback
                break

    if PROFILE.tier == 1:
        # IMPROVED Tier 1: 480p (was 384p) for better range
        # Lowered confidence to detect distant faces in restaurants
        return {"model": model, "imgsz": 480, "conf": 0.20}
    elif PROFILE.tier == 2:
        # IMPROVED Tier 2: 576p (was 512p) for better range
        # Lowered confidence for maximum distant face detection
        return {"model": model, "imgsz": 576, "conf": 0.15}
    else:
        # IMPROVED Tier 3: 704p (was 640p) for maximum range
        # Lowest confidence for longest distance detection
        return {"model": model, "imgsz": 704, "conf": 0.10}


def get_face_recognition_config() -> dict:
    """EdgeFace model path per tier."""
    if PROFILE.tier == 1:
        # Tier 1: buffalo_l fallback (already installed via insightface)
        return {
            "backend": "insightface",
            "model_name": "buffalo_l",
            "models_dir": _env("MODELS_DIR", "models"),
        }
    elif PROFILE.tier == 2:
        return {
            "backend": "edgeface",
            "model_path": _env("EDGEFACE_XS_MODEL", "models/edgeface_xs_int8.onnx"),
            "fallback_model": _env("EDGEFACE_XXS_MODEL", "models/edgeface_xxs_int8.onnx"),
        }
    else:
        return {
            "backend": "edgeface",
            "model_path": _env("EDGEFACE_BASE_MODEL", "models/edgeface_base_int8.onnx"),
            "fallback_model": _env("EDGEFACE_XS_MODEL", "models/edgeface_xs_int8.onnx"),
        }


def get_demographics_config() -> dict:
    """MiVOLO model config per tier."""
    if PROFILE.tier == 1:
        # IMPROVED Tier 1: Enable MiVOLO XXS for better accuracy (lightweight but better than DEX)
        return {
            "enabled": True,
            "model_path": _env("MIVOLO_XXS_MODEL", "models/mivolo_xxs.onnx"),
        }
    elif PROFILE.tier == 2:
        # IMPROVED Tier 2: MiVOLO XXS with higher update frequency
        return {
            "enabled": True,
            "model_path": _env("MIVOLO_XXS_MODEL", "models/mivolo_xxs.onnx"),
        }
    else:
        # IMPROVED Tier 3: MiVOLO Full — maximum demographics accuracy
        return {
            "enabled": True,
            "model_path": _env("MIVOLO_FULL_MODEL", "models/mivolo_full.onnx"),
        }


def get_emotion_config() -> dict:
    """Emotion model config per tier."""
    if PROFILE.tier == 1:
        return {"enabled": False}
    else:
        return {
            "enabled": True,
            "model_path": _env("FER_MODEL", "models/mobilenet_fer_int8.onnx"),
            "smooth_frames": 5 if PROFILE.tier == 2 else 3,
        }


def get_tracking_config() -> dict:
    """Tracker config per tier."""
    if PROFILE.tier == 1:
        return {"backend": "iou", "iou_threshold": 0.5}
    else:
        return {
            "backend": "bytetrack",
            "track_thresh": 0.5,
            "track_buffer": 30,
            "match_thresh": 0.8,
            "frame_rate": 15,
        }


def get_pipeline_schedule() -> dict:
    """
    How often to run each inference stage.
    
    IMPROVED FOR MAXIMUM ACCURACY:
    - Tier 1: More frequent recognition (every 10 frames, was 15)
    - Tier 2: Better update frequency for all features
    - Tier 3: Maximum update frequency for real-time accuracy
    """
    if PROFILE.tier == 1:
        # IMPROVED Tier 1: More frequent updates for better accuracy
        return {
            "detection_every": 1,    # every frame (fast, 480p)
            "recognition_every": 10, # IMPROVED: every 10 frames (was 15)
            "demographics_every": 8, # IMPROVED: every 8 frames (was 10)
            "emotion_every": 0,      # disabled for performance
            "vibe_update_every": 20, # IMPROVED: every 20 frames (was 30)
            "motion_gate_iou": 0.90, # IMPROVED: Lowered from 0.92 for better motion detection
        }
    elif PROFILE.tier == 2:
        # IMPROVED Tier 2: Better update frequency
        return {
            "detection_every": 1,
            "recognition_every": 4,  # IMPROVED: every 4 frames (was 5)
            "demographics_every": 4, # IMPROVED: every 4 frames (was 5)
            "emotion_every": 4,
            "vibe_update_every": 15, # IMPROVED: every 15 frames (was 20)
            "motion_gate_iou": 0.88, # IMPROVED: Lowered from 0.90
        }
    else:  # Tier 3
        # IMPROVED Tier 3: Maximum accuracy
        return {
            "detection_every": 1,
            "recognition_every": 2,
            "demographics_every": 2,  # IMPROVED: every 2 frames (was 3)
            "emotion_every": 2,       # IMPROVED: every 2 frames (was 3)
            "vibe_update_every": 8,   # IMPROVED: every 8 frames (was 10)
            "motion_gate_iou": 0.85,
        }


def get_onnx_providers() -> list:
    """ONNX Runtime execution providers per GPU availability."""
    if PROFILE.gpu == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    elif PROFILE.gpu == "mps":
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    else:
        return ["CPUExecutionProvider"]


def get_onnx_session_options():
    """ONNX session options — fewer threads on low-tier systems."""
    import onnxruntime as ort
    opts = ort.SessionOptions()
    if PROFILE.tier == 1:
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
    elif PROFILE.tier == 2:
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
    else:
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 2
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return opts
