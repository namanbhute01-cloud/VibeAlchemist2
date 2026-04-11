#!/usr/bin/env python3
"""
Vibe Alchemist V2 — Model Accuracy Benchmark

Measures real-world accuracy of all vision pipeline components:
1. Person detection (precision, recall, F1)
2. Face detection (precision, recall, F1)
3. Age estimation (MAE, accuracy at ±3yr/±5yr/±10yr)
4. Age group classification accuracy
5. End-to-end pipeline accuracy

Usage:
    # Benchmark with test images (need labeled dataset)
    python scripts/benchmark_accuracy.py --test-dir test_images/

    # Live benchmark (uses current camera feed, manual labeling)
    python scripts/benchmark_accuracy.py --live --camera 0

    # Quick synthetic benchmark (no dataset needed)
    python scripts/benchmark_accuracy.py --quick

Results saved to: benchmark_results.json
"""
import os
import sys
import json
import time
import cv2
import numpy as np
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BenchmarkResult:
    def __init__(self):
        self.person_detections = {"tp": 0, "fp": 0, "fn": 0}
        self.face_detections = {"tp": 0, "fp": 0, "fn": 0}
        self.age_predictions = []  # (predicted, actual) tuples
        self.age_group_predictions = []  # (predicted_group, actual_group) tuples
        self.latencies = {"person_det": [], "face_det": [], "age_est": [], "total": []}
        self.quality_scores = []
        self.start_time = time.time()

    def to_dict(self):
        elapsed = time.time() - self.start_time

        # Person detection metrics
        p = self.person_detections
        p_precision = p["tp"] / max(1, p["tp"] + p["fp"])
        p_recall = p["tp"] / max(1, p["tp"] + p["fn"])
        p_f1 = 2 * p_precision * p_recall / max(0.001, p_precision + p_recall)

        # Face detection metrics
        f = self.face_detections
        f_precision = f["tp"] / max(1, f["tp"] + f["fp"])
        f_recall = f["tp"] / max(1, f["tp"] + f["fn"])
        f_f1 = 2 * f_precision * f_recall / max(0.001, f_precision + f_recall)

        # Age estimation metrics
        ages = self.age_predictions
        if ages:
            errors = [abs(p - a) for p, a in ages]
            mae = np.mean(errors)
            acc_3yr = sum(1 for e in errors if e <= 3) / len(errors)
            acc_5yr = sum(1 for e in errors if e <= 5) / len(errors)
            acc_10yr = sum(1 for e in errors if e <= 10) / len(errors)
        else:
            mae = acc_3yr = acc_5yr = acc_10yr = 0.0

        # Age group metrics
        groups = self.age_group_predictions
        if groups:
            group_correct = sum(1 for p, a in groups if p == a)
            group_accuracy = group_correct / len(groups)
        else:
            group_accuracy = 0.0

        # Latency stats
        avg_latencies = {k: np.mean(v) * 1000 if v else 0 for k, v in self.latencies.items()}

        # Quality stats
        avg_quality = np.mean(self.quality_scores) if self.quality_scores else 0.0

        return {
            "benchmark_duration_sec": round(elapsed, 1),
            "total_frames_processed": len(self.latencies["total"]),
            "person_detection": {
                "precision": round(p_precision, 4),
                "recall": round(p_recall, 4),
                "f1_score": round(p_f1, 4),
                "true_positives": p["tp"],
                "false_positives": p["fp"],
                "false_negatives": p["fn"],
                "accuracy_percent": round(p_f1 * 100, 2),
            },
            "face_detection": {
                "precision": round(f_precision, 4),
                "recall": round(f_recall, 4),
                "f1_score": round(f_f1, 4),
                "true_positives": f["tp"],
                "false_positives": f["fp"],
                "false_negatives": f["fn"],
                "accuracy_percent": round(f_f1 * 100, 2),
            },
            "age_estimation": {
                "mae_years": round(mae, 2),
                "accuracy_±3yr": round(acc_3yr * 100, 2),
                "accuracy_±5yr": round(acc_5yr * 100, 2),
                "accuracy_±10yr": round(acc_10yr * 100, 2),
                "samples": len(ages),
            },
            "age_group_classification": {
                "accuracy_percent": round(group_accuracy * 100, 2),
                "samples": len(groups),
            },
            "latencies_ms": {k: round(v, 2) for k, v in avg_latencies.items()},
            "average_quality_score": round(avg_quality, 3),
            "overall_system_accuracy": round(
                (p_f1 * 0.25 + f_f1 * 0.25 + acc_5yr * 0.3 + group_accuracy * 0.2) * 100, 2
            ),
        }


