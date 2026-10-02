@echo off
chcp 65001 >nul
title RESTRICTED FORWARD BOT STUDIO — Web Cockpit
color 0b
echo ======================================================================
echo    ⚡ RESTRICTED FORWARD BOT STUDIO — WEB DASHBOARD LAUNCHER ⚡
echo ======================================================================
echo.
echo [*] Initializing high-speed local web server...
echo [*] Opening Studio Dashboard at http://127.0.0.1:8888 ...
echo.

python run_studio.py

if errorlevel 1 (
    echo.
    echo [!] Server exited with error. Press any key to close.
    pause >nul
)
