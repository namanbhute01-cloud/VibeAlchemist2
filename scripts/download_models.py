#!/usr/bin/env python3
"""
Download and setup all VibeAlchemist2 V5/V6 upgrade models.

Usage:
    python scripts/download_models.py

V6 Adaptive Model Selection (Tier-based):
- Tier 1 (LOW):    YOLOv11n-face (nano, 384p)
- Tier 2 (MEDIUM): YOLOv11s-face (small, 512p)
- Tier 3 (HIGH):   YOLOv11m-face (medium, 720p)

All tiers use YOLOv11 family. Size variant is selected by hardware tier.
"""
import os
import sys

# Resolve paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(project_root, "models"))
os.makedirs(MODELS_DIR, exist_ok=True)

# Core models — already present and working
EXISTING_MODELS = [
    "arcface_r100.onnx",
    "dex_age.onnx",
]

# YOLOv11 face models — tier-based selection
YOLO11_FACE_MODELS = {
    "yolo11n-face.pt": "Tier 1 (nano, 384p) — fastest detection",
    "yolo11s-face.pt": "Tier 2 (small, 512p) — balanced speed/accuracy",
    "yolo11m-face.pt": "Tier 3 (medium, 720p) — maximum accuracy",
}

# V5/V6 upgrade models — need manual download/export
V5_MODELS = {
    "retinaface_mobilenet_int8.onnx": {
        "note": "RetinaFace — profile view robust face detection",
        "instructions": """
  Option 1: Export from PyTorch RetinaFace
    pip install retina-face
    # Model downloads automatically on first use

  Option 2: Download ONNX from Ultralytics
    pip install ultralytics
    python -c "from ultralytics import YOLO; YOLO('yolov8n-face.pt').export(format='onnx')"

  Option 3: Export from biubug6/Pytorch_Retinaface
    git clone https://github.com/biubug6/Pytorch_Retinaface.git
    cd Pytorch_Retinaface
    # Convert mobilenet0.25 to ONNX using their export script
    # Place output at: {models_dir}/retinaface_mobilenet_int8.onnx
""",
    },
    "mivolo_xxs.onnx": {
        "note": "MiVOLO XX-Small — age+gender from face+body (MAE~5.1 years)",
        "instructions": """
  Export from MiVOLO PyTorch checkpoint:
    git clone https://github.com/wildchlamydia/mivolo.git
    cd mivolo
    pip install -e .
    python -c "
    from mivolo import MiVOLO
    model = MiVOLO.from_pretrained('mivolo_d1_224')
    model.export('mivolo_xxs.onnx', opset=18)
    "
    # Place output at: {models_dir}/mivolo_xxs.onnx

  NOTE: ONNX export requires opset 18 and may need torch/onnx/utils.py patch.
  See: https://github.com/WildChlamydia/MiVOLO/issues/8
""",
    },
    "mobilenet_fer_int8.onnx": {
        "note": "MobileNet FER INT8 — emotion recognition (7 classes)",
        "instructions": """
  Export from HuggingFace FER model:
    from transformers import AutoModelForImageClassification
    model = AutoModelForImageClassification.from_pretrained(
        "trpakov/vit-face-expression"
    )
    # Export to ONNX with opset 18
    # Place at: {models_dir}/mobilenet_fer_int8.onnx

  Or use any pre-trained FER ONNX model (AffectNet/FER2013 trained).
""",
    },
}


def check_existing():
    """Check which core models are already present."""
    print("=== Checking core models ===")
    all_present = True
    for model in EXISTING_MODELS:
        path = os.path.join(MODELS_DIR, model)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {model} ({size_mb:.1f} MB)")
        else:
            print(f"  [MISSING] {model}")
            all_present = False
    return all_present


def check_yolo11_face():
    """Check which YOLOv11 face models are present (tier-based)."""
    print("\n=== Checking YOLOv11 face models (tier-based) ===")
    present = []
    missing = []
    for model, desc in YOLO11_FACE_MODELS.items():
        path = os.path.join(MODELS_DIR, model)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {model} ({size_mb:.1f} MB) — {desc}")
            present.append(model)
        else:
            print(f"  [MISSING] {model} — {desc}")
            missing.append(model)
    return present, missing


def check_v5():
    """Check which V5 models are present."""
    print("\n=== Checking V5 upgrade models ===")
    present = []
    missing = []
    for model, info in V5_MODELS.items():
        path = os.path.join(MODELS_DIR, model)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {model} ({size_mb:.1f} MB) — {info['note']}")
            present.append(model)
        else:
            print(f"  [MISSING] {model} — {info['note']}")
            missing.append(model)
    return present, missing


def print_download_instructions(yolo_missing, v5_missing):
    """Print instructions for downloading missing models."""
    if yolo_missing:
        print(f"\n⚠ {len(yolo_missing)} YOLOv11 face model(s) missing:")
        for model in yolo_missing:
            desc = YOLO11_FACE_MODELS.get(model, "")
            print(f"\n  ┌─ {model}")
            print(f"  │  {desc}")
            print(f"  │  Auto-downloads on first run, or download manually:")
            print(f"  │  pip install ultralytics")
            print(f"  │  python -c \"from ultralytics import YOLO; YOLO('{model.replace('.pt', '.pt')}')\"")
            print(f"  └─")

    if v5_missing:
        print(f"\n⚠ {len(v5_missing)} V5 model(s) missing:")
        for model in v5_missing:
            info = V5_MODELS[model]
            print(f"\n  ┌─ {model}")
            print(f"  │  {info['note']}")
            print(info["instructions"].replace("{models_dir}", MODELS_DIR))
            print(f"  └─")

    if not yolo_missing and not v5_missing:
        print("\n✅ All models are present!")


def main():
    print("=" * 60)
    print("  VibeAlchemist2 V6 Model Setup")
    print("=" * 60)
    print(f"\nModels directory: {MODELS_DIR}\n")

    # Check core models
    core_ok = check_existing()

    # Check YOLOv11 face models
    yolo_present, yolo_missing = check_yolo11_face()

    # Check V5 models
    v5_present, v5_missing = check_v5()

    # Print instructions for missing models
    print_download_instructions(yolo_missing, v5_missing)

    # Summary
    print("\n" + "=" * 60)
    if core_ok:
        print("  ✅ Core models are present — server will start")
    else:
        print("  ⚠ Some core models are missing — server may have limited features")

    if not yolo_missing:
        print("  ✅ All YOLOv11 face models ready — adaptive tier selection active")
    else:
        print(f"  ℹ {len(yolo_missing)} YOLOv11 face model(s) will auto-download on first run")

    if not v5_missing:
        print("  ✅ All V5 upgrade models ready — full feature set active")
    else:
        print(f"  ℹ {len(v5_missing)} V5 model(s) need manual download (see above)")
        print("  ℹ V5 features activate automatically when models are added")

    print("=" * 60)

    return 0 if core_ok and not yolo_missing and not v5_missing else 1


if __name__ == "__main__":
    sys.exit(main())