def _age_to_group(age):
    """Match vision_pipeline._age_to_group exactly."""
    if age < 14:
        return "kids"
    elif age < 22:
        return "youths"
    elif age < 55:
        return "adults"
    else:
        return "seniors"


def benchmark_test_images(pipeline, test_dir, benchmark):
    """
    Benchmark using labeled test images.
    Expects directory structure:
        test_dir/
            person_0_age25_adults.jpg
            person_1_age42_adults.jpg
            ...
        Labels encoded in filename: person_{id}_age{actual_age}_{group}.{ext}
    """
    test_path = Path(test_dir)
    if not test_path.exists():
        print(f"❌ Test directory not found: {test_dir}")
        return

    images = list(test_path.glob("*.jpg")) + list(test_path.glob("*.png"))
    if not images:
        print(f"❌ No images found in {test_dir}")
        return

    print(f"📸 Benchmarking {len(images)} test images...\n")

    for img_path in images:
        # Parse label from filename
        # Format: person_{id}_age{actual_age}_{group}.{ext}
        name = img_path.stem.lower()
        try:
            age_part = [p for p in name.split("_") if p.startswith("age")]
            if not age_part:
                print(f"  ⚠ Skipping {img_path.name} — no age label")
                continue
            actual_age = int(age_part[0].replace("age", ""))
            actual_group = _age_to_group(actual_age)
        except (ValueError, IndexError):
            print(f"  ⚠ Skipping {img_path.name} — bad label format")
            continue

        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"  ⚠ Failed to read {img_path.name}")
            continue

        t0 = time.time()

        # Run pipeline
        t_det = time.time()
        detections = pipeline.process_frame(frame, cam_id=-1)
        benchmark.latencies["total"].append(time.time() - t_det)

        # Evaluate person detection
        person_boxes = [d for d in detections if d.get("bbox")]
        if len(person_boxes) > 0:
            benchmark.person_detections["tp"] += 1
        else:
            benchmark.person_detections["fn"] += 1

        # Evaluate face detection + age estimation
        for det in detections:
            if det.get("is_good_quality", False):
                benchmark.face_detections["tp"] += 1
                pred_age = det.get("age", 25)
                pred_group = det.get("group", "adults")
                quality = det.get("quality", 0.0)

                benchmark.age_predictions.append((pred_age, actual_age))
                benchmark.age_group_predictions.append((pred_group, actual_group))
                benchmark.quality_scores.append(quality)
            else:
                benchmark.face_detections["fp"] += 1

    print(f"✅ Benchmark complete: {len(images)} images processed\n")


