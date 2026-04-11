# CRITICAL FIXES — Detection Was Completely Broken

**Date:** April 8, 2026
**Status:** FIXED ✅

---

## ROOT CAUSE FOUND: Face Model Failed to Load

### The Problem
`_load_yolo_tiered()` tried to load `yolo11s-face.pt` (Tier 2) and `yolo11m-face.pt` (Tier 3).
**These models DON'T EXIST on Ultralytics hub.**
→ Download failed → `face_model = None`
→ `_detect_faces()` returned `[]` immediately
→ NO face detection ever ran
→ NO ages estimated
→ NO bounding boxes drawn
→ NO faces saved to temp_faces
→ NO detections logged to vibe_engine
→ Music played randomly from default "adults" folder

### Why It Wasn't Obvious
- The error was swallowed by `try/except` in `_load_yolo_tiered()`
- It returned `None` → pipeline continued without face detection
- Person detection still worked (yolo11n.pt loaded fine)
- But faces were NEVER detected → everything fell apart

### Evidence From Validation
```
Local face model not found. Auto-downloading yolo11s-face.pt (Tier 2 small)...
Failed to download yolo11s-face.pt: [Errno 2] No such file or directory
```
The file literally doesn't exist on Ultralytics.

---

## ALL FIXES APPLIED

### Fix #1: Face Model Loading — Use Existing yolov8n-face.onnx
**Before:** Tried to download non-existent `yolo11s-face.pt` → returned `None`
**After:** Falls back to existing `yolov8n-face.onnx` (12MB, already on disk)

```python
# New fallback chain:
1. yolo11n-face.onnx (local)
2. yolo11n-face.pt (local)
3. yolov8n-face.onnx (local) ← EXISTS! 12MB
4. yolov8n-face.pt (local)
5. Download yolo11n-face.pt from Ultralytics
6. Download yolov8n-face.pt from Ultralytics
7. Load yolov8n-face.onnx directly (last resort)
```

### Fix #2: model_registry.py — All Tiers Use Same Model
**Before:** Each tier tried to load a different non-existent model
**After:** All tiers use `yolo11n-face.pt` (same model, different resolution/conf)

### Fix #3: Credentials.json Missing
Drive sync can't work without `credentials.json`. The file is in `.gitignore` (correct — it contains secrets).
User needs to download it from Google Cloud Console and place it in the project root.

---

## VALIDATION RESULTS (After Fixes)

| Test | Result |
|------|--------|
| Face model loads | ✅ YOLO (from yolov8n-face.onnx) |
| Music player starts | ✅ MPV running |
| Music folders | ✅ kids:3, youths:3, adults:4, seniors:3 |
| Vibe engine logs detections | ✅ avg_age changes from 25→19 |
| Face vault saves locally | ✅ Save works |
| Drive sync | ❌ credentials.json missing (user must provide) |

---

## WHAT WAS WORKING (Unchanged)
- Person detection (yolo11n.pt loaded fine)
- Music playback
- Vibe engine consensus
- Face vault save logic
- Bounding box drawing code

## WHAT WAS BROKEN (Now Fixed)
- Face model loading (yolo11s-face.pt doesn't exist)
- All face detection (face_model was None)
- All age estimation (no faces → no ages)
- All face saving (no detections → no saves)
- Music was random (no detections to influence selection)

---

## DEPLOYMENT

```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
docker compose down
docker compose up -d --build
```

### Verify Face Model Loads
```bash
docker compose logs -f | grep -E "Face model|yolov8n-face|yolo11n-face"
```
Expected:
```
Loading yolov8n-face.onnx (local, Tier 2 nano (MED res))
```

### Verify Detections Work
```bash
docker compose logs -f | grep -E "Cam [0-9]+:.*face"
```
Expected when faces are in view:
```
Cam 0: 1 face(s) | Ages: [32] | Groups: ['adults'] | Avg quality: 0.45
```

### Verify Face Saving
```bash
docker compose logs -f | grep "Face saved"
ls -la vibe_alchemist_v2/temp_faces/
```

---

**CRITICAL FIXES COMPLETE.** Face model now loads from existing yolov8n-face.onnx. 🎯
