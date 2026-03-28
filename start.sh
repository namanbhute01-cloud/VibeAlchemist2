#!/bin/bash

# Vibe Alchemist V2 - Unified Startup Script
# Starts both backend and frontend in a single terminal with cleanup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Function to cleanup background processes on exit
cleanup() {
    echo -e "\n\033[1;31m[System] Stopping services...\033[0m"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit
}

# Trap Ctrl+C (SIGINT)
trap cleanup SIGINT SIGTERM

echo -e "\033[1;34m=== VIBE ALCHEMIST V2 UNIFIED STARTUP ===\033[0m"

# 1. Clear occupied ports
echo "[1/3] Clearing ports 8080 and 5173..."
lsof -ti:8080,5173 | xargs kill -9 2>/dev/null || true

# 2. Start Backend
echo "[2/3] Starting Backend (FastAPI)..."
source "$SCRIPT_DIR/venv/bin/activate"
python3 "$SCRIPT_DIR/main.py" &
BACKEND_PID=$!

# Give backend a moment to initialize models
sleep 5

# 3. Start Frontend
echo "[3/3] Starting Frontend (Vite)..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo -e "\n\033[1;32m[Success] Both services are now running in this terminal!\033[0m"
echo -e "Backend:  \033[4;36mhttp://127.0.0.1:8080\033[0m"
echo -e "Frontend: \033[4;36mhttp://127.0.0.1:5173\033[0m"
echo -e "\033[1;33mLogs from both services will appear below. Press Ctrl+C to stop both.\033[0m\n"

# Keep the script running to maintain background processes
wait
