#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Remote Server Setup Script
# Run this ONCE on your remote server to prepare for deployment
# ═══════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo -e ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}     ${BLUE}VIBE ALCHEMIST V2${NC} - Remote Server Setup         ${CYAN}║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════╝${NC}"
echo -e ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    log_error "Please do NOT run as root. Run as your regular user."
    exit 1
fi

# ───────────────────────────────────────────────────────────────
# Step 1: Install Docker (if not installed)
# ───────────────────────────────────────────────────────────────
log_info "Checking Docker installation..."

if ! command -v docker &> /dev/null; then
    log_warning "Docker not found. Installing Docker..."
    
    # Detect package manager
    if command -v apt &> /dev/null; then
        # Ubuntu/Debian
        sudo apt update
        sudo apt install -y ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt update
        sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        sudo yum install -y yum-utils
        sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    else
        log_error "Unsupported package manager. Please install Docker manually."
        exit 1
    fi
    
    log_success "Docker installed"
else
    log_success "Docker already installed: $(docker --version)"
fi

# ───────────────────────────────────────────────────────────────
# Step 2: Add user to docker group (no sudo needed)
# ───────────────────────────────────────────────────────────────
log_info "Configuring Docker permissions..."

if ! groups $USER | grep -q docker; then
    sudo usermod -aG docker $USER
    log_warning "Added $USER to docker group. You'll need to re-login or run: newgrp docker"
else
    log_success "User already in docker group"
fi

# ───────────────────────────────────────────────────────────────
# Step 3: Check HRMS server port conflict
# ───────────────────────────────────────────────────────────────
log_info "Checking for port conflicts with HRMS server..."

HRMS_PORT=5000
VIBE_PORT=8081

if ss -tlnp | grep -q ":$HRMS_PORT "; then
    log_warning "Port $HRMS_PORT is already in use (HRMS server detected)"
    log_info "Vibe Alchemist will use port $VIBE_PORT instead"
    echo "API_PORT=$VIBE_PORT" > .env
    log_success "Created .env with API_PORT=$VIBE_PORT"
else
    log_success "Port $HRMS_PORT is free. Vibe Alchemist will use port $VIBE_PORT"
    echo "API_PORT=$VIBE_PORT" > .env
fi

# ───────────────────────────────────────────────────────────────
# Step 4: Create application directory
# ───────────────────────────────────────────────────────────────
log_info "Creating application directory..."

APP_DIR=~/vibe-alchemist-v2
mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/logs"
mkdir -p "$APP_DIR/OfflinePlayback"

log_success "Created directory: $APP_DIR"

# ───────────────────────────────────────────────────────────────
# Step 5: Create systemd service (for auto-start on boot)
# ───────────────────────────────────────────────────────────────
log_info "Creating systemd service for auto-start..."

SERVICE_FILE="/tmp/vibe-alchemist.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Vibe Alchemist V2
After=network.target docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# Copy to systemd directory (requires sudo)
if sudo cp "$SERVICE_FILE" /etc/systemd/system/vibe-alchemist.service; then
    sudo systemctl daemon-reload
    sudo systemctl enable vibe-alchemist.service
    log_success "Systemd service created (auto-starts on boot)"
else
    log_warning "Could not create systemd service. Run with sudo manually."
fi

# ───────────────────────────────────────────────────────────────
# Step 6: Setup SSH key for GitHub Actions (optional)
# ───────────────────────────────────────────────────────────────
log_info "Setting up SSH for GitHub Actions deployment..."

SSH_DIR=~/.ssh
mkdir -p "$SSH_DIR"

if [ ! -f "$SSH_DIR/id_ed25519" ]; then
    ssh-keygen -t ed25519 -f "$SSH_DIR/id_ed25519" -N "" -C "vibe-alchemist-deploy"
    log_success "Generated SSH key pair"
    echo -e ""
    log_info "Add this public key to your GitHub repository secrets:"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    cat "$SSH_DIR/id_ed25519.pub"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e ""
    log_info "Secret name: DEPLOY_SSH_KEY"
else
    log_success "SSH key already exists"
fi

# Add GitHub to known_hosts
ssh-keyscan -H github.com >> "$SSH_DIR/known_hosts" 2>/dev/null

# ───────────────────────────────────────────────────────────────
# Step 7: Create .env template
# ───────────────────────────────────────────────────────────────
log_info "Creating .env configuration..."

cat > "$APP_DIR/.env" << EOF
# Vibe Alchemist V2 - Environment Configuration

# Port (8081 to avoid conflict with HRMS on 5000)
API_PORT=8081

# Camera sources (comma-separated)
# Use 0 for default webcam, or RTSP/HTTP URLs
CAMERA_SOURCES=0

# Video settings
TARGET_HEIGHT=720
FRAME_RATE_LIMIT=15

# Vision confidence thresholds
FACE_DETECTION_CONF=0.5
PERSON_DETECTION_CONF=0.4
FACE_SIMILARITY_THRESHOLD=0.65

# Google Drive (optional)
GDRIVE_FOLDER_ID=your_folder_id_here
DRIVE_UPLOAD_INTERVAL=900

# Music player
DEFAULT_VOLUME=70
SHUFFLE_MODE=true
EOF

log_success "Created .env at $APP_DIR/.env"

# ───────────────────────────────────────────────────────────────
# Summary
# ───────────────────────────────────────────────────────────────
echo -e ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}         ${BLUE}Server Setup Complete!${NC}                    ${GREEN}║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo -e ""
echo -e "Next steps:"
echo -e ""
echo -e "  ${CYAN}1.${NC} Add SSH key to GitHub:"
echo -e "     Settings → Secrets and variables → Actions"
echo -e "     Secret: DEPLOY_SSH_KEY"
echo -e "     Value: $(cat $SSH_DIR/id_ed25519.pub)"
echo -e ""
echo -e "  ${CYAN}2.${NC} Add these GitHub secrets:"
echo -e "     - DEPLOY_SERVER_HOST: $(hostname -I | awk '{print $1}')"
echo -e "     - DEPLOY_SERVER_USER: $USER"
echo -e "     - API_PORT: 8081"
echo -e ""
echo -e "  ${CYAN}3.${NC} Push to GitHub main branch to auto-deploy"
echo -e ""
echo -e "  ${CYAN}4.${NC} Or manually deploy:"
echo -e "     cd $APP_DIR"
echo -e "     docker compose up -d"
echo -e ""
echo -e "  ${CYAN}5.${NC} Access at: http://$(hostname -I | awk '{print $1}'):8081"
echo -e ""
log_info "HRMS server (port 5000) and Vibe Alchemist (port 8081) can now run in parallel!"
echo -e ""
