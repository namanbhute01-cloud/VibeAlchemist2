@echo off
REM Vibe Alchemist - Stop Server (CMD wrapper)
echo ========================================
echo   Vibe Alchemist - Stopping Server
echo ========================================
echo.

cd /d "%~dp0"

if exist "Stop-Server.ps1" (
    powershell -ExecutionPolicy Bypass -File "Stop-Server.ps1"
) else (
    docker compose down
)

echo.
pause
