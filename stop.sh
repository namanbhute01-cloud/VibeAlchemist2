#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Stop Script
# Stops all running services with proper cleanup
# ═══════════════════════════════════════════════════════════════

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e ""
echo -e "${YELLOW}Stopping Vibe Alchemist V2 services...${NC}"
echo -e ""

# Find and kill backend processes (with graceful shutdown)
BACKEND_PIDS=$(pgrep -f "python.*main.py" 2>/dev/null || true)
if [ -n "$BACKEND_PIDS" ]; then
    echo -e "${YELLOW}Stopping backend processes:${NC} $BACKEND_PIDS"
    # Send SIGINT first to trigger cleanup handlers
    kill -INT $BACKEND_PIDS 2>/dev/null || true
    # Wait up to 10 seconds for graceful shutdown
    for i in {1..10}; do
        if ! kill -0 $BACKEND_PIDS 2>/dev/null; then
            break
        fi
        sleep 1
    done
    # Force kill if still running
    if kill -0 $BACKEND_PIDS 2>/dev/null; then
        echo -e "${YELLOW}Force stopping backend...${NC}"
        kill -9 $BACKEND_PIDS 2>/dev/null || true
    fi
    echo -e "${GREEN}✓ Backend stopped${NC}"
else
    echo "No backend processes found"
fi

# Find and kill frontend processes
FRONTEND_PIDS=$(pgrep -f "vite" 2>/dev/null || true)
if [ -n "$FRONTEND_PIDS" ]; then
    echo -e "${YELLOW}Stopping frontend processes:${NC} $FRONTEND_PIDS"
    kill $FRONTEND_PIDS 2>/dev/null || true
    echo -e "${GREEN}✓ Frontend stopped${NC}"
else
    echo "No frontend processes found"
fi

# Clean up temp_faces directory
echo -e ""
echo -e "${YELLOW}Cleaning up temp_faces...${NC}"
TEMP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/temp_faces"
if [ -d "$TEMP_DIR" ]; then
    DELETED=0
    for f in "$TEMP_DIR"/*.png "$TEMP_DIR"/*.jpg; do
        if [ -f "$f" ]; then
            rm -f "$f"
            DELETED=$((DELETED + 1))
        fi
    done
    if [ $DELETED -gt 0 ]; then
        echo -e "${GREEN}✓ Cleaned up $DELETED face file(s)${NC}"
    fi
    # Remove directory if empty
    if [ -z "$(ls -A "$TEMP_DIR" 2>/dev/null)" ]; then
        rmdir "$TEMP_DIR" 2>/dev/null || true
        echo -e "${GREEN}✓ Removed empty temp_faces directory${NC}"
    fi
else
    echo "temp_faces directory not found"
fi

# Free up ports
echo -e ""
echo "Checking ports..."

if ss -tlnp | grep -q ":8000 "; then
    echo -e "${YELLOW}Port 8000 still in use, freeing...${NC}"
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
fi

echo -e ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}All Vibe Alchemist services stopped${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e ""
