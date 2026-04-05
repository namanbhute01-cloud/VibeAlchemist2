# Vibe Alchemist - Windows Update Script
# Usage: .\Update-Server.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Vibe Alchemist - Update Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if this is a git repo
if (Test-Path "$ProjectRoot\.git") {
    Write-Host "Pulling latest code..." -ForegroundColor Cyan
    git pull
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Git pull failed. Continuing with existing code." -ForegroundColor Yellow
    }
} else {
    Write-Host "Not a git repository. Skipping pull." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Rebuilding and restarting..." -ForegroundColor Cyan
docker compose up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to rebuild!" -ForegroundColor Red
    docker compose logs --tail=50
    exit 1
}

# Wait for health check
Write-Host ""
Write-Host "Waiting for health check..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

$maxAttempts = 30
for ($i = 1; $i -le $maxAttempts; $i++) {
    try {
        $status = docker inspect --format='{{.State.Health.Status}}' vibe-alchemist-v2 2>&1
        if ($status -eq "healthy") {
            Write-Host ""
            Write-Host "========================================" -ForegroundColor Green
            Write-Host "  Update complete! Server is healthy." -ForegroundColor Green
            Write-Host "  URL: http://localhost:8000" -ForegroundColor Green
            Write-Host "========================================" -ForegroundColor Green
            exit 0
        } elseif ($status -eq "unhealthy") {
            Write-Host "ERROR: Container is unhealthy after update!" -ForegroundColor Red
            docker compose logs --tail=50
            exit 1
        }
    } catch {
        # Container might be restarting
    }
    Write-Host "  Waiting... ($i/$maxAttempts)" -ForegroundColor Gray
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "WARNING: Server hasn't reached healthy state yet." -ForegroundColor Yellow
Write-Host "Check logs: docker compose logs -f" -ForegroundColor Gray
