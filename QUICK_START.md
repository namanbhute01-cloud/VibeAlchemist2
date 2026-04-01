# Vibe Alchemist V2 - Quick Start Guide

## 🚀 Starting the Application

### Option 1: Unified Script (Recommended)

Start both backend and frontend with one command:

```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
./start.sh
```

**Access Points:**
- Frontend: http://localhost:5173
- Network Access: http://YOUR_IP:5173 (e.g., http://10.253.109.95:5173)
- Backend API: http://localhost:8081/api

**Stop all services:**
```bash
./stop.sh
```

Or press `Ctrl+C` in the terminal running `start.sh`

---

### Option 2: Manual Start (for debugging)

**Terminal 1 - Backend:**
```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
source venv/bin/activate
python main.py
```

**Terminal 2 - Frontend:**
```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2/frontend"
npm run dev
```

---

## 🔧 Troubleshooting

### Port Already in Use
```bash
./stop.sh
# Or manually:
lsof -ti:8080 | xargs kill -9
lsof -ti:5173 | xargs kill -9
```

### Backend Won't Start
Check logs:
```bash
tail -50 logs/backend.log
```

Common issues:
- Models not found: Ensure `models/` directory contains YOLO and ArcFace models
- Port conflict: Run `./stop.sh` first
- Missing dependencies: `source venv/bin/activate && pip install -r requirements.txt`

### Frontend Won't Start
Check logs:
```bash
tail -50 logs/frontend.log
```

Common issues:
- Node modules missing: `cd frontend && npm install`
- Port conflict: Run `./stop.sh` first

### Camera Not Working
1. Check `.env` file:
   ```bash
   CAMERA_SOURCES=0  # USB camera
   # or
   CAMERA_SOURCES=rtsp://your_ip:port/stream  # RTSP camera
   ```

2. For IP cameras, ensure they're accessible:
   ```bash
   ping your_camera_ip
   ```

### Music Not Playing
1. Ensure MPV is installed:
   ```bash
   which mpv
   # Should return: /usr/bin/mpv
   ```

2. Check music files exist:
   ```bash
   ls -la OfflinePlayback/*/
   ```

3. Test playback via API:
   ```bash
   curl -X POST -H "Content-Type: application/json" \
        -d '{"group":"adults"}' \
        http://localhost:8081/api/playback/next
   ```

---

## 📡 API Endpoints

### Cameras
```bash
GET  /api/cameras              # List all cameras
POST /api/cameras/{id}/settings # Update camera settings
GET  /feed/{cam_id}            # MJPEG camera stream
```

### Playback
```bash
GET  /api/playback/status      # Current playback status
GET  /api/playback/library     # Music library by age groups
POST /api/playback/pause       # Toggle pause
POST /api/playback/next        # Next track
POST /api/playback/prev        # Previous track
POST /api/playback/shuffle     # Toggle shuffle
POST /api/playback/volume      # Set volume
```

### Faces
```bash
GET /api/faces              # Face detection statistics
GET /api/faces/drive/status # Google Drive sync status
```

### Vibe
```bash
GET /api/vibe/current       # Current vibe state
GET /api/vibe/journal       # Vibe history/analytics
```

### WebSocket
```
WS /ws  # Real-time vibe state updates (2Hz)
```

---

## 🧪 Testing

### Quick Health Check
```bash
# Backend
curl http://localhost:8081/api/cameras
curl http://localhost:8081/api/playback/status

# Frontend
curl http://localhost:5173 | grep "alchemist"
```

### Test Music Playback
```bash
# Play next song
curl -X POST -H "Content-Type: application/json" \
     -d '{"group":"adults"}' \
     http://localhost:8081/api/playback/next

# Check status
curl http://localhost:8081/api/playback/status
```

---

## 📊 System Requirements

- **Python:** 3.10+
- **Node.js:** 18+
- **RAM:** 4GB minimum (8GB recommended)
- **Storage:** 2GB for models + music library
- **OS:** Linux (tested on Ubuntu 22.04+)

### Dependencies

**Python (venv):**
- FastAPI
- Uvicorn
- OpenCV
- Ultralytics (YOLO)
- ONNX Runtime
- InsightFace (ArcFace)
- python-mpv

**Node (frontend):**
- React 18
- Vite
- TypeScript
- Tailwind CSS
- Radix UI

---

## 🎯 Usage Flow

1. **Start the application:** `./start.sh`
2. **Open browser:** http://localhost:5173
3. **Dashboard shows:**
   - Live camera feeds
   - Real-time face detection
   - Current vibe/mood
   - Music playback controls
4. **System automatically:**
   - Detects faces in camera feed
   - Estimates age and demographics
   - Selects music based on audience vibe
   - Transitions smoothly between tracks

---

## 📝 Configuration

Edit `.env` file:

```bash
# Camera
CAMERA_SOURCES=0                    # USB camera ID
# or
CAMERA_SOURCES=rtsp://ip:port/stream

# Detection
FACE_DETECTION_CONF=0.5             # Confidence threshold
PERSON_DETECTION_CONF=0.4

# Music
ROOT_MUSIC_DIR=./OfflinePlayback    # Music library path
DEFAULT_VOLUME=70                   # 0-100
SHUFFLE_MODE=true

# Performance
TARGET_HEIGHT=720                   # Camera resolution
FRAME_RATE_LIMIT=15                 # Max FPS
```

---

## 🐛 Known Issues

1. **RTSP Camera Lag:** IP cameras may have 2-5 second latency
2. **First Run Slow:** Models download/cache on first run
3. **Face Detection CPU:** Can use 50-100% CPU on low-end systems

---

## 📞 Support

For issues, check:
1. Logs: `logs/backend.log` and `logs/frontend.log`
2. Process status: `ps aux | grep -E "main.py|vite"`
3. Port status: `ss -tlnp | grep -E "8080|5173"`

---

**Enjoy the Vibe! 🎵✨**
