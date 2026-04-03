# Vibe Alchemist V2 - Deployment Guide

Complete guide for deploying Vibe Alchemist V2 alongside an existing HRMS server.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Running Alongside HRMS](#running-alongside-hrms)
3. [One-Time Server Setup](#one-time-server-setup)
4. [CI/CD Auto-Deploy (GitHub Actions)](#cicd-auto-deploy)
5. [Manual Deploy](#manual-deploy)
6. [Management Commands](#management-commands)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              Production Server                   │
│                                                   │
│  ┌─────────────────┐    ┌──────────────────────┐ │
│  │   HRMS Server   │    │  Vibe Alchemist V2   │ │
│  │   Port: 5000    │    │   Port: 8081         │ │
│  │   (existing)    │    │   (Docker container) │ │
│  └─────────────────┘    └──────────────────────┘ │
│                                                   │
│  Both run in parallel, no port conflicts          │
└─────────────────────────────────────────────────┘
         ↓                        ↓
    http://server:5000     http://server:8081
```

### Key Design Decisions

| Aspect | Detail |
|--------|--------|
| **Port** | 8081 (avoids HRMS on 5000) |
| **Runtime** | Docker container (isolated, clean) |
| **Config** | `.env` file (mounted into container) |
| **Persistence** | Docker volumes for temp data, bind mounts for music/logs |
| **Auto-start** | systemd service or Docker `restart: unless-stopped` |
| **Updates** | `git pull` + `docker compose up -d --build` |

---

## Running Alongside HRMS

### Port Strategy

- **HRMS**: Port `5000` (existing, do NOT change)
- **Vibe Alchemist**: Port `8081` (set in `.env` as `API_PORT=8081`)

### Resource Isolation

Vibe Alchemist is limited to:
- **CPU**: Max 2.0 cores (reservation: 0.5)
- **Memory**: Max 2GB (reservation: 512MB)

This ensures HRMS always has resources available.

### Data Isolation

| Vibe Alchemist Data | Location | Shared with HRMS? |
|---------------------|----------|-------------------|
| `.env` config | `~/vibe-alchemist-v2/.env` | No |
| Music files | `~/vibe-alchemist-v2/OfflinePlayback/` | No |
| Models | `~/vibe-alchemist-v2/models/` | No |
| Logs | `~/vibe-alchemist-v2/logs/` | No |
| Temp faces | Docker volume `vibe_temp_faces` | No |

---

## One-Time Server Setup

### Step 1: Install Prerequisites

```bash
# SSH into your server
ssh user@your-server-ip

# Install Docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh

# Add your user to docker group (no sudo needed for docker commands)
sudo usermod -aG docker $USER
newgrp docker

# Install git (if not installed)
sudo apt install -y git
```

### Step 2: Clone the Repository

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/vibe-alchemist-v2.git
cd vibe-alchemist-v2
```

### Step 3: Configure `.env`

```bash
cp .env.example .env
nano .env
```

**Minimum required settings:**

```env
# Port (MUST NOT be 5000 to avoid HRMS conflict)
API_PORT=8081

# Camera sources (0 = default webcam, or add IP camera URLs)
CAMERA_SOURCES=0

# Music directory (inside container)
ROOT_MUSIC_DIR=/app/OfflinePlayback
```

### Step 4: Install Pre-commit Hooks (Optional, for developers)

```bash
cp .githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### Step 5: Initial Deploy

```bash
./deploy-prod.sh
```

### Step 6: Verify

```bash
# Check container is running
docker compose ps

# Check API is responding
curl http://localhost:8081/api/cameras

# Check the web UI
curl http://localhost:8081/ | head -20
```

---

## CI/CD Auto-Deploy

When you push to `main` branch, GitHub Actions automatically:
1. **Lint** — Python flake8 + TypeScript type check
2. **Test** — Run Python tests + env_manager validation
3. **Build** — Create Docker image and push to GitHub Container Registry
4. **Deploy** — SSH into server, pull code, restart container

### GitHub Secrets Required

Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret Name | Value | Required |
|-------------|-------|----------|
| `DEPLOY_SSH_KEY` | Private SSH key for server access | Yes |
| `DEPLOY_SERVER_HOST` | Server IP or hostname | Yes |
| `DEPLOY_SERVER_USER` | SSH username on server | Yes |
| `GITHUB_TOKEN` | (Auto-provided by GitHub) | Auto |

### Generate SSH Key for Deployment

```bash
# On the SERVER (not your local machine)
ssh-keygen -t ed25519 -f ~/.ssh/vibe_deploy -N "" -C "vibe-alchemist-ci"

# Show the public key - add this to GitHub deploy keys
cat ~/.ssh/vibe_deploy.pub

# Show the private key - add this to GitHub secret DEPLOY_SSH_KEY
cat ~/.ssh/vibe_deploy
```

### Add SSH Key to GitHub

1. **Repo Settings** → **Deploy keys** → **Add deploy key**
   - Title: `vibe-alchemist-deploy`
   - Key: paste the `.pub` content
   - Check "Allow write access"

2. **Repo Settings** → **Secrets and variables** → **Actions**
   - `DEPLOY_SSH_KEY`: paste the private key content
   - `DEPLOY_SERVER_HOST`: your server IP
   - `DEPLOY_SERVER_USER`: your SSH username

### Trigger a Deploy

```bash
# Just push to main
git add .
git commit -m "fix: settings persistence and CI/CD pipeline"
git push origin main
```

Watch the deploy in GitHub Actions → **Actions** tab.

---

## Manual Deploy

### Method 1: Deploy Script (Recommended)

```bash
cd ~/vibe-alchemist-v2
./deploy-prod.sh
```

This script:
- Pulls latest code from git
- Validates `.env` file
- Builds and restarts Docker container
- Runs health checks
- Reports status

### Method 2: Docker Compose Direct

```bash
cd ~/vibe-alchemist-v2

# Pull latest code
git pull origin main

# Rebuild and restart
docker compose up -d --build

# View logs
docker compose logs -f vibe-alchemist
```

### Method 3: Systemd Service

```bash
# Install the service file
sudo cp vibe-alchemist.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vibe-alchemist
sudo systemctl start vibe-alchemist

# Check status
sudo systemctl status vibe-alchemist

# View logs
journalctl -u vibe-alchemist -f
```

---

## Management Commands

### Container Management

```bash
# View status
docker compose ps

# View logs (last 100 lines)
docker compose logs --tail=100 vibe-alchemist

# Follow logs in real-time
docker compose logs -f vibe-alchemist

# Restart container
docker compose restart vibe-alchemist

# Stop container
docker compose down

# Start container
docker compose up -d

# Rebuild after code changes
docker compose up -d --build
```

### Config Management

```bash
# Edit configuration
nano .env

# Apply config changes (container reads .env on restart)
docker compose restart vibe-alchemist

# View current config
docker compose exec vibe-alchemist env | grep -E "API_|CAMERA|FACE|MODEL"
```

### Music Management

```bash
# Add music files (on the server)
cp /path/to/song.mp3 ~/vibe-alchemist-v2/OfflinePlayback/adults/
cp /path/to/kids-song.mp3 ~/vibe-alchemist-v2/OfflinePlayback/kids/

# Music is available immediately (no restart needed)
ls -la ~/vibe-alchemist-v2/OfflinePlayback/*/
```

### Backup & Restore

```bash
# Backup config and data
tar czf vibe-alchemist-backup-$(date +%Y%m%d).tar.gz \
    .env OfflinePlayback/ logs/

# Restore
tar xzf vibe-alchemist-backup-*.tar.gz
docker compose up -d
```

---

## Troubleshooting

### Port Conflict with HRMS

```bash
# Check what's using port 5000
ss -tlnp | grep 5000

# Check what's using port 8081
ss -tlnp | grep 8081

# If conflict, change API_PORT in .env
nano .env
# Set API_PORT=8082 (or any free port)
docker compose down && docker compose up -d
```

### Container Won't Start

```bash
# Check logs
docker compose logs vibe-alchemist

# Common issues:
# 1. Missing .env file
ls -la .env

# 2. Port already in use
ss -tlnp | grep 8081

# 3. Docker not running
sudo systemctl status docker
```

### Settings Not Persisting

```bash
# Check .env file has the changes
cat .env | grep -E "AUTO_PLAYLIST|FACE_OVERLAY|PRIVACY_MODE"

# Check container has the .env mounted
docker compose exec vibe-alchemist cat /app/.env | grep -E "AUTO_PLAYLIST|FACE_OVERLAY"

# Restart to reload
docker compose restart vibe-alchemist
```

### Camera Not Working

```bash
# Check camera sources in .env
grep CAMERA_SOURCES .env

# Test camera feed
curl http://localhost:8081/feed/0 > /tmp/test.jpg
file /tmp/test.jpg

# Check camera API
curl http://localhost:8081/api/cameras
```

### Music Not Playing

```bash
# Check music directory
ls -la ~/vibe-alchemist-v2/OfflinePlayback/*/

# Verify music API
curl http://localhost:8081/api/playback/library

# Check playback status
curl http://localhost:8081/api/playback/status
```

### High Memory Usage

```bash
# Check container resource usage
docker stats vibe-alchemist-v2

# If exceeding limits, increase in docker-compose.yml
# Then restart
docker compose up -d
```

---

## File Structure

```
~/vibe-alchemist-v2/
├── .env                          # Configuration (edit this)
├── .env.example                  # Template
├── docker-compose.yml            # Docker config
├── Dockerfile                    # Build definition
├── docker-entrypoint.sh          # Container startup script
├── deploy-prod.sh               # Production deploy script
├── vibe-alchemist.service        # Systemd service file
├── main.py                       # Entry point
├── requirements.txt              # Python dependencies
├── api/                          # FastAPI backend
│   ├── api_server.py
│   └── routes/
│       ├── settings.py           # Settings API (persists to .env)
│       ├── cameras.py
│       ├── playback.py
│       ├── vibe.py
│       └── faces.py
├── core/                         # Core modules
│   ├── env_manager.py            # Centralized env file manager
│   ├── vision_pipeline.py
│   ├── camera_pool.py
│   ├── vibe_engine.py
│   ├── face_vault.py
│   ├── face_registry.py
│   └── alchemist_player.py
├── frontend/                     # React frontend
│   └── src/
│       ├── pages/
│       │   └── Settings.tsx      # Settings page (saves to backend)
│       ├── lib/
│       │   └── api.ts            # API client
│       └── ...
├── OfflinePlayback/              # Music files (bind mount)
│   ├── kids/
│   ├── youths/
│   ├── adults/
│   └── seniors/
├── models/                       # AI models
├── logs/                         # Application logs
└── .github/
    └── workflows/
        └── ci-cd.yml            # CI/CD pipeline
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Deploy | `./deploy-prod.sh` |
| View logs | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` |
| Update code | `git pull && docker compose up -d --build` |
| Check health | `curl http://localhost:8081/api/cameras` |
| Edit config | `nano .env` then `docker compose restart` |
| Add music | `cp song.mp3 OfflinePlayback/adults/` |
