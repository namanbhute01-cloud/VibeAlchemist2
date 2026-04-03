#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Production Deploy Script
# 
# Usage: ./deploy-prod.sh
# 
# This script:
#   1. Pulls latest code from git
#   2. Validates .env file
#   3. Rebuilds/updates Docker container
#   4. Runs health checks
#   5. Reports status
#
# Designed to run on the production server alongside HRMS
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
LOG_FILE="$APP_DIR/logs/deploy.log"
DEPLOY_START=$(date +%s)

# ═══════════════════════════════════════════════════════════════
# Pre-flight checks
# ═══════════════════════════════════════════════════════════════
preflight() {
    echo -e ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}     ${BLUE}VIBE ALCHEMIST V2${NC} - Production Deploy           ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════╝${NC}"
    echo -e ""

    # Check git
    if ! command -v git &>/dev/null; then
        log_error "git is not installed"
        exit 1
    fi

    # Check docker
    if ! command -v docker &>/dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null 2>&1; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    # Check .env file
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env file not found at $ENV_FILE"
        log_info "Copy .env.example to .env and configure it"
        exit 1
    fi

    # Check HRMS port conflict
    HRMS_PORT=5000
    VIBE_PORT=$(grep -E "^API_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8081")

    if ss -tlnp 2>/dev/null | grep -q ":$HRMS_PORT "; then
        log_info "HRMS server detected on port $HRMS_PORT"
        if [ "$VIBE_PORT" = "$HRMS_PORT" ]; then
            log_error "Port conflict! Vibe Alchemist and HRMS both on port $HRMS_PORT"
            log_info "Change API_PORT in .env to 8081 or another free port"
            exit 1
        else
            log_success "No port conflict (HRMS: $HRMS_PORT, Vibe: $VIBE_PORT)"
        fi
    else
        log_info "HRMS server not detected on port $HRMS_PORT"
    fi

    log_success "Pre-flight checks passed"
}

