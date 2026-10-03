@echo off
title Push Sessions & DB to VPS - Restricted Bot
color 0b
echo ========================================================
echo   Push Logged-in Accounts to Linux VPS
echo ========================================================
python sync_to_vps.py
pause
