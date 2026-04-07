#!/usr/bin/env python3
"""
Download all VibeAlchemist2 V5 upgrade models into models/ directory.
Run once before starting the server.

Usage:
    python scripts/download_models.py

Models downloaded:
    - retinaface_mobilenet_int8.onnx — Robust face detector (profile views)
    - YOLOv8n-face.pt                — Fallback face detector
    - mivolo_xxs.onnx                — Age + gender from face+body crops
    - mobilenet_fer_int8.onnx        — Facial emotion recognition (7 classes)

The server will still START even if some models are missing (graceful degradation).
"""
import os
import sys
import urllib.request
import urllib.error

# Allow override via environment variable
MODELS_DIR = os.getenv("MODELS_DIR", "models")

# Resolve relative to project root (parent of scripts/)
if not os.path.isabs(MODELS_DIR):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    MODELS_DIR = os.path.join(project_root, MODELS_DIR)

os.makedirs(MODELS_DIR, exist_ok=True)

MODELS = [
    {
        "name": "RetinaFace MobileNet INT8",
        "filename": "retinaface_mobilenet_int8.onnx",
        "urls": [
            "https://github.com/biubug6/Pytorch_Retinaface/releases/download/v0.1/RetinaFace_mobilenet.onnx",
        ],
        "note": "Robust face detector — profile views, occlusion, low-light",
        "required": False,  # falls back to YOLOv8n-face
    },
    {
        "name": "YOLOv8n-face",
        "filename": "yolov8n-face.pt",
        "urls": [
            "https://github.com/derronqi/yolov8-face/releases/download/v1.0/yolov8n-face.pt",
        ],
        "note": "Fallback face detector for 240p tiered inference",
        "required": False,  # already have yolov8n-face.onnx
    },
    {
        "name": "MiVOLO XX-Small",
        "filename": "mivolo_xxs.onnx",
        "urls": [
            "https://github.com/WildChlamydia/MiVOLO/releases/download/v1.0/mivolo_xxs.onnx",
        ],
        "note": "Age + gender from face+body crops (MAE~5.1 years)",
        "required": False,  # demographics disabled if missing
    },
    {
        "name": "MobileNet FER INT8",
        "filename": "mobilenet_fer_int8.onnx",
        "urls": [
            "https://github.com/WildChlamydia/MiVOLO/releases/download/fer/mobilenet_fer_int8.onnx",
        ],
        "note": "Facial emotion recognition — 7 classes",
        "required": False,  # emotion disabled if missing
    },
]


def download_one(url: str, dest: str, max_retries: int = 2) -> bool:
    """Try downloading from a single URL with retries."""
    for attempt in range(1, max_retries + 1):
        try:
            print(f"    Attempt {attempt}/{max_retries}…")
            urllib.request.urlretrieve(
                url, dest,
                reporthook=lambda b, bs, t: print(
                    f"\r    {min(100, int(b * bs * 100 / max(t, 1)))}%",
                    end="", flush=True,
                ),
            )
            print()  # newline after progress
            return True
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            print(f"\r    Attempt {attempt} failed: {e}")
            if os.path.exists(dest):
                os.remove(dest)
    return False


def download(model: dict) -> bool:
    """Download a single model, trying multiple URLs. Returns True on success."""
    path = os.path.join(MODELS_DIR, model["filename"])
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  [SKIP] {model['filename']} already exists ({size_mb:.1f} MB)")
        return True

    print(f"  [DOWN] {model['name']} → {path}")
    print(f"         {model['note']}")

    for url in model["urls"]:
        if download_one(url, path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK]   {model['filename']} ({size_mb:.1f} MB)")
            return True

    print(f"  [FAIL] Could not download {model['filename']} from any source.")
    print(f"         Please manually download from one of these URLs:")
    for url in model["urls"]:
        print(f"           {url}")
    print(f"         Then place the file at: {path}")
    if model["required"]:
        print(f"  [WARN] This model is REQUIRED for the server to function.")
    else:
        print(f"  [INFO] The server will still start — this feature will be disabled.")
    return False


if __name__ == "__main__":
    print("=== VibeAlchemist2 V4 Model Downloader ===")
    print(f"Models directory: {MODELS_DIR}")
    print()

    success_count = 0
    fail_count = 0
    skip_count = 0

    for m in MODELS:
        try:
            result = download(m)
            if result:
                if os.path.exists(os.path.join(MODELS_DIR, m["filename"])):
                    success_count += 1
                else:
                    skip_count += 1
            else:
                fail_count += 1
        except KeyboardInterrupt:
            print("\n\n[ABORT] Download interrupted by user.")
            sys.exit(1)

    print()
    print("=" * 45)
    print(f"  Downloaded: {success_count}")
    print(f"  Skipped:    {skip_count}")
    print(f"  Failed:     {fail_count}")
    print("=" * 45)

    if fail_count > 0:
        print()
        print("Some models failed to download.")
        print("You can still start the server — missing models will disable features gracefully.")
        print("Run: python main.py")
    else:
        print()
        print("All models are ready. Run: python main.py")
