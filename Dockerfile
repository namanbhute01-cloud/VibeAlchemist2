# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Production Dockerfile
# Multi-stage build: Node frontend → Python backend
# ═══════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────
# Stage 1: Build Frontend
# ───────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy package files first (layer caching)
COPY frontend/package*.json ./

# Install all dependencies (including dev for build)
RUN npm ci

# Copy source and build
COPY frontend/ ./
RUN npm run build

# ───────────────────────────────────────────────────────────────
# Stage 2: Python Backend + Built Frontend
# ───────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Build-time arguments
ARG BUILD_DATE
ARG COMMIT_SHA

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    # Default app config (overridden by .env at runtime)
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DEBUG=false

WORKDIR /app

# Install system dependencies (OpenCV, display libs, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY api/ ./api/
COPY core/ ./core/

# Copy models directory (will be mounted as volume in production)
COPY models/ ./models/
RUN mkdir -p /app/models

# Copy built frontend from builder stage
COPY --from=frontend-builder /app/frontend/dist ./static

# Create data directories
RUN mkdir -p /app/temp_faces /app/logs /app/OfflinePlayback \
    && mkdir -p /app/OfflinePlayback/kids \
    && mkdir -p /app/OfflinePlayback/youths \
    && mkdir -p /app/OfflinePlayback/adults \
    && mkdir -p /app/OfflinePlayback/seniors

# Create non-root user
RUN useradd --create-home --shell /bin/bash vibeuser \
    && chown -R vibeuser:vibeuser /app

USER vibeuser

# Build metadata labels
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.title="Vibe Alchemist V2" \
      org.opencontainers.image.description="AI-powered ambiance system with age detection and adaptive music"

# Expose port (actual port is set via API_PORT env var at runtime)
EXPOSE 8000

# Health check (uses internal container port 8000)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/cameras || exit 1

# Entrypoint: load .env if present, then start app
COPY --chown=vibeuser:vibeuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "main.py"]
