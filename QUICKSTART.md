# Vibe Alchemist V2 - Quick Start Guide

## 🚀 Running the System

### Single Command Start
```bash
cd /path/to/vibe_alchemist_v2
./start.sh
```

### Access the Application
- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8080
- **Network Access:** http://YOUR_IP:5173

### Stop the System
Press `Ctrl+C` in the terminal

---

## 📁 Project Structure

```
vibe_alchemist_v2/
├── main.py                 # Backend entry point
├── start.sh                # Unified startup script
├── .env                    # Configuration
├── api/                    # FastAPI routes
│   ├── api_server.py
│   └── routes/
│       ├── cameras.py
│       ├── playback.py
│       ├── vibe.py
│       └── faces.py
├── core/                   # Business logic
│   ├── camera_pool.py
│   ├── vision_pipeline.py
│   ├── vibe_engine.py
│   ├── alchemist_player.py
│   ├── face_vault.py
│   └── face_registry.py
├── OfflinePlayback/        # Music library
│   ├── kids/
│   ├── youths/
│   ├── adults/
│   └── seniors/
├── frontend/               # React app
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── hooks/
│   └── package.json
└── models/                 # AI models
    ├── yolov8n.onnx
    ├── yolov8n-face.onnx
    ├── arcface_r100.onnx
    └── dex_age.onnx
```

---

## 🎯 Features Overview

### Dashboard (Home)
- Real-time vibe status
- Active camera count
- Music playback status
- Live camera grid
- Age distribution gauge

### Camera Feeds
- Live MJPEG streaming
- Brightness/Contrast/Sharpness controls
- Multi-camera support

### Audience
- Unique face count
- Age group distribution
- Vibe journal visualization
- Live detection events

### Playlist
- Browse music by age group
- Search tracks
- Now Playing display
- Playback controls

### Analytics
- Weekly traffic patterns
- Demographic distribution
- Peak hours analysis
- KPI dashboard

### Settings
- Environment variable editor
- Toggle preferences
- System status monitor

---

## 🔧 Configuration (.env)

### Camera Settings
```bash
CAMERA_SOURCES=0            # Webcam ID or comma-separated RTSP URLs
TARGET_HEIGHT=720           # Resolution height
FRAME_RATE_LIMIT=15         # Max FPS
```

### Vision Settings
```bash
FACE_DETECTION_CONF=0.5     # Face detection threshold
PERSON_DETECTION_CONF=0.4   # Person detection threshold
FACE_SIMILARITY_THRESHOLD=0.65  # Face matching threshold
```

### Music Settings
```bash
ROOT_MUSIC_DIR=./OfflinePlayback
DEFAULT_VOLUME=70
SHUFFLE_MODE=true
```

### System Settings
```bash
API_HOST=0.0.0.0
API_PORT=8080
DEBUG=true
```

---

## 🎵 Adding Music

1. Place music files in appropriate age group folders:
```bash
OfflinePlayback/kids/       # Music for children
OfflinePlayback/youths/     # Music for teens/young adults
OfflinePlayback/adults/     # Music for 26-50 age group
OfflinePlayback/seniors/    # Music for 50+ age group
```

2. Supported formats: `.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`

3. Refresh playlist in UI or restart the app

---

## 📡 API Endpoints

### Quick Test Commands
```bash
# Get camera list
curl http://localhost:8080/api/cameras/

# Get playback status
curl http://localhost:8080/api/playback/status

# Get music library
curl http://localhost:8080/api/playback/library

# Get current vibe
curl http://localhost:8080/api/vibe/current

# Get face statistics
curl http://localhost:8080/api/faces

# Get vibe journal
curl http://localhost:8080/api/vibe/journal
```

### WebSocket Stream
Connect to `ws://localhost:8080/ws` for real-time vibe updates (2Hz)

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Kill processes on ports 8080 and 5173
lsof -ti:8080 | xargs kill -9
lsof -ti:5173 | xargs kill -9
```

### Camera Not Detected
- Check `CAMERA_SOURCES` in `.env`
- For webcam: use `0` or `/dev/video0`
- For IP camera: use RTSP URL like `rtsp://192.168.1.100:554/stream`

### Music Not Playing
- Ensure `mpv` is installed: `sudo apt install mpv`
- Check music files exist in `OfflinePlayback/` folders
- Verify volume is not muted in UI

### Frontend Not Loading
- Clear browser cache
- Check if Vite dev server is running on port 5173
- Rebuild: `cd frontend && npm run build`

### High CPU Usage
- Reduce `TARGET_HEIGHT` to 480
- Lower `FRAME_RATE_LIMIT` to 10
- Reduce camera count

---

## 📊 System Status Indicators

| Indicator | Meaning |
|-----------|---------|
| 🟢 "Vibing" | System actively detecting and playing music |
| 🟡 "Transitioning" | Changing vibe/music |
| 🔴 "Offline" | Backend not connected |
| 🟢 Camera "Online" | Camera feed active |
| 🔴 Camera "Offline" | Camera disconnected |

---

## 🎨 UI Keyboard Shortcuts

- `B` - Toggle sidebar
- `Space` - Play/Pause music (when focused on player)

---

## 📝 Logs Location

Backend logs appear in the terminal running `start.sh`. For detailed debugging:

```bash
# Run with debug logging
DEBUG=true ./start.sh
```

---

## 🆘 Need Help?

1. Check `INTEGRATION_REPORT.md` for detailed architecture
2. Review backend logs in the terminal
3. Open browser DevTools Console for frontend errors
4. Verify all API endpoints respond: `curl http://localhost:8080/docs`

---

**Made with ❤️ by Vibe Alchemist Team**