def benchmark_live(pipeline, camera_id=0, num_frames=100):
    """
    Live benchmark: captures from camera and asks for manual age input.
    Useful for calibrating on real-world subjects.
    """
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print(f"❌ Cannot open camera {camera_id}")
        return None

    benchmark = BenchmarkResult()
    print(f"📹 Live benchmark — Camera {camera_id}, {num_frames} frames")
    print("Press 'q' to quit, 's' to save current frame with manual age label\n")

    frames_captured = 0
    while frames_captured < num_frames:
        ret, frame = cap.read()
        if not ret:
            print("❌ Failed to read frame")
            break

        t0 = time.time()
        detections = pipeline.process_frame(frame, cam_id=0)
        benchmark.latencies["total"].append(time.time() - t0)

        # Show frame with detections
        display = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            color = (0, 255, 0) if det.get("is_good_quality") else (0, 255, 255)
            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            label = f"Age:{det['age']} {det['group']} ({det.get('quality', 0):.2f})"
            cv2.putText(display, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imshow("Live Benchmark — Press 's' to label, 'q' to quit", display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord("s"):
            # Manual labeling
            try:
                actual_age = int(input(f"Enter actual age for frame {frames_captured}: "))
                actual_group = _age_to_group(actual_age)

                for det in detections:
                    if det.get("is_good_quality"):
                        benchmark.face_detections["tp"] += 1
                        benchmark.age_predictions.append((det["age"], actual_age))
                        benchmark.age_group_predictions.append((det["group"], actual_group))
                        benchmark.quality_scores.append(det.get("quality", 0.0))
                    else:
                        benchmark.face_detections["fp"] += 1

                benchmark.person_detections["tp"] += 1 if detections else 0
                benchmark.person_detections["fn"] += 1 if not detections else 0
                frames_captured += 1
            except ValueError:
                print("Invalid age input, skipping frame")

    cap.release()
    cv2.destroyAllWindows()
    return benchmark


def benchmark_quick(pipeline):
    """
    Quick synthetic benchmark — tests pipeline with generated test patterns.
    No dataset needed — just verifies pipeline runs and measures latency.
    """
    print("⚡ Quick synthetic benchmark...\n")
    benchmark = BenchmarkResult()

    # Generate synthetic test frames with known properties
    test_cases = [
        {"type": "single_person", "age": 25, "group": "adults"},
        {"type": "single_person", "age": 8, "group": "kids"},
        {"type": "single_person", "age": 18, "group": "youths"},
        {"type": "single_person", "age": 60, "group": "seniors"},
        {"type": "single_person", "age": 35, "group": "adults"},
        {"type": "single_person", "age": 45, "group": "adults"},
        {"type": "single_person", "age": 70, "group": "seniors"},
        {"type": "single_person", "age": 12, "group": "kids"},
        {"type": "single_person", "age": 20, "group": "youths"},
        {"type": "single_person", "age": 55, "group": "seniors"},
    ]

    for i, tc in enumerate(test_cases):
        # Create synthetic frame (noise + gradient — no real person)
        # Pipeline won't detect anything, but we measure latency
        frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)

        t0 = time.time()
        detections = pipeline.process_frame(frame, cam_id=0)
        elapsed = time.time() - t0

        benchmark.latencies["total"].append(elapsed)

        # Log what we got
        status = "✅ detected" if detections else "❌ no detection (expected — synthetic)"
        print(f"  Frame {i+1:2d} | Expected: age={tc['age']:3d} ({tc['group']:8s}) | "
              f"Got {len(detections)} detections | {status} | {elapsed*1000:.0f}ms")

    print(f"\n✅ Quick benchmark complete: {len(test_cases)} synthetic frames\n")
    return benchmark


def run_benchmark():
    parser = argparse.ArgumentParser(description="Vibe Alchemist Model Accuracy Benchmark")
    parser.add_argument("--test-dir", type=str, help="Path to labeled test images directory")
    parser.add_argument("--live", action="store_true", help="Live benchmark with camera")
    parser.add_argument("--camera", type=int, default=0, help="Camera ID for live benchmark")
    parser.add_argument("--frames", type=int, default=100, help="Number of frames for live benchmark")
    parser.add_argument("--quick", action="store_true", help="Quick synthetic benchmark")
    parser.add_argument("--output", type=str, default="benchmark_results.json", help="Output file path")
    args = parser.parse_args()

    if not any([args.test_dir, args.live, args.quick]):
        args.quick = True  # Default to quick if nothing specified

    # Initialize pipeline
    print("=" * 70)
    print("  Vibe Alchemist V2 — Model Accuracy Benchmark")
    print("=" * 70)
    print()

    try:
        from core.vision_pipeline import VisionPipeline
        from core.vibe_engine import VibeEngine
        from core.face_vault import FaceVault
        from core.face_registry import FaceRegistry
    except ImportError as e:
        print(f"❌ Failed to import pipeline modules: {e}")
        print("   Make sure you're running from the project root directory.")
        sys.exit(1)

    vibe_engine = VibeEngine()
    face_vault = FaceVault(temp_dir="temp_faces")
    face_registry = FaceRegistry()
    pipeline = VisionPipeline(
        models_dir=os.getenv("MODELS_DIR", "models"),
        pool=None, engine=vibe_engine, vault=face_vault, registry=face_registry
    )

    print(f"✅ Pipeline initialized\n")

    # Run benchmark
    benchmark = BenchmarkResult()

    if args.test_dir:
        benchmark_test_images(pipeline, args.test_dir, benchmark)
    elif args.live:
        benchmark = benchmark_live(pipeline, args.camera, args.frames)
        if benchmark is None:
            sys.exit(1)
    else:
        benchmark_quick(pipeline)

    # Print results
    results = benchmark.to_dict()

    print("=" * 70)
    print("  BENCHMARK RESULTS")
    print("=" * 70)
    print()
    print(f"  Frames processed:    {results['total_frames_processed']}")
    print(f"  Duration:            {results['benchmark_duration_sec']:.1f}s")
    print()
    print(f"  ┌─ Person Detection")
    pd = results["person_detection"]
    print(f"  │  Accuracy:  {pd['accuracy_percent']:.1f}%  (F1: {pd['f1_score']:.3f})")
    print(f"  │  Precision: {pd['precision']:.3f}  Recall: {pd['recall']:.3f}")
    print(f"  │  TP: {pd['true_positives']}  FP: {pd['false_positives']}  FN: {pd['false_negatives']}")
    print(f"  │")
    fd = results["face_detection"]
    print(f"  ├─ Face Detection")
    print(f"  │  Accuracy:  {fd['accuracy_percent']:.1f}%  (F1: {fd['f1_score']:.3f})")
    print(f"  │  Precision: {fd['precision']:.3f}  Recall: {fd['recall']:.3f}")
    print(f"  │  TP: {fd['true_positives']}  FP: {fd['false_positives']}  FN: {fd['false_negatives']}")
    print(f"  │")
    ae = results["age_estimation"]
    print(f"  ├─ Age Estimation")
    print(f"  │  MAE:       {ae['mae_years']:.1f} years")
    print(f"  │  ±3yr:      {ae['accuracy_±3yr']:.1f}%")
    print(f"  │  ±5yr:      {ae['accuracy_±5yr']:.1f}%")
    print(f"  │  ±10yr:     {ae['accuracy_±10yr']:.1f}%")
    print(f"  │  Samples:   {ae['samples']}")
    print(f"  │")
    ag = results["age_group_classification"]
    print(f"  ├─ Age Group Classification")
    print(f"  │  Accuracy:  {ag['accuracy_percent']:.1f}%")
    print(f"  │  Samples:   {ag['samples']}")
    print(f"  │")
    print(f"  ├─ Latencies (avg)")
    for k, v in results["latencies_ms"].items():
        print(f"  │  {k:20s} {v:.1f}ms")
    print(f"  │")
    print(f"  ├─ Avg Quality Score:  {results['average_quality_score']:.3f}")
    print(f"  │")
    print(f"  └─ OVERALL SYSTEM ACCURACY:  {results['overall_system_accuracy']:.1f}%")
    print()

    # Save results
    output_path = Path(args.output)
    results["timestamp"] = datetime.now().isoformat()
    results["target_accuracy"] = "90-95%"

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"📊 Results saved to: {output_path}")
    print("=" * 70)

    # Check if targets met
    print()
    print("🎯 TARGET CHECK (90-95%):")
    targets = {
        "Person Detection": (pd["accuracy_percent"], 90),
        "Face Detection": (fd["accuracy_percent"], 92),
        "Age Est (±5yr)": (ae["accuracy_±5yr"], 90),
        "Age Group": (ag["accuracy_percent"], 92),
        "Overall System": (results["overall_system_accuracy"], 90),
    }
    for name, (actual, target) in targets.items():
        status = "✅" if actual >= target else "❌"
        print(f"  {status} {name:25s} {actual:5.1f}%  (target: {target}%)")

    return results


if __name__ == "__main__":
    run_benchmark()
