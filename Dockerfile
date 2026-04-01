# ═══════════════════════════════════════════════════════════════
# VIBE ALCHEMIST V2 - Production Dockerfile
# Multi-stage build for optimized image size
# ═══════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────
# Stage 1: Build Frontend
# ───────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy frontend package files
COPY frontend/package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build

# ───────────────────────────────────────────────────────────────
# Stage 2: Python Backend with Built Frontend
# ───────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.2-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY main.py .
COPY api/ ./api/
COPY core/ ./core/
COPY models/ ./models/
COPY OfflinePlayback/ ./OfflinePlayback/

# Copy built frontend from builder stage
COPY --from=frontend-builder /app/frontend/dist ./static

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash vibeuser \
    && chown -R vibeuser:vibeuser /app

# Create necessary directories
RUN mkdir -p /app/temp_faces /app/logs \
    && chown -R vibeuser:vibeuser /app/temp_faces /app/logs

USER vibeuser

# Expose port (configurable via environment)
EXPOSE ${API_PORT:-8080}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${API_PORT:-8080}/api/cameras || exit 1

# Run the application
CMD ["python", "main.py"]
