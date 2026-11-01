#!/usr/bin/env python3
"""Trader-Status updaten – schreibt letzten Lauf-Zeitpunkt.

Wird von jedem Trader aufgerufen, um seinen letzten Lauf zu protokollieren.
"""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(BASE, "trader_status.json")


def update_status(trader_name, info=None):
    """Trader-Status aktualisieren."""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE) as f:
                status = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            status = {}
    else:
        status = {}

    status[trader_name] = {
        "letzter_lauf": datetime.now().isoformat(),
        "info": info or {}
    }

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def lade_status():
    """Lade aktuellen Trader-Status."""
    if not os.path.exists(STATUS_FILE):
        return {}
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except:
        return {}


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "test"
    info = {}
    if len(sys.argv) > 2:
        try:
            info = json.loads(sys.argv[2])
        except:
            pass
    update_status(name, info)
    print(f"✅ Status für {name} aktualisiert: {datetime.now().isoformat()}")