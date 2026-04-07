"""
Model Registry — maps Tier to model configs.
All modules import from here. Never hardcode model paths elsewhere.
"""
import os
from core.capability_detector import PROFILE


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def get_detection_config() -> dict:
    """YOLOv8 face/person detector config per tier."""
    base = {"model": _env("YOLO_FACE_MODEL", "models/yolov8n-face.onnx")}
    if PROFILE.tier == 1:
        return {**base, "imgsz": 240, "conf": 0.45}
    elif PROFILE.tier == 2:
        return {**base, "imgsz": 480, "conf": 0.40}
    else:
        return {**base, "imgsz": 640, "conf": 0.35}


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
        return {"enabled": False}
    elif PROFILE.tier == 2:
        return {
            "enabled": True,
            "model_path": _env("MIVOLO_XXS_MODEL", "models/mivolo_xxs.onnx"),
        }
    else:
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
    Tier 1 = most aggressive skipping.
    """
    if PROFILE.tier == 1:
        return {
            "detection_every": 1,    # every frame (fast, 240p)
            "recognition_every": 15, # every 15 frames
            "demographics_every": 0, # disabled
            "emotion_every": 0,      # disabled
            "vibe_update_every": 30, # every 30 frames
            "motion_gate_iou": 0.92,
        }
    elif PROFILE.tier == 2:
        return {
            "detection_every": 1,
            "recognition_every": 5,
            "demographics_every": 5,
            "emotion_every": 5,
            "vibe_update_every": 20,
            "motion_gate_iou": 0.90,
        }
    else:  # Tier 3
        return {
            "detection_every": 1,
            "recognition_every": 2,
            "demographics_every": 3,
            "emotion_every": 3,
            "vibe_update_every": 10,
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
    """ONNX session options - fewer threads on low-tier systems."""
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
