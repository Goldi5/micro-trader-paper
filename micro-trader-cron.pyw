"""Micro-Trading Cron-Runner (Hermes no_agent-Job).
Startet die Pipeline als abgetrennten Prozess (überlebt Scheduler-Interrupts)
und endet sofort. Detailliertes Log: ~/projects/micro-trader/cron_pipeline.log

Priorität 0 (Zwei-Ebenen-Cron):
  Aufruf mit --mode engine  → nur lokale Logik (kein LLM)
  Aufruf mit --mode ki      → nur LLM-Läufe
  Ohne Arg                  → full (alles)

Zusätzlich (Phase 1): Sonntags wird ein wöchentlicher KI-Reflexionsbericht
(ki_reflexion.reflexion_wochenbericht) erzeugt → pending_rules.json + Summary.
"""
import subprocess, os, sys, json
from datetime import datetime
BASE = os.path.expanduser("~/projects/micro-trader")
sys.path.insert(0, BASE)  # trader_status etc. liegen im Projektordner

# Mode aus Argument (engine | ki | full)
MODE = "full"
for a in sys.argv[1:]:
    if a in ("--mode", "-m"):
        continue
    if a.lstrip("-") in ("engine", "ki", "full"):
        MODE = a.lstrip("-")

# Pipeline detached starten (eigene Prozessgruppe, überlebt Scheduler-Interrupts)
pipeline = os.path.join(os.path.dirname(os.path.abspath(__file__)), "micro-trader-pipeline.py")
# Hermes-venv Python nutzen (hat yfinance + alle Deps) — FENSTERLOS
# WICHTIG: der venv/Scripts/pythonw.exe ist nur ein uv-SHIM, der intern den
# echten Console-python neu startet -> poppt Fenster. Echtes windowless pythonw
# liegt im uv-base (gleiche home, lädt alle venv-Module):
uv_base = os.path.join(
    os.environ.get("APPDATA", r"C:\Users\goldi\AppData\Roaming"),
    "uv", "python", "cpython-3.11-windows-x86_64-none", "pythonw.exe")
if os.path.exists(uv_base):
    PY = uv_base
else:
    venv_pyw = os.path.join(
        os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
        "hermes", "hermes-agent", "venv", "Scripts", "pythonw.exe")
    if os.path.exists(venv_pyw):
        PY = venv_pyw
    else:
        PY = r"C:\Program Files\Python312\pythonw.exe"
        if not os.path.exists(PY):
            PY = r"C:\Program Files\Python312\python.exe"
            if not os.path.exists(PY):
                PY = sys.executable
env = dict(os.environ)
env["PYTHONPATH"] = ""  # Venv-Kontamination vermeiden
# Wichtig: PYTHONHOME falls gesetzt entfernen (zeigt sonst auf Hermes-venv)
env.pop("PYTHONHOME", None)
# Falls PYTHONPATH vom Scheduler vererbt wurde: komplett löschen
if "PYTHONPATH" in env:
    del env["PYTHONPATH"]
flags = 0
if os.name == "nt":
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
else:
    flags = 0  # POSIX: start_new_session unten
try:
    subprocess.Popen(
        [PY, pipeline, f"--mode", MODE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, cwd=BASE, env=env,
        close_fds=True,
        start_new_session=(os.name != "nt"),
        creationflags=flags,
    )
    # Status für Cron-Lauf selbst
    from trader_status import update_status
    update_status("cron", {"zeit": datetime.now().isoformat(), "mode": MODE})
    try:
        from system_log import log_eintrag
        log_eintrag("cron", f"Cron-Pipeline gestartet (mode={MODE}, detached)", "info")
    except Exception:
        pass
    print(f"Pipeline detached gestartet (mode={MODE})")
except Exception as e:
    print(f"FEHLER beim Pipeline-Start: {e}")
    sys.exit(1)

# ── Phase 1: Wöchentlicher Reflexionsbericht (Sonntag) ──
if datetime.now().weekday() == 6:  # 6 = Sonntag
    try:
        from ki_reflexion import reflexion_wochenbericht
        n, pfad = reflexion_wochenbericht()
        if pfad:
            print(f"Wochenbericht: {n} Regel-Kandidaten → {pfad}")
            try:
                from system_log import log_eintrag
                log_eintrag("reflexion", f"Wochenbericht: {n} Kandidaten", "info")
            except Exception:
                pass
    except Exception as e:
        print(f"Wochenbericht fehlgeschlagen: {e}")

