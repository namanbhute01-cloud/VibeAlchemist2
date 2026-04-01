# Vibe Alchemist V2 - Deployment Guide

## 📋 Overview

This guide covers:
1. **Auto-deployment** from your local machine to remote server via GitHub
2. **Running alongside HRMS** server without conflicts
3. **Manual deployment** options

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    YOUR LOCAL MACHINE                            │
│  (Make changes → git push → auto-deploy triggers)               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    GitHub Repository
                              ↓
                    GitHub Actions CI/CD
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    REMOTE SERVER                                 │
│  ┌─────────────────┐  ┌─────────────────────────────────────┐   │
│  │   HRMS Server   │  │      Vibe Alchemist V2              │   │
│  │   Port: 8080    │  │      Port: 8081 (or 8080 if free)   │   │
│  │   (existing)    │  │      (Docker container)             │   │
│  └─────────────────┘  └─────────────────────────────────────┘   │
│                                                                  │
│  Both run in parallel without conflicts!                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (3 Steps)

### Step 1: Setup Remote Server

SSH into your remote server and run:

```bash
# On remote server
cd ~
curl -O https://raw.githubusercontent.com/namanbhute01-cloud/VibeAlchemist2/main/deploy-setup.sh
chmod +x deploy-setup.sh
./deploy-setup.sh
```

This script will:
- Install Docker (if needed)
- Configure permissions
- Detect HRMS port conflicts
- Create systemd service for auto-start
- Generate SSH keys for GitHub Actions

**Important:** After running, it will show you a public SSH key. Copy it!

### Step 2: Configure GitHub Secrets

Go to your GitHub repository: `https://github.com/namanbhute01-cloud/VibeAlchemist2`

1. **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add these secrets:

| Secret Name | Value | Description |
|-------------|-------|-------------|
| `DEPLOY_SSH_KEY` | (from deploy-setup.sh output) | Private key for SSH access |
| `DEPLOY_SERVER_HOST` | `your.server.ip.address` | Remote server IP or hostname |
| `DEPLOY_SERVER_USER` | `your-username` | SSH username on remote server |
| `API_PORT` | `8081` (or `8080` if free) | Port for Vibe Alchemist |
| `GDRIVE_FOLDER_ID` | (optional) | Google Drive folder ID |
| `CAMERA_SOURCES` | (optional) | Camera URLs |

### Step 3: Push to Deploy

```bash
# On your local machine
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"

# Make any changes you want
git add .
git commit -m "Update feature"
git push origin main
```

**That's it!** GitHub Actions will automatically:
1. Build the Docker image
2. Push to GitHub Container Registry
3. Deploy to your remote server via SSH
4. Restart the container with new code

---

## 🔧 Running Alongside HRMS Server

### Port Configuration

The system automatically handles port conflicts:

| Scenario | HRMS Port | Vibe Alchemist Port |
|----------|-----------|---------------------|
| HRMS uses 5000 | 5000 | 8081 (default) |
| HRMS uses different port | 3000 | 8081 (default) |

### Manual Port Override

Edit `.env` on the remote server:

```bash
# On remote server
cd ~/vibe-alchemist-v2
nano .env

# Change:
API_PORT=8081  # Any free port
```

Then restart:

```bash
docker compose down
docker compose up -d
```

### Access Both Services

```
HRMS:           http://server-ip:5000
Vibe Alchemist: http://server-ip:8081
```

---

## 📦 Deployment Methods

### Method 1: GitHub Actions (Recommended)

**Pros:** Automatic, version-controlled, rollback support

```bash
# Just push to main branch
git push origin main
```

**Workflow:**
1. Code change on local
2. `git push`
3. GitHub Actions builds Docker image
4. Deploys to remote server
5. Container restarts with new code

### Method 2: Manual Docker Deploy

**Pros:** Full control, no GitHub setup needed

```bash
# On remote server
cd ~/vibe-alchemist-v2

# Pull latest code
git pull origin main

# Rebuild and restart
docker compose build
docker compose up -d

# View logs
docker compose logs -f vibe-alchemist
```

### Method 3: Direct SSH Deploy Script

Create a deploy script on your local machine:

