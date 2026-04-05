# Vibe Alchemist - Windows Start Script
# Usage: .\Start-Server.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Vibe Alchemist - Starting Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running"
    }
} catch {
    Write-Host "ERROR: Docker is not running or not installed." -ForegroundColor Red
    Write-Host "Please install Docker Desktop: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    Write-Host "Then start Docker Desktop and try again." -ForegroundColor Yellow
    exit 1
}

# Check if .env exists
if (-not (Test-Path "$ProjectRoot\.env")) {
    if (Test-Path "$ProjectRoot\.env.example") {
        Write-Host "WARNING: .env not found. Copying from .env.example..." -ForegroundColor Yellow
        Copy-Item "$ProjectRoot\.env.example" "$ProjectRoot\.env"
        Write-Host "Please edit .env with your configuration before proceeding." -ForegroundColor Yellow
        $continue = Read-Host "Continue anyway? (y/n)"
        if ($continue -ne "y") { exit 0 }
    } else {
        Write-Host "ERROR: Neither .env nor .env.example found!" -ForegroundColor Red
        exit 1
    }
}

# Check if docker-compose.yml exists
if (-not (Test-Path "$ProjectRoot\docker-compose.yml")) {
    Write-Host "ERROR: docker-compose.yml not found!" -ForegroundColor Red
    exit 1
}

# Check if container is already running
$running = docker compose ps --format json 2>&1 | ConvertFrom-Json
if ($running -and $running.Count -gt 0) {
    Write-Host "Server is already running." -ForegroundColor Yellow
    Write-Host ""
    $action = Read-Host "Restart? (r) / Stop (s) / Continue (c)"
    switch ($action) {
        "r" {
            Write-Host "Restarting..." -ForegroundColor Cyan
            docker compose restart
        }
        "s" {
            Write-Host "Stopping..." -ForegroundColor Cyan
            docker compose down
            exit 0
        }
        default {
            Write-Host "Server is running at http://localhost:8000" -ForegroundColor Green
            Start-Process "http://localhost:8000"
            exit 0
        }
    }
}

# Build and start
Write-Host ""
Write-Host "Building and starting..." -ForegroundColor Cyan
docker compose up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to start container!" -ForegroundColor Red
    docker compose logs --tail=50
    exit 1
}

# Wait for health check
Write-Host ""
Write-Host "Waiting for server to start..." -ForegroundColor Cyan
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $status = docker inspect --format='{{.State.Health.Status}}' vibe-alchemist-v2 2>&1
        if ($status -eq "healthy") {
            Write-Host ""
            Write-Host "========================================" -ForegroundColor Green
            Write-Host "  Server is running!" -ForegroundColor Green
            Write-Host "  URL: http://localhost:8000" -ForegroundColor Green
            Write-Host "========================================" -ForegroundColor Green
            Write-Host ""
            Write-Host "Opening in browser..." -ForegroundColor Cyan
            Start-Process "http://localhost:8000"
            exit 0
        } elseif ($status -eq "unhealthy") {
            Write-Host "ERROR: Container is unhealthy!" -ForegroundColor Red
            docker compose logs --tail=50
            exit 1
        }
        Write-Host "  Waiting... ($i/30)" -ForegroundColor Gray
    } catch {
        Write-Host "  Waiting... ($i/30)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "WARNING: Server hasn't reached healthy state yet." -ForegroundColor Yellow
Write-Host "It may still be starting up. Check logs:" -ForegroundColor Yellow
Write-Host "  docker compose logs -f" -ForegroundColor Gray
Write-Host ""
Write-Host "Server should be available at: http://localhost:8000" -ForegroundColor Cyan
