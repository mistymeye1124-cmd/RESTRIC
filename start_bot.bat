@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Telegram Restricted Downloader ^& Business Bot
color 0A
cd /d "%~dp0"

echo ======================================================================
echo           TELEGRAM RESTRICTED DOWNLOADER ^& BUSINESS BOT
echo ======================================================================
echo.

:: Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [X] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: Kill any existing orphaned main.py processes to avoid session conflicts
powershell -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%main.py%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: Remove stale lock files if any
if exist "sessions\restricted_saver_bot.session-journal" (
    del /f /q "sessions\restricted_saver_bot.session-journal" >nul 2>&1
)

echo [*] Starting 24/7 Bot Supervisor Engine...
echo [*] Press Ctrl+C anytime to stop the bot completely.
echo.

:bot_loop
echo [%date% %time%] 🚀 Launching Telegram Bot Engine...
python -u main.py
set EXITCODE=%errorlevel%

echo.
echo ======================================================================
echo [!] Bot process stopped (Exit Code: %EXITCODE%).
echo [*] Cleaning stale locks for clean recovery...
if exist "sessions\restricted_saver_bot.session-journal" (
    del /f /q "sessions\restricted_saver_bot.session-journal" >nul 2>&1
)
echo [*] Auto-Restarting Bot in 3 seconds... (Press Ctrl+C to abort)
echo ======================================================================
timeout /t 3 /nobreak >nul
goto bot_loop
