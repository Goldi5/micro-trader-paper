#!/usr/bin/env python3
"""
Micro-Trader Monitor — stündlicher Status-Check (KEIN Trading, nur Beobachtung).
Prueft:
  - Neue Trades seit letztem Lauf (trades.log / depot_*.json trades)
  - Neue KI-Log-Eintraege (ki_log.json decision)
  - Depot-Audit-PDF: Aenderung (mtime) seit letztem Lauf
  - Dashboard erreichbar? (http://localhost:5300/api/version)
Schreibt Status nach monitor_status_last.json (fuer Delta-Erkennung).
"""
import os, json, datetime, glob, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "monitor_status_last.json")
now = datetime.datetime.now()
DATUM = now.strftime("%Y-%m-%d")

def lade_state():
    if os.path.exists(STATE):
        try: return json.load(open(STATE, encoding="utf-8"))
        except: return {}
    return {}

def trades_heute():
    """Anzahl Trades heute aus allen depot_*.json + spec_depots."""
    n = 0
    for p in glob.glob(os.path.join(BASE, "depot_0*.json")) + glob.glob(os.path.join(BASE, "etf_0*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
            for t in d.get("trades", []):
                if t.get("zeit", "").startswith(DATUM):
                    n += 1
        except: pass
    sdd = os.path.join(BASE, "spec_depots")
    if os.path.isdir(sdd):
        for fn in os.listdir(sdd):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(sdd, fn), encoding="utf-8"))
                    for t in d.get("trades", []):
                        if t.get("zeit", "").startswith(DATUM):
                            n += 1
                except: pass
    return n

def ki_decisions_heute():
    try:
        log = json.load(open(os.path.join(BASE, "ki_log.json"), encoding="utf-8"))
    except: return 0
    return sum(1 for e in log if e.get("typ") == "decision" and e.get("zeit", "").startswith(DATUM))

def dashboard_ok():
    try:
        r = urllib.request.urlopen("http://localhost:5300/api/version", timeout=4)
        return r.status == 200
    except: return False

def audit_pdf_mtime():
    p = os.path.join(BASE, "reports", f"depot-audit_{DATUM}.pdf")
    return os.path.getmtime(p) if os.path.exists(p) else 0

st = lade_state()
trades_n = trades_heute()
ki_n = ki_decisions_heute()
dash = dashboard_ok()
pdf_mt = audit_pdf_mtime()

neu_trades = max(0, trades_n - st.get("trades_heute", 0))
neu_ki = max(0, ki_n - st.get("ki_heute", 0))
pdf_neu = pdf_mt > st.get("audit_pdf_mtime", 0)

# Status speichern
json.dump({"trades_heute": trades_n, "ki_heute": ki_n, "audit_pdf_mtime": pdf_mt,
           "ts": now.isoformat()}, open(STATE, "w", encoding="utf-8"), indent=2)

# Report
lines = [f"📊 Micro-Trader Status {now.strftime('%H:%M')}"]
lines.append(f"Dashboard: {'✅ läuft' if dash else '❌ DOWN'}")
lines.append(f"Trades heute: {trades_n} (neu seit letztem Check: {neu_trades})")
lines.append(f"KI-Entscheidungen heute: {ki_n} (neu: {neu_ki})")
lines.append(f"Depot-Audit-PDF: {'🆕 aktualisiert' if pdf_neu else 'unverändert'}")
if not dash:
    lines.append("⚠️ Dashboard DOWN — bitte Hermes fragen: 'Dashboard wieder starten'")
print("\n".join(lines))