```bash
#!/bin/bash
# deploy.sh - Run locally to deploy to remote server

SERVER="user@server-ip"
APP_DIR="~/vibe-alchemist-v2"

echo "Deploying to $SERVER..."

# Copy files
scp -r . $SERVER:$APP_DIR

# Restart on server
ssh $SERVER << 'EOF'
  cd $APP_DIR
  docker compose build
  docker compose up -d
  echo "✓ Deployed!"
EOF
```

---

## 🔍 Monitoring & Maintenance

### View Logs

```bash
# On remote server
cd ~/vibe-alchemist-v2

# Real-time logs
docker compose logs -f vibe-alchemist

# Last 100 lines
docker compose logs --tail=100 vibe-alchemist

# Backend only
docker exec vibe-alchemist-v2 tail -f logs/backend.log
```

### Check Status

```bash
# Container status
docker compose ps

# Resource usage
docker stats vibe-alchemist-v2

# Health check
curl http://localhost:8081/api/cameras
```

### Restart Service

```bash
# Using docker compose
docker compose restart vibe-alchemist

# Using systemd (if configured)
sudo systemctl restart vibe-alchemist
```

### Update/Upgrade

```bash
# Pull latest code
cd ~/vibe-alchemist-v2
git pull origin main

# Rebuild and restart
docker compose build
docker compose up -d

# Cleanup old images
docker image prune -f
```

---

## 🛡 Security Best Practices

### 1. Environment Variables

Never commit `.env` file:

```bash
# Already in .gitignore:
.env
token.json
credentials.json
```

### 2. SSH Key Security

```bash
# Set proper permissions
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
```

### 3. Firewall Rules

```bash
# Allow only necessary ports
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 5000/tcp    # HRMS
sudo ufw allow 8081/tcp    # Vibe Alchemist
sudo ufw enable
```

### 4. Non-Root Container

The Dockerfile runs as `vibeuser` (non-root) for security.

---

## 🐛 Troubleshooting

### Port Already in Use

```bash
# Find what's using a port
sudo lsof -i :8080

# Kill process
sudo kill -9 <PID>
```

### Docker Permission Denied

```bash
# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

### GitHub Actions Fails

1. Check **Actions** tab in GitHub
2. Click failed run → see error
3. Common issues:
   - SSH key not configured
   - Server IP/hostname wrong
   - Firewall blocking SSH

### Container Won't Start

```bash
# Check logs
docker compose logs vibe-alchemist

# Try manual start
docker compose up vibe-alchemist

# Check .env file
cat .env
```

### HRMS Conflict

If HRMS stops working after Vibe Alchemist deploy:

```bash
# Check which port Vibe is using
docker compose ps

# Change Vibe port if needed
nano .env  # Change API_PORT
docker compose down
docker compose up -d
```

**Note:** HRMS runs on port 5000, Vibe Alchemist on port 8081

---

## 📊 Performance Tuning

### Resource Limits (docker-compose.yml)

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'    # Max 2 CPU cores
      memory: 2G     # Max 2GB RAM
```

### Camera Optimization

For low-end servers, reduce camera load:

```env
# In .env
TARGET_HEIGHT=480      # Lower resolution
FRAME_RATE_LIMIT=10    # Lower FPS
```

---

## 🎯 Complete Workflow Example

### Local Development

```bash
# 1. Make changes
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
# Edit files...

# 2. Test locally
./start.sh

# 3. Commit and push
git add .
git commit -m "Add new feature"
git push origin main

# 4. Watch deployment
# Go to GitHub → Actions → See progress
```

### Remote Verification

```bash
# SSH to server
ssh user@server-ip

# Check deployment
cd ~/vibe-alchemist-v2
docker compose ps
curl http://localhost:8081/api/cameras

# View logs
docker compose logs -f
```

---

## 📞 Support

If you encounter issues:

1. Check logs: `docker compose logs vibe-alchemist`
2. Verify GitHub Actions: Repository → Actions tab
3. Test SSH manually: `ssh user@server-ip`
4. Check ports: `ss -tlnp | grep :808`

---

## 🎉 Summary

| Task | Command |
|------|---------|
| Setup server | `./deploy-setup.sh` |
| Deploy (auto) | `git push origin main` |
| Deploy (manual) | `docker compose up -d` |
| View logs | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Update | `git pull && docker compose up -d` |

**Both HRMS and Vibe Alchemist run in parallel!** 🚀
