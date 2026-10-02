@echo off
title Telegram Account Connector - 100%% Permanent Login
cd /d "%~dp0"
echo ================================================================
echo      TELEGRAM ACCOUNT 1-CLICK PERMANENT CONNECTOR
echo ================================================================
echo.
python generate_session.py
echo.
echo Press any key to close this window...
pause >nul
