#!/usr/bin/env python3
"""System-Log – zentrale Klartext-Ereignisliste fürs Dashboard.

Jeder Trader/Cron/Lernmodul schreibt hier kurze Ereignisse rein
(z.B. 'Batch-Lauf: 20 Depots, +2.55%'). Das Dashboard zeigt sie
chronologisch im Tab '📋 Log'.

Format pro Eintrag:
{
  "zeit": "2026-07-31T10:08:41.123",
  "quelle": "cron" | "batch" | "spec" | "etf" | "ki_learning" | "ki_decisions" | "system",
  "level": "info" | "ok" | "warn" | "error",
  "text": "Klartext-Nachricht"
}
"""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE, "system_log.json")
MAX_EINTRAEGE = 500


def log_eintrag(quelle, text, level="info"):
    """Schreibt einen Log-Eintrag (append, max. MAX_EINTRAEGE)."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                log = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            log = []
    else:
        log = []
    if not isinstance(log, list):
        log = []
    log.append({
        "zeit": datetime.now().isoformat(),
        "quelle": quelle,
        "level": level,
        "text": text,
    })
    if len(log) > MAX_EINTRAEGE:
        log = log[-MAX_EINTRAEGE:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def lade_log(anzahl=200):
    """Lädt die letzten N Einträge (neueste zuerst)."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []
    if not isinstance(log, list):
        return []
    return log[-anzahl:][::-1]  # neueste zuerst


if __name__ == "__main__":
    quelle = sys.argv[1] if len(sys.argv) > 1 else "test"
    text = sys.argv[2] if len(sys.argv) > 2 else "Test-Eintrag"
    level = sys.argv[3] if len(sys.argv) > 3 else "info"
    log_eintrag(quelle, text, level)
    print(f"✅ Log-Eintrag geschrieben: [{level}] {quelle}: {text}")
    print(f"   ({len(lade_log())} Einträge gesamt)")
