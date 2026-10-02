#!/bin/bash
# Simple runner for Telegram Restricted Forward Bot
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 main.py
