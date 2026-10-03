#!/bin/bash
# Simple runner for Telegram Restricted Forward Bot with Auto BBR Optimization
if command -v sysctl >/dev/null 2>&1; then
    sudo sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
    sudo sysctl -w net.core.rmem_max=16777216 >/dev/null 2>&1 || true
    sudo sysctl -w net.core.wmem_max=16777216 >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216" >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216" >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_fastopen=3 >/dev/null 2>&1 || true
fi
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 main.py
