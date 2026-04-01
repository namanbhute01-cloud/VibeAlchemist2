# Vibe Alchemist V2 - Quick Deploy Reference

## 🚀 First Time Setup (One Time Only)

### On Remote Server:
```bash
# SSH into your remote server
ssh user@your-server-ip

# Download and run setup script
curl -O https://raw.githubusercontent.com/namanbhute01-cloud/VibeAlchemist2/main/deploy-setup.sh
chmod +x deploy-setup.sh
./deploy-setup.sh

# Copy the SSH public key it displays!
```

### On GitHub:
Go to: `https://github.com/namanbhute01-cloud/VibeAlchemist2/settings/secrets/actions/new`

Add these secrets:
```
DEPLOY_SSH_KEY        → (paste the private key from setup output)
DEPLOY_SERVER_HOST    → your-server-ip
DEPLOY_SERVER_USER    → your-username
API_PORT              → 8081 (HRMS uses 5000, so we use 8081)
```

---

## 📤 Deploy After Making Changes

### Option 1: Automatic (Recommended)
```bash
# Make your changes locally
git add .
git commit -m "Your commit message"
git push origin main

# That's it! GitHub auto-deploys in ~5 minutes
```

### Option 2: Manual (on remote server)
```bash
ssh user@server-ip
cd ~/vibe-alchemist-v2
git pull origin main
docker compose build
docker compose up -d
```

---

## 🔍 Monitoring

```bash
# SSH to server
ssh user@server-ip

# View logs
docker compose logs -f vibe-alchemist

# Check status
docker compose ps

# Check resource usage
docker stats vibe-alchemist-v2

# Test API
curl http://localhost:8081/api/cameras
```

---

## 🛑 Stop/Start/Restart

```bash
# Stop
docker compose down

# Start
docker compose up -d

# Restart
docker compose restart vibe-alchemist

# Rebuild (after code changes)
docker compose build
docker compose up -d
```

---

## 🔧 Common Issues

### Port Conflict with HRMS
```bash
# Check what's using port 5000
sudo lsof -i :5000

# Vibe Alchemist uses port 8081 by default (no conflict)
# If you need to change it:
cd ~/vibe-alchemist-v2
nano .env  # Change API_PORT=8082
docker compose down
docker compose up -d
```

### Deployment Fails
1. Check GitHub Actions: https://github.com/namanbhute01-cloud/VibeAlchemist2/actions
2. Verify SSH connection: `ssh user@server-ip`
3. Check server firewall allows SSH

### Container Won't Start
```bash
# Check logs
docker compose logs vibe-alchemist

# Try interactive start
docker compose up vibe-alchemist

# Check .env file
cat .env
```

---

## 📊 Architecture

```
Local Machine (Development)
    ↓ git push
GitHub Repository
    ↓ GitHub Actions
    ↓ Build Docker image
    ↓ Push to GHCR
    ↓ SSH deploy
Remote Server (Production)
    ├── HRMS Server (port 5000)
    └── Vibe Alchemist (port 8081) ← Runs in Docker
```

---

## 📁 File Locations (Remote Server)

```
~/vibe-alchemist-v2/
├── .env                    # Configuration
├── docker-compose.yml      # Docker config
├── logs/                   # Application logs
├── OfflinePlayback/        # Music files
└── temp_faces/             # Temporary face data (Docker volume)
```

---

## 🔐 Security Checklist

- [ ] SSH key added to GitHub secrets
- [ ] `.env` file NOT committed to git
- [ ] Firewall allows only necessary ports
- [ ] Docker container runs as non-root user
- [ ] Regular updates: `docker compose pull && docker compose up -d`

---

## 💡 Tips

1. **Test locally first**: Run `./start.sh` before pushing
2. **Small commits**: Deploy frequently with small changes
3. **Monitor logs**: Check logs after each deploy
4. **Backup music**: Keep music files in separate backup location
5. **Resource limits**: Adjust in `docker-compose.yml` if server is slow

---

## 📞 Quick Commands Reference

| Task | Command |
|------|---------|
| Deploy | `git push origin main` |
| View logs | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` |
| Start | `docker compose up -d` |
| Status | `docker compose ps` |
| Update | `git pull && docker compose up -d` |
| Cleanup | `docker image prune -f` |
| Access | `http://server-ip:8081` |

---

**HRMS on port 5000, Vibe Alchemist on port 8081 - Both run in parallel!** ✅
