@echo off
title Stop Telegram Bot
color 0E
cd /d "%~dp0"

echo ======================================================================
echo              STOPPING TELEGRAM BOT PROCESSES
echo ======================================================================
echo.

taskkill /F /FI "WINDOWTITLE eq Telegram Restricted Downloader*" /T >nul 2>&1
taskkill /F /IM python.exe /FI "MODULES eq *main.py*" >nul 2>&1
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' -or $_.CommandLine -like '*start_bot*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

if exist "sessions\restricted_saver_bot.session-journal" (
    del /f /q "sessions\restricted_saver_bot.session-journal" >nul 2>&1
    echo [+] Cleaned up session journal lock.
)

echo.
echo [OK] Done. You can now start the bot again cleanly.
echo.
timeout /t 3 /nobreak >nul 2>&1
exit /b 0
