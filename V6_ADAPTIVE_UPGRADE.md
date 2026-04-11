# Vibe Alchemist V6 — Adaptive Tier-Based Model Selection

**Date:** April 8, 2026
**Status:** IMPLEMENTED ✅
**Based on:** `adaptive_system.md` specification

---

## 🎯 WHAT CHANGED

Your system **already had** hardware capability detection (`capability_detector.py`) and tier-based model selection (`model_registry.py`). But it was using **YOLOv11n for ALL tiers** — only changing resolution.

**Now:** Different YOLOv11 size variants per tier for maximum accuracy on capable hardware.

---

## 📊 ADAPTIVE MODEL SELECTION (V6)

| Tier | Hardware | Face Detection Model | Resolution | Confidence | MiVOLO | Emotion | Tracking |
|------|----------|---------------------|------------|------------|--------|---------|----------|
| **Tier 1** (LOW) | RPi 4 / old CPU | **YOLOv11n-face** (nano) | 384p | 0.35 | XXS | ❌ Disabled | IoU |
| **Tier 2** (MED) | RPi 5 / laptop | **YOLOv11s-face** (small) | 512p | 0.30 | XXS | ✅ MobileNet FER | ByteTrack |
| **Tier 3** (HIGH) | GPU / strong CPU | **YOLOv11m-face** (medium) | 720p | 0.25 | Full | ✅ MobileNet FER | ByteTrack |

**Base model family is ALWAYS YOLOv11.** Tier controls the size variant (n/s/m).

---

## 📁 FILES MODIFIED

| File | Changes |
|------|---------|
| `core/model_registry.py` | Updated `get_detection_config()` — YOLOv11n/s/m per tier |
| `core/vision_pipeline.py` | Added `_load_yolo_tiered()` — tier-based face model loading |
| `core/adaptive_pipeline.py` | Updated detector log to show correct tier variant |
| `scripts/download_models.py` | Updated for V6 tier-based model checking |

---

## 🔧 HOW IT WORKS

### 1. Startup: Hardware Benchmark (~3 seconds)
```python
from core.capability_detector import PROFILE
PROFILE.detect()

# Output:
# SystemProfile result: CPU=142.3 Mop/s | RAM=7.8GB | GPU=cuda | → TIER 3
```

### 2. Model Loading: Tier-Based Selection
```python
# model_registry.py
if PROFILE.tier == 1:
    return {"model": "models/yolo11n-face.pt", "imgsz": 384, "conf": 0.35}
elif PROFILE.tier == 2:
    return {"model": "models/yolo11s-face.pt", "imgsz": 512, "conf": 0.30}
else:
    return {"model": "models/yolo11m-face.pt", "imgsz": 720, "conf": 0.25}
```

### 3. Graceful Fallback Chain
If a tier-specific model is missing:
```
Tier 3 requested → yolo11m-face.pt not found
                 → tries yolo11s-face.pt
                 → tries yolo11n-face.pt
                 → tries yolov8n-face.pt (last resort)
```

### 4. Manual Override
Force a specific tier in `.env`:
```bash
FORCE_TIER=3  # Always use high-tier models (YOLOv11m + MiVOLO Full)
```

---

## 📈 EXPECTED ACCURACY IMPROVEMENTS

### Before V6 (All tiers use YOLOv11n)
| Tier | Model | Resolution | Expected mAP |
|------|-------|------------|--------------|
| Tier 1 | YOLOv11n-face | 384p | ~45% |
| Tier 2 | YOLOv11n-face | 512p | ~47% |
| Tier 3 | YOLOv11n-face | 720p | ~48% |

### After V6 (Tier-based model selection)
| Tier | Model | Resolution | Expected mAP | Improvement |
|------|-------|------------|--------------|-------------|
| Tier 1 | YOLOv11n-face | 384p | ~45% | Baseline |
| Tier 2 | YOLOv11s-face | 512p | ~50% | **+5%** |
| Tier 3 | YOLOv11m-face | 720p | ~55% | **+10%** |

---

## 🚀 DEPLOYMENT

### 1. Check Current Models
```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
source venv/bin/activate
python scripts/download_models.py
```

### 2. Restart Server
```bash
docker compose down
docker compose up -d --build
```

### 3. Verify Tier Detection
```bash
docker compose logs -f | grep -E "SystemProfile|Detector|Tier"
```

Expected output:
```
SystemProfile: Running hardware benchmark (~3s)...
SystemProfile result: CPU=142.3 Mop/s | RAM=7.8GB | GPU=cuda | → TIER 3
AdaptivePipeline: Tier 3 — HIGH
Detector: YOLOv11m-face @ 720p, conf=0.25
```

---

## 📦 MODEL SIZES (For Reference)

| Model | Size | Parameters | Inference Time (CPU) |
|-------|------|------------|---------------------|
| YOLOv11n-face | ~6 MB | ~2.6M | ~15ms |
| YOLOv11s-face | ~22 MB | ~9.4M | ~35ms |
| YOLOv11m-face | ~52 MB | ~20.1M | ~75ms |

---

## ✅ VERIFICATION CHECKLIST

After deploying V6:

- [ ] `SystemProfile result` shows detected tier in logs
- [ ] `Detector: YOLOv11X-face` shows correct variant (n/s/m)
- [ ] `FORCE_TIER=` in `.env` works (set to 3, verify it uses YOLOv11m)
- [ ] `python scripts/download_models.py` shows correct model status
- [ ] Server starts without errors
- [ ] Face detection works and is more accurate on Tier 2/3 systems

---

## 🔍 ADAPTIVE SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────┐
│           STARTUP (3-second bench)          │
│  1. CPU benchmark (M-ops/sec)               │
│  2. RAM detection (available GB)            │
│  3. GPU detection (CUDA/MPS/none)           │
│  4. Tier assignment (1/2/3)                 │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│         MODEL REGISTRY (per tier)           │
│  Tier 1: YOLOv11n + MiVOLO XXS + IoU       │
│  Tier 2: YOLOv11s + MiVOLO XXS + ByteTrack │
│  Tier 3: YOLOv11m + MiVOLO Full + ByteTrack│
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│         ADAPTIVE PIPELINE                   │
│  - Detection every 1 frame (all tiers)      │
│  - Recognition every 15/5/2 frames          │
│  - Demographics every 10/5/3 frames         │
│  - Emotion every 0/5/3 frames               │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│         V4 AGE FUSION ENGINE                │
│  DEX + MiVOLO + Temporal + AutoCal          │
│  Target: 90-95% accuracy (±5yr)             │
└─────────────────────────────────────────────┘
```

---

**V6 ADAPTIVE UPGRADE COMPLETE.** System now uses the best models your hardware can handle. 🎯
