#!/usr/bin/env python3
"""
Download and setup all VibeAlchemist2 V5 upgrade models.

Usage:
    python scripts/download_models.py

Models used:
    - yolov8n-face.onnx/pt    — Face detection (already present: 12MB)
    - arcface_r100.onnx        — Face recognition (already present: 131MB)
    - dex_age.onnx             — Age estimation (already present: 1.3MB)
    - yolov8n.onnx/pt          — Person detection (already present: 13MB)

V5 Upgrade Models (download or export manually):
    - retinaface_mobilenet_int8.onnx — Profile-view robust face detector
    - mivolo_xxs.onnx                — Age+gender from face+body (MAE~5.1)
    - mobilenet_fer_int8.onnx        — Emotion recognition (7 classes)

NOTE: The official release URLs for V5 models don't exist yet on GitHub.
The server will start and run with the existing V3 models (YOLOv8n-face,
DEX-Age, ArcFace). V5 models activate automatically when placed in models/.
"""
import os
import sys

# Resolve paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(project_root, "models"))
os.makedirs(MODELS_DIR, exist_ok=True)

# V3 models — already present and working
EXISTING_MODELS = [
    "arcface_r100.onnx",
    "dex_age.onnx",
    "yolov8n-face.onnx",
    "yolov8n.onnx",
    "yolov8n.pt",
]

# V5 models — need manual download/export
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
    """Check which V3 models are already present."""
    print("=== Checking existing V3 models ===")
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


def print_v5_instructions(missing):
    """Print instructions for downloading missing V5 models."""
    if not missing:
        print("\n✅ All V5 models are present!")
        return

    print(f"\n⚠ {len(missing)} V5 model(s) missing:")
    for model in missing:
        info = V5_MODELS[model]
        print(f"\n  ┌─ {model}")
        print(f"  │  {info['note']}")
        print(info["instructions"].replace("{models_dir}", MODELS_DIR))
        print(f"  └─")


def main():
    print("=" * 60)
    print("  VibeAlchemist2 V5 Model Setup")
    print("=" * 60)
    print(f"\nModels directory: {MODELS_DIR}\n")

    # Check V3 models
    v3_ok = check_existing()

    # Check V5 models
    present, missing = check_v5()

    # Print instructions for missing models
    print_v5_instructions(missing)

    # Summary
    print("\n" + "=" * 60)
    if v3_ok:
        print("  ✅ V3 models are all present — server is fully functional")
    else:
        print("  ⚠ Some V3 models are missing — server may have limited features")

    if not missing:
        print("  ✅ All V5 upgrade models are ready — run: python main.py")
    else:
        print(f"  ℹ {len(missing)} V5 model(s) need manual download (see above)")
        print("  ℹ Server will still start with existing V3 models")
        print("  ℹ V5 features activate automatically when models are added")

    print("=" * 60)

    return 0 if v3_ok and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
