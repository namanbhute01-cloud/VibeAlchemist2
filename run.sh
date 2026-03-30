#!/bin/bash

# Vibe Alchemist V2 - Single Terminal Launcher
# Starts both backend and frontend from one terminal
# Press Ctrl+C to stop both and cleanup temp_faces

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV_DIR="$SCRIPT_DIR/venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║          VIBE ALCHEMIST V2 - LAUNCHER                 ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  Shutting down Vibe Alchemist V2...${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    # Kill child processes
    if [ ! -z "$BACKEND_PID" ]; then
        echo -e "${YELLOW}  Stopping backend (PID: $BACKEND_PID)...${NC}"
        kill $BACKEND_PID 2>/dev/null || true
    fi
    
    if [ ! -z "$FRONTEND_PID" ]; then
        echo -e "${YELLOW}  Stopping frontend (PID: $FRONTEND_PID)...${NC}"
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    
    # Cleanup temp_faces
    TEMP_DIR="$SCRIPT_DIR/temp_faces"
    if [ -d "$TEMP_DIR" ]; then
        COUNT=$(find "$TEMP_DIR" -name "*.png" | wc -l)
        if [ "$COUNT" -gt 0 ]; then
            rm -f "$TEMP_DIR"/*.png
            echo -e "${GREEN}  ✓ Cleaned up $COUNT face(s) from temp_faces${NC}"
        fi
    fi
    
    echo -e "${GREEN}  ✓ Shutdown complete${NC}"
    echo ""
    exit 0
}

# Register cleanup on Ctrl+C
trap cleanup SIGINT SIGTERM

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}✗ Virtual environment not found at: $VENV_DIR${NC}"
    echo -e "${YELLOW}  Please install dependencies first:${NC}"
    echo "    cd \"$SCRIPT_DIR\" && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check if frontend node_modules exists
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${YELLOW}! Frontend dependencies not found. Installing...${NC}"
    cd "$FRONTEND_DIR"
    npm install
    cd "$SCRIPT_DIR"
fi

echo -e "${GREEN}✓ Starting Backend...${NC}"
echo -e "  ${BLUE}→${NC} API will be available at: http://localhost:8080"
echo ""

# Activate virtual environment and start backend
source "$VENV_DIR/bin/activate"
python main.py &
BACKEND_PID=$!

echo -e "${GREEN}✓ Starting Frontend...${NC}"
echo -e "  ${BLUE}→${NC} UI will be available at: http://localhost:5173"
echo ""

# Wait a bit for backend to start
sleep 5

# Start frontend
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ Vibe Alchemist V2 is running!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BLUE}→${NC} Backend: http://localhost:8080"
echo -e "  ${BLUE}→${NC} Frontend: http://localhost:5173"
echo ""
echo -e "  ${YELLOW}Press Ctrl+C to stop both servers${NC}"
echo -e "  ${YELLOW}(temp_faces will be cleaned up automatically)${NC}"
echo ""

# Wait for both processes
wait
