#!/bin/bash
# Sammelt Systemmetriken von CT 300 (read-only)
echo "=== UPTIME ==="
uptime
echo "=== MEM ==="
free -m | head -2
echo "=== DISK ==="
df -h / /opt 2>/dev/null | head -4
echo "=== LOAD ==="
cat /proc/loadavg
echo "=== SERVICES ==="
systemctl is-active micro-trader.service 2>/dev/null || echo "micro-trader: unknown"
systemctl is-active cron 2>/dev/null || true
echo "=== PROC ==="
ps -eo pid,pcpu,pmem,comm --sort=-pcpu 2>/dev/null | head -6