# ═══════════════════════════════════════════════════════════════
# Pull latest code
# ═══════════════════════════════════════════════════════════════
pull_code() {
    log_info "Pulling latest code from git..."

    cd "$APP_DIR"

    # Check if this is a git repo
    if [ ! -d ".git" ]; then
        log_warn "Not a git repository. Skipping pull."
        return 0
    fi

    # Stash local changes (preserve .env and data)
    git stash --include-untracked 2>/dev/null || true

    # Pull latest
    if git pull origin main 2>&1; then
        log_success "Code updated"
    else
        log_warn "Git pull failed (may already be up to date)"
    fi

    # Restore stashed changes
    git stash pop 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════
# Validate environment
# ═══════════════════════════════════════════════════════════════
validate_env() {
    log_info "Validating environment..."

    # Ensure required directories exist
    mkdir -p "$APP_DIR/logs"
    mkdir -p "$APP_DIR/OfflinePlayback"/{kids,youths,adults,seniors}
    mkdir -p "$APP_DIR/models"
    mkdir -p "$APP_DIR/temp_faces"

    # Validate .env has required keys
    local required_keys=("API_PORT" "CAMERA_SOURCES" "TARGET_HEIGHT")
    for key in "${required_keys[@]}"; do
        if ! grep -q "^${key}=" "$ENV_FILE"; then
            log_warn "Missing $key in .env, adding default"
            echo "${key}=0" >> "$ENV_FILE"
        fi
    done

    # Ensure API_PORT is set
    local api_port
    api_port=$(grep -E "^API_PORT=" "$ENV_FILE" | cut -d= -f2)
    if [ -z "$api_port" ]; then
        echo "API_PORT=8081" >> "$ENV_FILE"
        api_port=8081
    fi

    log_success "Environment validated (port: $api_port)"
}

# ═══════════════════════════════════════════════════════════════
# Deploy with Docker
# ═══════════════════════════════════════════════════════════════
deploy() {
    log_info "Deploying..."

    cd "$APP_DIR"

    # ── Build frontend locally (submodule not available to Docker) ──
    log_info "Building frontend locally..."
    if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
        cd frontend
        if [ ! -d "node_modules" ]; then
            npm install
        fi
        npm run build
        cd "$APP_DIR"
        log_success "Frontend built"
    fi

    # Determine compose command
    local compose_cmd="docker compose"
    if ! docker compose version &>/dev/null 2>&1; then
        if command -v docker-compose &>/dev/null; then
            compose_cmd="docker-compose"
        else
            log_error "Docker Compose not installed"
            exit 1
        fi
    fi

    # Build and start (use pre-built frontend, skip frontend-builder stage)
    log_info "Building and starting container..."
    $compose_cmd up -d --build --remove-orphans vibe-alchemist 2>&1 | tee -a "$LOG_FILE"

    if [ $? -eq 0 ]; then
        log_success "Container started"
    else
        log_error "Container failed to start"
        $compose_cmd logs --tail=50 vibe-alchemist
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════
health_check() {
    local api_port
    api_port=$(grep -E "^API_PORT=" "$ENV_FILE" | cut -d= -f2)
    local max_attempts=30
    local attempt=1

    log_info "Running health checks (port: $api_port)..."

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "http://localhost:${api_port}/api/cameras" > /dev/null 2>&1; then
            log_success "Backend API is responding"

            # Get detailed status
            local status
            status=$(curl -sf "http://localhost:${api_port}/api/playback/status" 2>/dev/null || echo "{}")
            log_info "Playback status: $status"

            return 0
        fi
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "Health check failed after $max_attempts attempts"
    log_error "Check logs: docker compose logs vibe-alchemist"
    return 1
}

# ═══════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════
cleanup() {
    log_info "Cleaning up old Docker images..."
    docker image prune -f --filter "until=24h" 2>/dev/null || true
    log_success "Cleanup complete"
}

# ═══════════════════════════════════════════════════════════════
# Status report
# ═══════════════════════════════════════════════════════════════
report() {
    local deploy_end=$(date +%s)
    local deploy_duration=$((deploy_end - DEPLOY_START))

    local api_port
    api_port=$(grep -E "^API_PORT=" "$ENV_FILE" | cut -d= -f2)
    local network_ip
    network_ip=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "unknown")

    echo -e ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}          ${BLUE}DEPLOYMENT SUCCESSFUL!${NC}                      ${GREEN}║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
    echo -e ""
    echo -e "  ${CYAN}Duration:${NC}     ${deploy_duration}s"
    echo -e "  ${CYAN}Local:${NC}       http://localhost:${api_port}"
    echo -e "  ${CYAN}Network:${NC}      http://${network_ip}:${api_port}"
    echo -e ""
    echo -e "  ${CYAN}Quick Links:${NC}"
    echo -e "    • Dashboard:  http://${network_ip}:${api_port}/"
    echo -e "    • Settings:   http://${network_ip}:${api_port}/settings"
    echo -e "    • Cameras:    http://${network_ip}:${api_port}/cameras"
    echo -e "    • Playlist:   http://${network_ip}:${api_port}/playlist"
    echo -e ""
    echo -e "  ${CYAN}Management:${NC}"
    echo -e "    • Logs:       docker compose logs -f vibe-alchemist"
    echo -e "    • Stop:       docker compose down"
    echo -e "    • Restart:    docker compose restart vibe-alchemist"
    echo -e "    • Status:     docker compose ps"
    echo -e ""

    # HRMS coexistence info
    if ss -tlnp 2>/dev/null | grep -q ":5000 "; then
        echo -e "  ${CYAN}HRMS Coexistence:${NC}"
        echo -e "    • HRMS Server:  http://${network_ip}:5000"
        echo -e "    • Vibe Alchemist: http://${network_ip}:${api_port}"
        echo -e "    • Both running in parallel ✓"
        echo -e ""
    fi
}

# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
main() {
    mkdir -p "$APP_DIR/logs"

    preflight
    pull_code
    validate_env
    deploy
    health_check
    cleanup
    report

    log_success "Deploy complete at $(date)" | tee -a "$LOG_FILE"
}

main "$@"
