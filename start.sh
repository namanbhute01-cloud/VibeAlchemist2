#!/bin/bash

# Vibe Alchemist V2 - Unified Startup Script
# Starts both backend and frontend in a single terminal

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Function to cleanup on exit
cleanup() {
    echo -e "\n\033[1;31m[System] Stopping services...\033[0m"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    pkill -f "python.*main.py" 2>/dev/null
    pkill -f vite 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM

echo -e "\033[1;34m=== VIBE ALCHEMIST V2 ===\033[0m"
echo "Starting Backend & Frontend..."

# Clear occupied ports
echo "Clearing ports..."
lsof -ti:8080 | xargs kill -9 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true

# Check dependencies
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "Creating Python venv..."
    cd "$SCRIPT_DIR" && python -m venv venv
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "Installing Node dependencies..."
    cd "$FRONTEND_DIR" && npm install --silent
fi

# Start backend
echo "[Backend] Starting FastAPI on port 8080..."
cd "$SCRIPT_DIR"
source venv/bin/activate
DEBUG=false python main.py &
BACKEND_PID=$!

# Wait for backend to initialize
sleep 5

# Start frontend
echo "[Frontend] Starting Vite dev server on port 5173..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo -e "\033[1;32m✓ Services started!\033[0m"
echo "  Backend:  http://127.0.0.1:8080"
echo "  Frontend: http://127.0.0.1:5173"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Wait for both processes
wait
