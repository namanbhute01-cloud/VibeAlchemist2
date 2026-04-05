#!/usr/bin/env python3
"""
Model Setup Script - Downloads latest YOLO models if not present.
Run this once before starting the server for the first time.

Usage: python setup_models.py
"""

import os
import sys

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Models to check/download
MODELS = {
    # Person detection - YOLO11n (latest)
    "yolo11n.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt",
    # Face detection - YOLOv8n-face (best open-source face model)
    "yolov8n-face.onnx": None,  # Manual download or use existing
}

def check_models():
    """Check which models are present and download missing ones."""
    print("=== Vibe Alchemist - Model Setup ===\n")
    
    all_ok = True
    for model_name, download_url in MODELS.items():
        path = os.path.join(MODELS_DIR, model_name)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  ✓ {model_name} ({size_mb:.1f} MB)")
        else:
            print(f"  ✗ {model_name} - MISSING")
            all_ok = False
    
    # Check ONNX models
    onnx_models = [
        "yolov8n.onnx",
        "arcface_r100.onnx",
        "dex_age.onnx",
    ]
    
    print("\n--- ONNX Models ---")
    for model_name in onnx_models:
        path = os.path.join(MODELS_DIR, model_name)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  ✓ {model_name} ({size_mb:.1f} MB)")
        else:
            print(f"  ✗ {model_name} - MISSING")
            all_ok = False
    
    print()
    if all_ok:
        print("All models present! You can start the server.")
    else:
        print("Some models are missing.")
        print("\nFor YOLO11n (person detection):")
        print("  The server will auto-download yolo11n.pt on first start.")
        print("\nFor face detection:")
        print("  YOLOv8n-face.onnx should be placed in the models/ folder.")
        print("  If not found, the system will fall back to Haar cascades.")
    
    return all_ok


def download_yolo11n():
    """Auto-download YOLO11n using Ultralytics."""
    print("\nDownloading YOLO11n (person detection)...")
    try:
        from ultralytics import YOLO
        model = YOLO("yolo11n.pt")
        print("  ✓ YOLO11n downloaded successfully!")
        return True
    except Exception as e:
        print(f"  ✗ Failed to download YOLO11n: {e}")
        return False


if __name__ == "__main__":
    check_models()
    
    # Check if Ultralytics can download YOLO11n
    yolo11n_path = os.path.join(MODELS_DIR, "yolo11n.pt")
    if not os.path.exists(yolo11n_path):
        print("\n--- Auto-download YOLO11n ---")
        download_yolo11n()
