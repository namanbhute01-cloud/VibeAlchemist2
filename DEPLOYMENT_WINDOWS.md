# Windows Deployment Guide - Docker Desktop

## Prerequisites

### 1. Install Docker Desktop for Windows

1. Download from: https://www.docker.com/products/docker-desktop/
2. During installation, select **"Use WSL 2 instead of Hyper-V"** (recommended)
3. If you don't have WSL2 installed, Docker will prompt you to install it:
   ```powershell
   # Run in Administrator PowerShell if needed
   wsl --install
   ```
4. After installation, **restart your computer**
5. Open Docker Desktop and complete the initial setup
6. Ensure Docker is running (check system tray for Docker icon)

### 2. Verify Installation

Open PowerShell and run:
```powershell
docker --version
docker compose version
```

You should see version output for both commands.

---

## Quick Deploy

### First-Time Setup

1. **Copy the project folder** to your Windows machine (e.g., `C:\Projects\VibeAlchemist\`)

2. **Open PowerShell** in the `vibe_alchemist_v2` directory:
   ```powershell
   cd "C:\Projects\VibeAlchemist\vibe_alchemist_v2"
   ```

3. **Configure `.env` file**:
   - Copy `.env.example` to `.env` if not already present
   - Edit `.env` with your configuration
   - Key settings for Windows:
     ```env
     API_HOST=0.0.0.0
     API_PORT=8000
     ```

4. **Build and start**:
   ```powershell
   docker compose up -d --build
   ```

5. **Check status**:
   ```powershell
   docker compose ps
   docker compose logs -f
   ```

6. **Access the app**: Open browser to `http://localhost:8000`

### Subsequent Deployments

```powershell
# Pull latest code (if using Git)
git pull

# Rebuild and restart
docker compose up -d --build

# Or just restart (no rebuild needed)
docker compose restart
```

---

## Management Commands

### View Logs
```powershell
# Follow live logs
docker compose logs -f

# Last 100 lines
docker compose logs --tail=100

# Backend only
docker compose logs vibe-alchemist-v2
```

### Stop Server
```powershell
docker compose down
```

### Stop and Remove All Data
```powershell
docker compose down -v
```

### Rebuild from Scratch
```powershell
docker compose down --rmi all
docker compose up -d --build
```

### View Resource Usage
```powershell
docker stats vibe-alchemist-v2
```

### Access Container Shell
```powershell
docker exec -it vibe-alchemist-v2 bash
```

---

## Configuration

### Changing the Port

Edit `.env`:
```env
API_PORT=8000
```
Then rebuild:
```powershell
docker compose down
docker compose up -d --build
```

### Persistent Data

The following data persists across restarts:
- **`temp_faces/`** - Face registry (Docker volume)
- **`OfflinePlayback/`** - Music library (bind mount)
- **`logs/`** - Application logs (bind mount)
- **`.env`** - Configuration (bind mount, read-only)

### Updating Models

If you update AI models in the `models/` folder, rebuild:
```powershell
docker compose up -d --build
```

---

## Troubleshooting

### Docker Not Running
**Error:** `error during connect: ... pipe not found`

**Fix:** Start Docker Desktop from Start Menu. Wait for the whale icon in system tray.

### Port Already in Use
**Error:** `Bind for 0.0.0.0:8000 failed: port is already allocated`

**Fix:** 
```powershell
# Find what's using port 8000
netstat -ano | findstr :8000

# Kill the process (replace PID)
taskkill /PID <PID> /F

# Or change API_PORT in .env to a different port
```

### Build Fails
**Fix:** Clear Docker cache and rebuild:
```powershell
docker system prune -a
docker compose up -d --build
```

### Container Won't Start
```powershell
# View detailed logs
docker compose logs vibe-alchemist-v2

# Check health status
docker inspect --format='{{.State.Health.Status}}' vibe-alchemist-v2
```

### Permission Issues with Bind Mounts
If you get permission errors on mounted folders, ensure Docker Desktop has access to the drive:
1. Open Docker Desktop Settings
2. Go to **Resources > File sharing**
3. Add your project drive (e.g., `C:\`)

### Out of Memory
If the container uses too much memory, adjust Docker Desktop limits:
1. Docker Desktop Settings > **Resources**
2. Increase Memory limit (recommend 4GB+ for AI models)

---

## Automated Updates (Optional)

Create a PowerShell script for easy updates:

**`Update-Server.ps1`**
```powershell
Write-Host "Pulling latest code..." -ForegroundColor Cyan
git pull

Write-Host "Rebuilding and restarting..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host "Waiting for health check..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

$status = docker inspect --format='{{.State.Health.Status}}' vibe-alchemist-v2
if ($status -eq "healthy") {
    Write-Host "Server is healthy at http://localhost:8000" -ForegroundColor Green
} else {
    Write-Host "Warning: Server status is $status" -ForegroundColor Yellow
    docker compose logs --tail=50
}
```

---

## Running as a Service (Auto-Start)

To auto-start the server on Windows login:

### Task Scheduler Method

1. Create a batch file `Start-VibeAlchemist.bat`:
   ```batch
   @echo off
   cd /d "C:\Projects\VibeAlchemist\vibe_alchemist_v2"
   docker compose up -d
   ```

2. Open **Task Scheduler** (search in Start Menu)

3. Create a new task:
   - **General**: Name it "Vibe Alchemist", check "Run whether user is logged on or not"
   - **Triggers**: New trigger > "At log on"
   - **Actions**: Start a program > Browse to `Start-VibeAlchemist.bat`
   - **Conditions**: Uncheck "Start the task only if the computer is on AC power"

---

## Architecture Notes

- The Docker container runs **Python 3.11-slim** (Debian)
- Frontend is built during Docker image build (Node 20)
- Backend runs on **Uvicorn** (ASGI server)
- AI models (YOLOv8, ArcFace, DEX-Age) are loaded at startup
- Health check runs every 30s on `/health` endpoint
- Default resource limits: 2.5 CPU cores, 3GB RAM
