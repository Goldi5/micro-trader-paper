#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WhatsApp-Bericht für Micro-Trader via Hermes Gateway (hermes send).

Nutzt die bereits eingerichtete Hermes-WhatsApp-Anbindung (config.yaml:
whatsapp.mode=self-chat). Kein externer API-Key nötig — Hermes sendet
über den Gateway an dein WhatsApp self-chat.

Aufruf:
  python whatsapp_bericht.py [--test]
  --test: sendet nur eine kurze Test-Nachricht

Config: whatsapp_config.json { "target": "whatsapp:Christian Glaser (dm)" }
  (Ziel aus `hermes send --list` kopieren)
"""
import json, os, sys, datetime, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "whatsapp_config.json")
HERMES = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
    "hermes", "hermes-agent", "venv", "Scripts", "hermes.exe")

def lade_config():
    if not os.path.exists(CONFIG):
        return {}
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except Exception:
        return {}

def sende(target, text):
    """Sendet via `hermes send`. Return: (ok, msg)."""
    if not os.path.exists(HERMES):
        return False, f"hermes.exe nicht gefunden: {HERMES}"
    try:
        r = subprocess.run(
            [HERMES, "send", "--to", target, text],
            capture_output=True, text=True, timeout=30,
        )
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0 and "failed" not in out.lower():
            return True, out or "OK"
        return False, out or f"exit {r.returncode}"
    except Exception as e:
        return False, str(e)[:120]

def status_sammeln():
    """Sammelt den Tagesstatus aus dem Projekt."""
    heute = datetime.datetime.now().strftime("%Y-%m-%d")
    zeilen = []
    try:
        import glob
        trades_aktien = trades_etf = trades_spec = 0
        for f in glob.glob(os.path.join(BASE, "depot_*.json")):
            d = json.load(open(f, encoding="utf-8"))
            for t in d.get("trades", []):
                if str(t.get("zeit", "")).startswith(heute):
                    trades_aktien += 1
        for f in glob.glob(os.path.join(BASE, "etf_*.json")):
            d = json.load(open(f, encoding="utf-8"))
            for t in d.get("trades", []):
                if str(t.get("zeit", "")).startswith(heute):
                    trades_etf += 1
        for f in glob.glob(os.path.join(BASE, "spec_depots", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            for t in d.get("trades", []):
                if str(t.get("zeit", "")).startswith(heute):
                    trades_spec += 1
        zeilen.append(f"📊 Trades heute: Aktien {trades_aktien} | ETF {trades_etf} | Spec {trades_spec}")
    except Exception as e:
        zeilen.append(f"⚠️ Trades-Scan Fehler: {e}")

    try:
        import glob
        spec_start = spec_wert = 0
        for f in glob.glob(os.path.join(BASE, "spec_depots", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            if not (d.get("start") or d.get("shares") or d.get("trades")):
                continue
            spec_start += d.get("start", 0) or 0
            spec_wert += d.get("bargeld", 0) + (d.get("shares", 0) or 0) * (d.get("avg_price", 0) or 0)
        if spec_start:
            r = (spec_wert / spec_start - 1) * 100
            zeilen.append(f"🔥 Spec: {spec_wert:.0f}$ ({r:+.2f}%)")
    except Exception as e:
        zeilen.append(f"⚠️ Spec-Scan Fehler: {e}")

    try:
        d = json.load(open(os.path.join(BASE, "system_log.json"), encoding="utf-8"))
        spec = [e for e in d if e.get("quelle") == "spec"]
        if spec:
            zeilen.append(f"🤖 Letzter Spec-Lauf: {spec[-1].get('zeit','')[:16]}")
        else:
            zeilen.append("⚠️ Kein Spec-Lauf geloggt")
        fehler = [e for e in d if "FEHLER" in str(e.get("text", ""))][-3:]
        if fehler:
            zeilen.append(f"🚨 Fehler: {len(fehler)} (letzter: {fehler[-1].get('text','')[:50]})")
        else:
            zeilen.append("✅ Keine Fehler im Log")
    except Exception as e:
        zeilen.append(f"⚠️ Log-Scan: {e}")

    return "\n".join(zeilen)

def main():
    cfg = lade_config()
    target = cfg.get("target")
    if not target:
        print("❌ whatsapp_config.json: 'target' fehlt.")
        print("   Erstelle sie mit: {\"target\": \"whatsapp:Christian Glaser (dm)\"}")
        print("   Ziel aus `hermes send --list` kopieren.")
        sys.exit(1)

    if "--test" in sys.argv:
        ok, msg = sende(target, "✅ Micro-Trader WhatsApp-Test (Hermes Gateway)")
        print(f"Test-Send: {'OK' if ok else 'FEHLER'} | {msg}")
        sys.exit(0)

    bericht = status_sammeln()
    kopf = f"📈 Micro-Trader Bericht ({datetime.datetime.now().strftime('%d.%m %H:%M')})\n"
    text = kopf + bericht
    ok, msg = sende(target, text)
    print(f"Bericht gesendet: {'OK' if ok else 'FEHLER'} | {msg}")
    try:
        log = json.load(open(os.path.join(BASE, "system_log.json"), encoding="utf-8"))
    except Exception:
        log = []
    log.append({"zeit": datetime.datetime.now().isoformat(), "quelle": "whatsapp",
                "text": f"Bericht gesendet: {'OK' if ok else 'FEHLER'}"})
    json.dump(log[-1000:], open(os.path.join(BASE, "system_log.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
