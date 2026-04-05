@echo off
REM Vibe Alchemist - Start Server (CMD wrapper)
REM Double-click this file to start the server

echo ========================================
echo   Vibe Alchemist - Starting Server
echo ========================================
echo.

cd /d "%~dp0"

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not running or not installed.
    echo Please install Docker Desktop: https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

REM Start the server using PowerShell script
if exist "Start-Server.ps1" (
    powershell -ExecutionPolicy Bypass -File "Start-Server.ps1"
) else (
    echo Building and starting...
    docker compose up -d --build
    echo.
    echo Server should be available at: http://localhost:8000
)

echo.
pause
