#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Stop Script
# Stops all running services
# ═══════════════════════════════════════════════════════════════

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e ""
echo -e "${YELLOW}Stopping Vibe Alchemist V2 services...${NC}"
echo -e ""

# Find and kill backend processes
BACKEND_PIDS=$(pgrep -f "python.*main.py" 2>/dev/null || true)
if [ -n "$BACKEND_PIDS" ]; then
    echo -e "${YELLOW}Stopping backend processes:${NC} $BACKEND_PIDS"
    kill $BACKEND_PIDS 2>/dev/null || true
    echo -e "${GREEN}✓ Backend stopped${NC}"
else
    echo "No backend processes found"
fi

# Find and kill frontend processes
FRONTEND_PIDS=$(pgrep -f "vite.*5173" 2>/dev/null || true)
if [ -n "$FRONTEND_PIDS" ]; then
    echo -e "${YELLOW}Stopping frontend processes:${NC} $FRONTEND_PIDS"
    kill $FRONTEND_PIDS 2>/dev/null || true
    echo -e "${GREEN}✓ Frontend stopped${NC}"
else
    echo "No frontend processes found"
fi

# Free up ports
echo -e ""
echo "Checking ports..."

if ss -tlnp | grep -q ":8080 "; then
    echo -e "${YELLOW}Port 8080 still in use, freeing...${NC}"
    lsof -ti:8080 | xargs kill -9 2>/dev/null || true
fi

if ss -tlnp | grep -q ":5173 "; then
    echo -e "${YELLOW}Port 5173 still in use, freeing...${NC}"
    lsof -ti:5173 | xargs kill -9 2>/dev/null || true
fi

echo -e ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}All Vibe Alchemist services stopped${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e ""
