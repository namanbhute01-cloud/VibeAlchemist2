# Vibe Alchemist V2 - Production Deployment Guide

## Quick Start

### For Development (with Vite hot reload)
```bash
./start.sh
```
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000/api

### For Production (recommended)
```bash
./deploy.sh
```
- Application: http://localhost:8000
- Single unified server (FastAPI serves both API and frontend)

## Architecture

### Production Mode
- **Backend**: FastAPI on port 8000
  - Serves API endpoints at `/api/*`
  - Serves static frontend files at `/`
  - WebSocket at `/ws`
  - Camera feeds at `/feed/{cam_id}`

### Development Mode
- **Backend**: FastAPI on port 8000
- **Frontend**: Vite dev server on port 5173
  - Hot module replacement (HMR)
  - Proxy to backend API

## Configuration

Edit `.env` file:

```bash
# API Server
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=false

# Camera Sources (comma-separated)
CAMERA_SOURCES=0,http://ip-camera-1:port/video,http://ip-camera-2:port/video

# Detection Settings
FACE_DETECTION_CONF=0.5
PERSON_DETECTION_CONF=0.4
FACE_SIMILARITY_THRESHOLD=0.65

# Music Directory
ROOT_MUSIC_DIR=./OfflinePlayback
```

## Directory Structure

```
vibe_alchemist_v2/
├── api/                    # FastAPI backend
│   ├── routes/            # API endpoints
│   └── api_server.py      # Main server
├── core/                   # Core modules
│   ├── camera_pool.py     # Camera management
│   ├── vision_pipeline.py # AI vision processing
│   ├── vibe_engine.py     # Music ambiance logic
│   └── alchemist_player.py# Music player
├── frontend/               # React frontend (development)
├── static/                 # Built frontend (production)
├── models/                 # AI models (YOLO, ArcFace, etc.)
├── OfflinePlayback/        # Music library organized by age groups
├── temp_faces/            # Temporary face storage
├── .env                   # Configuration
├── deploy.sh              # Production deployment script
└── start.sh               # Development startup script
```

## Music Library Setup

Organize music in `OfflinePlayback/` folder:

```
OfflinePlayback/
├── kids/      # Music for children (age < 13)
├── youths/    # Music for teens (age 13-19)
├── adults/    # Music for adults (age 20-49)
└── seniors/   # Music for seniors (age 50+)
```

Supported formats: MP3, WAV, FLAC, M4A, OGG

## API Endpoints

### Cameras
- `GET /api/cameras` - List all cameras
- `GET /api/cameras/config` - Get camera configuration
- `POST /api/cameras/config` - Save camera configuration

### Playback
- `GET /api/playback/status` - Current playback status
- `GET /api/playback/library` - Music library
- `POST /api/playback/add-song` - Add song to library
- `POST /api/playback/{action}` - Control playback (play, pause, next, etc.)

### Vibe
- `GET /api/vibe/current` - Current vibe state
- `GET /api/vibe/journal` - Vibe history/analytics

### Faces
- `GET /api/faces` - Face detection statistics
- `GET /api/faces/drive/status` - Google Drive sync status

### Settings
- `GET /api/settings` - All settings
- `POST /api/settings` - Save settings
- `GET /api/settings/{key}` - Get specific setting
- `POST /api/settings/{key}` - Update specific setting

## Features

### Automatic Image Enhancement
- **Brightness**: Auto-adjusts based on scene lighting
- **Contrast**: CLAHE adaptive histogram equalization
- **Sharpness**: Edge-detection based sharpening

### Face Detection Pipeline
1. Motion detection (MOG2 background subtraction)
2. Person detection (YOLOv8-nano)
3. Face detection (YOLOv8-face + Haar cascade fallback)
4. Face recognition (ArcFace embeddings)
5. Age estimation (DEX age prediction)

### Music Ambiance Engine
- Real-time age group detection
- Automatic playlist switching
- 80% consensus threshold for vibe changes
- Cross-camera face deduplication

## Troubleshooting

### Frontend shows black screen
1. Check browser console for errors (F12)
2. Verify backend is running: `curl http://localhost:8000/api/cameras`
3. Clear browser cache and reload
4. Try production mode: `./deploy.sh`

### Camera feeds not loading
1. Check camera URLs in `.env`
2. Verify network connectivity to IP cameras
3. Check backend logs: `tail -f logs/backend.log`
4. Test camera URL directly: `vlc <camera-url>`

### Face detection not working
1. Verify models exist in `models/` folder
2. Check backend logs for model loading errors
3. Ensure proper lighting conditions
4. Adjust `FACE_DETECTION_CONF` in `.env`

### Music not playing
1. Check music files exist in `OfflinePlayback/{group}/`
2. Verify file formats are supported
3. Check backend logs for player errors
4. Test with different browser

## Performance Tuning

### For low-end hardware
- Reduce `TARGET_HEIGHT=480` in `.env`
- Increase `FRAME_RATE_LIMIT=10`
- Set `FACE_DETECTION_CONF=0.6` (higher = fewer detections)

### For better accuracy
- Increase `TARGET_HEIGHT=1080`
- Lower `FACE_DETECTION_CONF=0.4`
- Ensure good lighting conditions

## System Requirements

### Minimum
- CPU: 4 cores
- RAM: 8 GB
- Storage: 10 GB (for models and music)

### Recommended
- CPU: 8 cores
- RAM: 16 GB
- Storage: 50 GB SSD
- GPU: Optional (CUDA for faster inference)

## Security Notes

- Change default ports in production
- Use HTTPS for external access
- Configure firewall rules
- Secure camera network access
- Regular model and dependency updates

## Support

For issues and feature requests, check the logs:
- Backend: `logs/backend.log`
- Frontend (dev): `logs/frontend.log`

Contact: Vibe Alchemist Team
