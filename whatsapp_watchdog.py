#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WhatsApp-Bridge Watchdog für Micro-Trader.

Prüft alle INTERVAL_MIN Minuten:
  1. Läuft der Bridge (Port 3000 offen)?
  2. Funktioniert das Senden (hermes send --test)?
Wenn nicht: Bridge neu starten + erneut testen.
Bei Internet-Abbruch (Send scheitert an Connect) wird automatisch
erneut versucht (Bridge stirbt oft bei Netz-Reset).

Nutzen:
  python whatsapp_watchdog.py          # Einmal-Check (für Cron alle 15min)
  python whatsapp_watchdog.py --loop   # Dauer-Loop (eigener Hintergrund-Prozess)

Konfig: whatsapp_config.json { "target": "whatsapp:...", "interval_min": 15 }
"""
import sys, os, json, time, socket, subprocess, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "whatsapp_config.json")
HERMES = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
    "hermes", "hermes-agent", "venv", "Scripts", "hermes.exe")
BRIDGE = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
    "hermes", "hermes-agent", "scripts", "whatsapp-bridge", "bridge.js")

PORT = 3000
INTERVAL = 15 * 60  # default 15 min
HERMES_EXE = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
    "hermes", "hermes-agent", "venv", "Scripts", "hermes.exe")
GATEWAY_PY = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
    "hermes", "hermes-agent", "hermes_cli", "main.py")
PY_EXE = r"C:\Program Files\Python312\python.exe"


def lade_config():
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except Exception:
        return {}


def port_offen():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            return s.connect_ex(("127.0.0.1", PORT)) == 0
    except Exception:
        return False


def gateway_laeuft():
    """Prüft ob ein Gateway-Prozess aktiv ist (nicht nur Port 3000)."""
    try:
        out = subprocess.run(["tasklist.exe"], capture_output=True, text=True,
                             timeout=10).stdout
        for line in out.splitlines():
            if "python.exe" in line.lower():
                pid = line.split()[1]
                # CommandLine prüfen geht mit tasklist nicht -> wir prüfen
                # stattdessen den gateway_state.json
                break
    except Exception:
        pass
    # Robust: gateway_state.json auswerten
    try:
        st = json.load(open(os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "gateway_state.json"), encoding="utf-8"))
        return st.get("gateway_state") == "running"
    except Exception:
        return False


def whatsapp_connected():
    """Prüft ob WhatsApp in Gateway wirklich verbunden ist (nicht nur running)."""
    try:
        st = json.load(open(os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "gateway_state.json"), encoding="utf-8"))
        wa = st.get("platforms", {}).get("whatsapp", {})
        return wa.get("state") == "connected"
    except Exception:
        return False


def bridge_starten():
    if not os.path.exists(BRIDGE):
        return False
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        subprocess.Popen(["node", BRIDGE], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, startupinfo=startupinfo)
        return True
    except Exception:
        return False


def gateway_starten():
    """Startet den Hermes Gateway (der managed WhatsApp)."""
    try:
        # Hermes-venv python nutzen (hat alle Deps)
        venv_py = os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "hermes-agent", "venv", "Scripts", "python.exe")
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        if os.path.exists(venv_py):
            subprocess.Popen([venv_py, GATEWAY_PY, "gateway", "run"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
        else:
            subprocess.Popen([HERMES_EXE, "gateway", "run"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
        return True
    except Exception as e:
        log(f"Gateway-Start Fehler: {e}")
        return False


def gateway_neustart():
    """Startet Gateway mit --replace (killt alten Prozess sauber)."""
    try:
        venv_py = os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "hermes-agent", "venv", "Scripts", "python.exe")
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        if os.path.exists(venv_py):
            subprocess.Popen([venv_py, GATEWAY_PY, "gateway", "run", "--replace"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
        else:
            subprocess.Popen([HERMES_EXE, "gateway", "run", "--replace"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
        return True
    except Exception as e:
        log(f"Gateway-Neustart Fehler: {e}")
        return False


def send_test(target, text="🔧 Watchdog-Test"):
    if not os.path.exists(HERMES):
        return False, "hermes.exe fehlt"
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        r = subprocess.run([HERMES, "send", "--to", target,
                            text],
                           capture_output=True, text=True, timeout=30,
                           startupinfo=startupinfo)
        out = (r.stdout + r.stderr).strip()
        ok = r.returncode == 0 and "failed" not in out.lower()
        return ok, out or f"exit {r.returncode}"
    except Exception as e:
        return False, str(e)[:120]


def log(msg):
    ts = datetime.datetime.now().isoformat()
    try:
        d = json.load(open(os.path.join(BASE, "system_log.json"),
                           encoding="utf-8"))
    except Exception:
        d = []
    d.append({"zeit": ts, "quelle": "watchdog", "text": msg})
    json.dump(d[-1000:], open(os.path.join(BASE, "system_log.json"), "w",
               encoding="utf-8"), ensure_ascii=False, indent=2)


def check():
    cfg = lade_config()
    target = cfg.get("target")
    if not target:
        log("Watchdog: kein target in Config")
        return

    status = []

    # 0. Gateway prüfen (managed WhatsApp + Bridge)
    if not gateway_laeuft():
        status.append("Gateway nicht running")
        if gateway_starten():
            status.append("Gateway gestartet (warte auf WhatsApp-Connect)")
            time.sleep(30)  # Gateway braucht Zeit zum Connect
            # Nach Gateway-Start läuft der Bridge meist mit -> erneut prüfen
            if not port_offen():
                bridge_starten()
                time.sleep(8)

    # 0b. WhatsApp wirklich verbunden? (Gateway running aber WA disconnected)
    if gateway_laeuft() and not whatsapp_connected():
        status.append("WhatsApp disconnected")
        status.append("Gateway neustart (WhatsApp reconnect)")
        gateway_neustart()
        time.sleep(30)  # Gateway braucht Zeit zum WhatsApp-Connect
        # Bridge evtl. auch neu
        if not port_offen():
            bridge_starten()
            time.sleep(8)

    # 1. Port prüfen
    if not port_offen():
        status.append("Port 3000 zu")
        if bridge_starten():
            time.sleep(8)  # Bridge braucht Zeit zum Connect
            status.append("Bridge neu gestartet")
            # Gateway neu starten, damit er den Bridge bindet
            if gateway_laeuft():
                status.append("Gateway neustart (Bridge neu)")
                gateway_neustart()
                time.sleep(30)
        else:
            status.append("Bridge-Start FEHLER")
            log(" | ".join(status))
            return

    # 2. Send testen – NUR wenn vorher ein Problem erkannt & repariert wurde.
    #    Bei gesundem System: KEIN Send, kein Test, keine WhatsApp-Nachricht (kein Spam).
    hatte_problem = len(status) > 0
    if hatte_problem:
        ok, msg = send_test(target)
        if not ok:
            status.append(f"Send FEHLER: {msg}")
            # Bei Connect-Fehler ODER resolve-Fehler: Bridge + Gateway neustarten
            if ("connect" in msg.lower() or "refused" in msg.lower()
                    or "resolve" in msg.lower()):
                status.append("Bridge+Gateway Neustart nach Connect/Resolve-Fehler")
                bridge_starten()
                time.sleep(8)
                if gateway_laeuft():
                    gateway_neustart()
                    time.sleep(30)
                ok2, msg2 = send_test(target)
                if ok2:
                    status.append("nach Neustart OK")
                else:
                    status.append(f"immer noch FEHLER: {msg2}")
    # Ergebnis: bei Problemen WhatsApp-Nachricht senden, sonst nur Log
    if hatte_problem:
        meldung = " | ".join(status)
        log("Watchdog: " + meldung)
        try:
            send_test(target, "⚠️ Watchdog: " + meldung)
        except Exception:
            pass
    else:
        log("Watchdog: alles OK (kein Test gesendet)")


def main():
    cfg = lade_config()
    interval = int(cfg.get("interval_min", 15)) * 60
    if "--loop" in sys.argv:
        log("Watchdog-Loop gestartet (Interval %d min)" % (interval // 60))
        while True:
            try:
                check()
            except Exception as e:
                log(f"Watchdog Exception: {e}")
            time.sleep(interval)
    else:
        check()


if __name__ == "__main__":
    main()
