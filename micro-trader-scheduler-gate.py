"""Micro-Trader Master-Scheduler (markt-gesteuert).

Laeuft alle 5min (Cron). Prueft ueber boersen.py, ob die relevanten
Boersen offen sind (±15min Puffer). Startet Tasks NUR wenn Markt aktiv.

Börsen (aus boersen.py BOERSEN):
  US    → NYSE/NASDAQ (09:30–16:00 ET)
  XETRA → 09:00–17:30 Berlin
  (Watchlist ist 100% US → US ist Haupt-Börse)

Tasks:
  - pipeline   (Trading+KI)  → nur wenn US offen ±15min
  - ki_lauf    (KI nur)      → nur wenn US offen ±15min
  - depot_audit(DB-Check)    → nur wenn US offen (sinnvoll)
  - monitor    (Status)      → immer (kein Risiko), aber nur Meldung wenn offen
  - watcher    (A-I Check)   → immer (Überwachung)

Jeder Task ist ein Hermes-Cron (der via micro-trader-cron.pyw startet).
Dieses Script ist der GATE-Keeper: es entscheidet, OB gestartet wird.
"""
import subprocess, os, sys, json
from datetime import datetime, timedelta

BASE = os.path.expanduser("~/projects/micro-trader")
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import boersen

# Puffer: 15min vor/open, 15min nach close
PUFFER = timedelta(minutes=15)

def markt_aktiv(boerse="US", jetzt=None):
    """True wenn Börse offen oder innerhalb 15min Puffer vor/nach Öffnung."""
    jetzt = jetzt or datetime.now()
    # Ist offen?
    if boersen.ist_offen(boerse, jetzt):
        return True
    # 15min vor Öffnung?
    try:
        na = boersen.next_open(boerse, jetzt)
        if na and (na - jetzt) <= PUFFER and (na - jetzt) >= timedelta(0):
            return True
    except Exception:
        pass
    # 15min nach Schluss?
    try:
        # letztes close war vor <15min?
        # boersen.status_mit_next_open liefert Info
        status = boersen.status_mit_next_open(boerse, jetzt)
        if isinstance(status, dict):
            zu = status.get("zu")
            if zu and (jetzt - zu) <= PUFFER:
                return True
    except Exception:
        pass
    return False

def pipeline_starten(mode="full"):
    """Startet Pipeline detached (wie micro-trader-cron.pyw), aber nur wenn Gate ok."""
    if not markt_aktiv("US"):
        print(f"[{datetime.now():%H:%M}] GATE: US geschlossen -> Pipeline ({mode}) NICHT gestartet")
        return False
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "micro-trader-pipeline.py")
    uv_base = os.path.join(os.environ.get("APPDATA", ""), "uv", "python", "cpython-3.11-windows-x86_64-none", "pythonw.exe")
    PY = uv_base if os.path.exists(uv_base) else sys.executable
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = ""
    try:
        subprocess.Popen([PY, script, "--mode", mode],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, cwd=BASE, env=env,
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
        print(f"[{datetime.now():%H:%M}] GATE: US offen -> Pipeline ({mode}) gestartet")
        return True
    except Exception as e:
        print(f"[{datetime.now():%H:%M}] Pipeline-Start Fehler: {e}")
        return False

# 01.11.2026: depot_audit_starten() stand HINTER dem __main__-Block und war
# beim Aufruf noch nicht definiert (NameError nach jedem Pipeline-Start).
def depot_audit_starten():
    """Startet Depot-Audit (DB-Check) wenn Markt offen."""
    script = os.path.join(BASE, "depot_audit.py")
    if not os.path.exists(script):
        return
    uv_base = os.path.join(os.environ.get("APPDATA", ""), "uv", "python", "cpython-3.11-windows-x86_64-none", "pythonw.exe")
    PY = uv_base if os.path.exists(uv_base) else sys.executable
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = ""
    try:
        subprocess.Popen([PY, script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, cwd=BASE, env=env,
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
        print(f"[{datetime.now():%H:%M}] Depot-Audit gestartet")
    except Exception as e:
        print(f"[{datetime.now():%H:%M}] Depot-Audit Fehler: {e}")


if __name__ == "__main__":
    jetzt = datetime.now()
    us_aktiv = markt_aktiv("US", jetzt)
    print(f"[{jetzt:%H:%M}] Markt-Check US: {'AKTIV' if us_aktiv else 'GESCHLOSSEN'} | {boersen.status_text()}")
    if us_aktiv:
        pipeline_starten("full")
        # Depot-Audit nur wenn Markt offen (sinnvoll)
        depot_audit_starten()
    else:
        print(f"[{jetzt:%H:%M}] Keine Trading-Tasks (Börse zu). Monitor/Watcher laufen separat.")
