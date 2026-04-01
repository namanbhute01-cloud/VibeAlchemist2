# Port Configuration - Vibe Alchemist V2

## ✅ Port Updated to Avoid HRMS Conflict

### Current Configuration

| Service | Port | Status |
|---------|------|--------|
| **HRMS Server** | 5000 | Existing |
| **Vibe Alchemist Backend** | 8081 | ✅ Updated |
| **Vibe Alchemist Frontend** | 5173 | No change |

### Why Port 8081?

- **Port 5000**: Used by HRMS server (existing)
- **Port 8080**: Common alternative, but we chose 8081 to be extra safe
- **Port 8081**: Our final choice - no conflicts!

---

## 📝 Files Updated

### Backend Configuration
```
.env                    API_PORT=8081
.env.example           API_PORT=8081
api/api_server.py      CORS allows: localhost:8081
start.sh               Backend runs on port 8081
docker-compose.yml     Default port: 8081
```

### Frontend Configuration
```
frontend/src/lib/api.ts  Uses relative URLs (/api/*)
start.sh                 Frontend on port 5173
```

### Documentation Updated
```
✓ QUICK_START.md
✓ QUICKSTART.md
✓ AUTOMATIC_SYSTEM_GUIDE.md
✓ INTEGRATION_REPORT.md
✓ INSPECTION_REPORT.md
✓ run.sh
✓ DEPLOYMENT_GUIDE.md
✓ QUICK_DEPLOY.md
```

---

## 🚀 How to Run

### Local Development
```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
./start.sh
```

**Access URLs:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8081/api
- Camera Feed: http://localhost:8081/feed/0
- WebSocket: ws://localhost:8081/ws

### Parallel with HRMS

Both servers can now run simultaneously:

```
HRMS Server:        http://localhost:5000
Vibe Alchemist:     http://localhost:8081
```

**No port conflicts!** ✅

---

## 🔧 Change Port (If Needed)

If you need to change the port in the future:

### Method 1: Edit .env
```bash
nano .env
# Change: API_PORT=8082
# Restart: ./start.sh
```

### Method 2: Command Line
```bash
export API_PORT=8082
./start.sh
```

### Method 3: Docker Compose
```yaml
# docker-compose.yml
ports:
  - "8082:8080"  # Host:Container
```

---

## 📊 Port Summary

| Component | Port | Configurable | Notes |
|-----------|------|--------------|-------|
| Backend API | 8081 | `.env` → `API_PORT` | Main REST API |
| Frontend | 5173 | Vite default | Dev server |
| WebSocket | 8081 | Same as API | Real-time updates |
| Camera Feeds | 8081 | Same as API | MJPEG streams |

---

## ✅ Verification Checklist

- [x] `.env` has `API_PORT=8081`
- [x] `start.sh` uses port 8081
- [x] CORS allows `localhost:8081`
- [x] Documentation updated
- [x] No hardcoded `localhost:8080` in code
- [x] Frontend uses relative URLs (port-agnostic)
- [x] Docker compose defaults to 8081
- [x] Deployment guides reference 8081

---

## 🎯 Running Alongside HRMS

### System Requirements
- HRMS on port 5000
- Vibe Alchemist on port 8081
- Both can run 24/7 without conflicts

### Access Both Services
```
HRMS Dashboard:     http://your-server-ip:5000
Vibe Alchemist:     http://your-server-ip:8081
```

### Firewall Rules (if needed)
```bash
sudo ufw allow 5000/tcp    # HRMS
sudo ufw allow 8081/tcp    # Vibe Alchemist
sudo ufw allow 5173/tcp    # Frontend (dev only)
```

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Check what's using port 8081
sudo lsof -i :8081

# Kill the process
sudo kill -9 <PID>

# Or change Vibe Alchemist port
nano .env  # API_PORT=8082
```

### Can't Access Backend
```bash
# Verify backend is running
curl http://localhost:8081/api/cameras

# Check logs
tail -f logs/backend.log
```

### CORS Errors
- Ensure frontend is on port 5173
- Ensure backend CORS includes your frontend URL
- Check `api/api_server.py` CORS configuration

---

## 📞 Quick Reference

**Start Both Servers:**
```bash
# HRMS (existing - already configured)
# Runs on port 5000

# Vibe Alchemist
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
./start.sh
# Runs on port 8081
```

**Test Both Services:**
```bash
curl http://localhost:5000/health    # HRMS
curl http://localhost:8081/api       # Vibe Alchemist
```

**Both running in parallel!** ✅
