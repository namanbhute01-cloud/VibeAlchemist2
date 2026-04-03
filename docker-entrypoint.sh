#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Docker Entrypoint
# Loads .env file if present, then starts the application
# ═══════════════════════════════════════════════════════════════

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Vibe Alchemist V2 - Container Starting"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Load .env file if it exists in the working directory
if [ -f /app/.env ]; then
    echo "  Loading .env configuration..."
    set -a
    source /app/.env
    set +a
    echo "  .env loaded successfully"
fi

# Ensure required directories exist
mkdir -p /app/temp_faces /app/logs
mkdir -p /app/OfflinePlayback/{kids,youths,adults,seniors}

# Display runtime config
echo ""
echo "  Runtime Configuration:"
echo "    API_HOST:    ${API_HOST:-0.0.0.0}"
echo "    API_PORT:    ${API_PORT:-8000}"
echo "    DEBUG:       ${DEBUG:-false}"
echo "    CAMERA_SOURCES: ${CAMERA_SOURCES:-0}"
echo "    TARGET_HEIGHT:  ${TARGET_HEIGHT:-720}"
echo ""
echo "  Starting application..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Execute the CMD passed to the container
exec "$@"
