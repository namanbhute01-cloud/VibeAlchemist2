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
    # Safe loading: read key=value pairs without executing shell commands
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        case "$key" in
            \#*|"") continue ;;
        esac
        # Trim whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        if [ -n "$key" ] && [ -n "$value" ]; then
            export "$key=$value"
        fi
    done < /app/.env
    echo "  .env loaded successfully"
fi

# Ensure required directories exist
mkdir -p /app/temp_faces /app/logs /app/models
mkdir -p /app/OfflinePlayback/{kids,youths,adults,seniors}

# Auto-download YOLO11n if not present (first-run only)
if [ ! -f /app/models/yolo11n.pt ] && [ ! -f /app/models/yolo11n.onnx ] && [ ! -f /app/models/yolov8n.pt ] && [ ! -f /app/models/yolov8n.onnx ]; then
    echo ""
    echo "  First run: downloading YOLO11n model..."
    python3 -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" 2>&1 | while read line; do echo "    $line"; done
    echo "  Model downloaded."
fi

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
