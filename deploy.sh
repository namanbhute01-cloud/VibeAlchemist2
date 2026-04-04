#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - PRODUCTION DEPLOYMENT SCRIPT
# Builds frontend and starts backend in production mode
#
# Usage: ./deploy.sh
# Stop: Ctrl+C or ./stop.sh
# ═══════════════════════════════════════════════════════════════

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
LOG_DIR="$SCRIPT_DIR/logs"
STATIC_DIR="$SCRIPT_DIR/static"

# PIDs
BACKEND_PID=""

# ═══════════════════════════════════════════════════════════════
# Cleanup function
# ═══════════════════════════════════════════════════════════════
cleanup() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  Shutting down Vibe Alchemist V2...${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "  Stopping backend (PID: $BACKEND_PID)..."
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi

    # Cleanup any orphaned processes
    pkill -f "python.*main.py" 2>/dev/null || true

    # Cleanup temp_faces directory
    TEMP_DIR="$SCRIPT_DIR/temp_faces"
    if [ -d "$TEMP_DIR" ]; then
        COUNT=$(find "$TEMP_DIR" -name "*.png" 2>/dev/null | wc -l)
        if [ "$COUNT" -gt 0 ]; then
            rm -f "$TEMP_DIR"/*.png
            echo -e "${GREEN}  ✓ Cleaned up $COUNT face(s) from temp_faces${NC}"
        fi
    fi

    echo -e "${GREEN}  ✓ Shutdown complete${NC}"
    echo ""
    exit 0
}

trap cleanup SIGINT SIGTERM

# ═══════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

check_port() {
    local port=$1
    if ss -tlnp | grep -q ":$port "; then
        return 0  # Port is in use
    fi
    return 1  # Port is free
}

free_port() {
    local port=$1
    if check_port $port; then
        log_warning "Port $port is in use, freeing..."
        # Safe: only kill processes that are our own backend
        local pids
        pids=$(ss -tlnp "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                # Only kill if it's a python/uvicorn process (our backend)
                if ps -p "$pid" -o args= 2>/dev/null | grep -qE 'python|uvicorn|main\.py'; then
                    log_info "Stopping existing backend (PID: $pid)..."
                    kill "$pid" 2>/dev/null || true
                    sleep 1
                    # Force kill only if still running
                    if kill -0 "$pid" 2>/dev/null; then
                        kill -9 "$pid" 2>/dev/null || true
                    fi
                else
                    log_warning "Port $port is used by non-backend process (PID: $pid), skipping"
                fi
            done
        fi
    fi
}

wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=${3:-30}
    local attempt=1

    log_info "Waiting for $name..."
    while [ $attempt -le $max_attempts ]; do
        if curl -s --max-time 2 "$url" > /dev/null 2>&1; then
            log_success "$name is ready!"
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done

    log_error "$name failed to start"
    return 1
}

# ═══════════════════════════════════════════════════════════════
# Main deployment sequence
# ═══════════════════════════════════════════════════════════════

echo -e ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}        ${BLUE}VIBE ALCHEMIST V2${NC} - Production Deploy        ${CYAN}║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════╝${NC}"
echo -e ""

# Create log directory
mkdir -p "$LOG_DIR"

# Step 1: Free up ports
log_info "Checking ports..."
free_port 8000
log_success "Ports cleared"

# Step 2: Check Python venv
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    log_info "Creating Python virtual environment..."
    cd "$SCRIPT_DIR" && python3 -m venv venv
    log_success "Virtual environment created"
fi

# Step 3: Install Python dependencies
log_info "Installing Python dependencies..."
source "$SCRIPT_DIR/venv/bin/activate"
pip install -q -r "$SCRIPT_DIR/requirements.txt"
log_success "Python dependencies installed"

# Step 4: Build Frontend
echo -e ""
log_info "Building Frontend for production..."
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$FRONTEND_DIR"

# Check Node modules
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log_info "Installing Node dependencies..."
    npm install
    log_success "Node dependencies installed"
fi

# Build frontend
npm run build

if [ ! -d "$STATIC_DIR" ] || [ ! -f "$STATIC_DIR/index.html" ]; then
    log_error "Frontend build failed!"
    exit 1
fi

log_success "Frontend built successfully!"
echo -e "  ${CYAN}Static files:${NC} $STATIC_DIR"
echo -e ""

# Step 5: Start Backend (which serves the static files)
echo -e ""
log_info "Starting Backend (FastAPI on port 8000)..."
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$SCRIPT_DIR"

# Start backend with output to log file
python -u main.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

log_info "Backend PID: $BACKEND_PID"

# Wait for backend to be ready (models take time to load)
if ! wait_for_service "http://localhost:8000/api/cameras" "Backend API" 90; then
    log_error "Backend failed to start. Check logs:"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    tail -50 "$LOG_DIR/backend.log"
    exit 1
fi

# Get network IP
NETWORK_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "localhost")

# Step 6: Success!
echo -e ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}          ${BLUE}VIBE ALCHEMIST V2 - READY!${NC}                  ${GREEN}║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo -e ""
echo -e "  ${CYAN}Application:${NC} http://localhost:8000"
echo -e "  ${CYAN}Network:${NC}    http://$NETWORK_IP:8000"
echo -e "  ${CYAN}Backend API:${NC}  http://localhost:8000/api"
echo -e ""
echo -e "  ${YELLOW}Quick Links:${NC}"
echo -e "    • Dashboard:  http://localhost:8000/"
echo -e "    • Cameras:    http://localhost:8000/cameras"
echo -e "    • Playlist:   http://localhost:8000/playlist"
echo -e "    • Audience:   http://localhost:8000/audience"
echo -e "    • Settings:   http://localhost:8000/settings"
echo -e ""
echo -e "  ${YELLOW}API Endpoints:${NC}"
echo -e "    • GET  /api/cameras       - List cameras"
echo -e "    • GET  /api/playback/status - Playback status"
echo -e "    • POST /api/playback/next - Next track"
echo -e "    • GET  /api/faces         - Face statistics"
echo -e "    • GET  /api/vibe/current  - Current vibe state"
echo -e ""
echo -e "  ${RED}Press Ctrl+C to stop all services${NC}"
echo -e ""

# Verify services are working
log_info "Running health checks..."

# Check backend
if curl -s http://localhost:8000/api/playback/status | grep -q "song"; then
    log_success "Backend API: OK"
else
    log_warning "Backend API: Response unexpected"
fi

# Check frontend
if curl -s http://localhost:8000/ | grep -q "Vibe Alchemist"; then
    log_success "Frontend: OK"
else
    log_warning "Frontend: Response unexpected"
fi

echo -e ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}All systems operational! Open your browser and enjoy!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e ""

# Keep script running and monitor processes
while true; do
    # Check if backend is still running
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${RED}[System] Backend process died unexpectedly${NC}"
        tail -20 "$LOG_DIR/backend.log"
        exit 1
    fi

    sleep 5
done
