#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Unified Startup Script
# Starts both backend (FastAPI) and frontend (Vite/React)
# 
# Usage: ./start.sh
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

# PIDs
BACKEND_PID=""
FRONTEND_PID=""

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
    
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "  Stopping frontend (PID: $FRONTEND_PID)..."
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    
    # Cleanup any orphaned processes
    pkill -f "python.*main.py" 2>/dev/null || true
    pkill -f "vite.*5173" 2>/dev/null || true
    
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
        lsof -ti:$port | xargs kill -9 2>/dev/null || true
        sleep 1
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
    
    # For frontend, just check if it's serving HTML
    if [ "$name" = "Frontend" ]; then
        if curl -s --max-time 2 "http://localhost:5173" 2>&1 | grep -qi "vite\|react\|html"; then
            log_success "$name is ready!"
            return 0
        fi
    fi
    
    log_error "$name failed to start"
    return 1
}

# ═══════════════════════════════════════════════════════════════
# Main startup sequence
# ═══════════════════════════════════════════════════════════════

echo -e ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}        ${BLUE}VIBE ALCHEMIST V2${NC} - Starting Services        ${CYAN}║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════╝${NC}"
echo -e ""

# Create log directory
mkdir -p "$LOG_DIR"

# Step 1: Free up ports
log_info "Checking ports..."
free_port 8081
free_port 5173
log_success "Ports cleared"

# Step 2: Check Python venv
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    log_info "Creating Python virtual environment..."
    cd "$SCRIPT_DIR" && python3 -m venv venv
    log_success "Virtual environment created"
fi

# Step 3: Check Node modules
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log_info "Installing Node dependencies..."
    cd "$FRONTEND_DIR" && npm install
    log_success "Node dependencies installed"
fi

# Step 4: Start Backend
echo -e ""
log_info "Starting Backend (FastAPI on port 8081)..."
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$SCRIPT_DIR"
source venv/bin/activate

# Start backend with output to log file
python -u main.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

log_info "Backend PID: $BACKEND_PID"

# Wait for backend to be ready (models take time to load)
if ! wait_for_service "http://localhost:8081/api/cameras" "Backend API" 90; then
    log_error "Backend failed to start. Check logs:"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    tail -50 "$LOG_DIR/backend.log"
    exit 1
fi

# Show backend status
echo -e ""
log_success "Backend is running!"
echo -e "  ${CYAN}API:${NC}      http://localhost:8081/api"
echo -e "  ${CYAN}WebSocket:${NC} ws://localhost:8081/ws"
echo -e "  ${CYAN}Camera Feed:${NC} http://localhost:8081/feed/0"
echo -e ""

# Step 5: Start Frontend
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
log_info "Starting Frontend (Vite on port 5173)..."
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$FRONTEND_DIR"

# Start frontend with output to log file
npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

log_info "Frontend PID: $FRONTEND_PID"

# Wait for frontend to be ready
if ! wait_for_service "http://localhost:5173" "Frontend" 30; then
    log_error "Frontend failed to start. Check logs:"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    tail -50 "$LOG_DIR/frontend.log"
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
echo -e "  ${CYAN}Frontend:${NC}  http://localhost:5173"
echo -e "  ${CYAN}Network:${NC}   http://$NETWORK_IP:5173"
echo -e "  ${CYAN}Backend:${NC}   http://localhost:8081/api"
echo -e ""
echo -e "  ${YELLOW}Quick Links:${NC}"
echo -e "    • Dashboard:  http://localhost:5173/"
echo -e "    • Cameras:    http://localhost:5173/cameras"
echo -e "    • Playlist:   http://localhost:5173/playlist"
echo -e "    • Audience:   http://localhost:5173/audience"
echo -e "    • Settings:   http://localhost:5173/settings"
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
if curl -s http://localhost:8081/api/playback/status | grep -q "song"; then
    log_success "Backend API: OK"
else
    log_warning "Backend API: Response unexpected"
fi

# Check frontend
if curl -s http://localhost:5173 | grep -q "alchemist"; then
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
    
    # Check if frontend is still running
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo -e "${RED}[System] Frontend process died unexpectedly${NC}"
        tail -20 "$LOG_DIR/frontend.log"
        exit 1
    fi
    
    sleep 5
done
