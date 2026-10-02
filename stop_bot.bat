@echo off
title Stop Telegram Bot
color 0E
cd /d "%~dp0"

echo ======================================================================
echo              STOPPING TELEGRAM BOT PROCESSES
echo ======================================================================
echo.

powershell -Command "$procs = Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%main.py%%'\"; if ($procs) { $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host \"[+] Stopped process ID $($_.ProcessId)\" } } else { Write-Host \"[*] No running bot processes found.\" }"

if exist "sessions\restricted_saver_bot.session-journal" (
    del /f /q "sessions\restricted_saver_bot.session-journal" >nul 2>&1
    echo [+] Cleaned up session journal lock.
)

echo.
echo [OK] Done. You can now start the bot again cleanly.
echo.
timeout /t 3 /nobreak >nul 2>&1
exit /b 0
