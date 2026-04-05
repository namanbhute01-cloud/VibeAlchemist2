# Vibe Alchemist - Windows Stop Script
# Usage: .\Stop-Server.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Vibe Alchemist - Stopping Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if container is running
$running = docker compose ps --format json 2>&1
if (-not $running -or $running.Trim() -eq "[]") {
    Write-Host "No running containers found." -ForegroundColor Yellow
    exit 0
}

Write-Host "Stopping containers..." -ForegroundColor Cyan
docker compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Server stopped." -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "ERROR: Failed to stop server!" -ForegroundColor Red
    exit 1
}
