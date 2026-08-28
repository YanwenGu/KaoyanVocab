@echo off
rem ============================================================
rem  KaoyanVocab launcher for Windows 11
rem  Double-click to start: checks Python, installs deps,
rem  kills old server on port 8000, starts in background,
rem  then opens the browser.
rem ============================================================
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo [ERROR] PowerShell not found. This script requires Windows 10/11.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-server.ps1"
echo.
pause
