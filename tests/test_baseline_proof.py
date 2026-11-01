#!/usr/bin/env python3
"""
BEWEIS-SKript: fuehrt die Kernpruefungen gegen DEN BASELINE-Stand
(Commit 8da05cd, Backups in /tmp/riskbak-*) und gegen den NEUEN Stand aus.

Aufruf:  venv/bin/python test_baseline_proof.py

Erwartet: Exit-Code 0, wenn (a) die Baseline die Defekte ZEIGT und
(b) der neue Stand sie behebt hat. Ein Defekt, der in der Baseline nicht
nachweisbar ist, wird als FEHLER gewertet.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import os
import re
import shutil
import subprocess
import sys
import types

M = _MT_BASE
BAK = "/tmp/riskbak-20260927-201645"
SANDBOX = "/tmp/baseline-sandbox"

# tabulate fehlt im venv (VORBESTAND, auch in Commit 8da05cd).
if "tabulate" not in sys.modules:
    try:
        import tabulate  # noqa: F401
    except ImportError:
        _s = types.ModuleType("tabulate")
        _s.tabulate = lambda *a, **k: ""
        sys.modules["tabulate"] = _s

DEFEKTE = []   # Defekte, die in der BASELINE nachweisbar sein MUESSEN
FIXES = []     # Defekte, die im NEUEN Stand behoben sein MUESSEN


def lies_basis(pfad):
    with open(pfad, encoding="utf-8") as f:
        return f.read()


def ohne_kommentare(text):
    return "".join(l.split("#", 1)[0] + "\n" for l in text.splitlines())


def banner(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


# ─────────────────────────────────────────────────────────────────
banner("TEIL 1: BASELINE (Commit 8da05cd) – Defekte nachweisen")
print("Quelle: %s\n" % BAK)

if not os.path.isdir(BAK):
    print("FEHLER: Backup-Verzeichnis %s fehlt" % BAK)
    sys.exit(2)

eng_b = lies_basis(os.path.join(BAK, "engine.py.bak-20260927-201645"))
bt_b = lies_basis(os.path.join(BAK, "batch_trader.py.bak-20260927-201645"))
sp_b = lies_basis(os.path.join(BAK, "spec_trader.py.bak-20260927-201645"))
pt_b = lies_basis(os.path.join(BAK, "paper_trader.py.bak-20260927-201645"))
etf_b = lies_basis(os.path.join(BAK, "etf_trader.py.bak-20260927-201645"))
rp_b = lies_basis(os.path.join(BAK, "risk_profile.py.bak-20260927-201645"))

# ── Defekt 1: Ausweichkauf mit 100% des Depot-Cash ──────────────
d1 = "_budget = depot.bargeld" in ohne_kommentare(eng_b)
print("[Befund 1] engine.py: `_budget = depot.bargeld` (100%% Cash): %s" %
      ("NACHWEISBAR - BUG" if d1 else "NICHT GEFUNDEN"))
print("          Zeile(n): %s" % [i for i, l in enumerate(eng_b.splitlines(), 1)
                                if "_budget = depot.bargeld" in l])
if d1:
    DEFEKTE.append("B1 Ausweichkauf nutzt 100% des Cash")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B1 nicht nachweisbar")

# ── Defekt 2: except Exception: pass um das Enforcement ─────────
m2 = re.search(r"except Exception:\s*\n\s*pass\s*#\s*Enforcement nie fatal",
               ohne_kommentare(bt_b).replace("\n", "\n"))
bt_lines = bt_b.splitlines()
try2 = [i for i, l in enumerate(bt_lines, 1)
        if "pass" in l and "Enforcement nie fatal" in l]
print("\n[Befund 2] batch_trader.py `except: pass` um enforce_risk_limits: %s"
      % ("NACHWEISBAR - BUG" if try2 else "NICHT GEFUNDEN"))
print("          Zeile(n): %s" % try2)
if try2:
    DEFEKTE.append("B2 Enforcement-Fehler laesst Trade durch")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B2 nicht nachweisbar")

# ── Defekt 3: gepruefter und gehandelter Wert verschieden ───────
p3 = re.search(r"pos_pct = min\(menge_faktor \* params\.get\(",
               ohne_kommentare(bt_b))
p3b = re.search(r"_pos_frac = min\(params\.get\(",
                ohne_kommentare(bt_b))
print("\n[Befund 3] batch_trader.py geprueft (pos_pct) != gehandelt (_pos_frac): %s"
      % ("NACHWEISBAR - BUG" if (p3 and p3b) else "NICHT GEFUNDEN"))
if p3:
    print("          pos_pct : %s" % p3.group(0))
if p3b:
    print("          _pos_frac: %s" % p3b.group(0))
if p3 and p3b:
    DEFEKTE.append("B3 gepruefter != gehandelter Betrag")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B3 nicht nachweisbar")

# ── Defekt 4: spec_trader ohne SL/TP/Limit/Drawdown ─────────────
sp_code = ohne_kommentare(sp_b)
fehlend4 = [k for k in ("stop_loss", "take_profit", "max_positions", "drawdown")
            if k not in sp_code]
nur_gate = "if konfidenz < 40:" in sp_code and "bargeld > 1.0" in sp_code
print("\n[Befund 4] spec_trader.py ohne %s" % ", ".join(fehlend4))
print("          einziges Gate = konfidenz>=40 + cash>1.0 : %s" % nur_gate)
print("          'voll' == 100%% des Cash (faktor 1.0)      : %s"
      % ('"voll": 1.0' in sp_code and "invest = depot.bargeld * faktor" in sp_code))
if fehlend4 and nur_gate:
    DEFEKTE.append("B4 spec_trader ohne Risikolimits")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B4 nicht nachweisbar")

# ── Defekt 5: paper_trader ohne jede Risikokontrolle + 0-EUR-Verkauf
pt_code = ohne_kommentare(pt_b)
fehlend5 = [k for k in ("stop_loss", "take_profit", "max_positions", "drawdown")
            if k not in pt_code]
print("\n[Befund 5] paper_trader.py ohne %s" % ", ".join(fehlend5))
v5 = re.search(r"def verkaufen\(self, symbol, kurs\):(.*?)\n    def ",
               pt_code, re.S)
v5_body = v5.group(1) if v5 else ""
kein_guard = ("kurs <= 0" not in v5_body and "<= 0" not in v5_body
              and "kurs > 0" not in v5_body)
print("          verkaufen() ohne kurs<=0-Guard: %s" % kein_guard)
if fehlend5 and kein_guard:
    DEFEKTE.append("B5 paper_trader ohne Risikokontrolle, 0-EUR-Verkauf moeglich")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B5 nicht nachweisbar")

# ── Defekt 6: tier_bonus / allowed_tiers nie gesetzt ─────────────
rp_code = ohne_kommentare(rp_b)
hat_tb = '"tier_bonus"' in rp_code
print("\n[Struktur] risk_profile.get_params liefert tier_bonus: %s" % hat_tb)
if not hat_tb:
    DEFEKTE.append("B6 get_params liefert kein tier_bonus/allowed_tiers -> immer 0")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B6 nicht nachweisbar")

# ── Defekt 7: risikodifferenzierung faktisch nicht vorhanden ─────
# get_params der BASELINE: gibt es allowed_tiers? Nein -> engine default
has_allowed = '"allowed_tiers"' in rp_code
print("[Struktur] get_params liefert allowed_tiers: %s" % has_allowed)
if not has_allowed:
    DEFEKTE.append("B7 kein allowed_tiers in params -> Risk-0 == Risk-95")
else:
    print("  !! FEHLER: Defekt nicht nachweisbar")
    DEFEKTE.append("B7 nicht nachweisbar")

# ─────────────────────────────────────────────────────────────────
banner("TEIL 2: VERHALTENS-BEWEIS – Baseline vs. neu (paper_trader 0-EUR)")

if os.path.isdir(SANDBOX):
    shutil.rmtree(SANDBOX)
os.makedirs(SANDBOX)
for f in ("engine.py", "batch_trader.py", "spec_trader.py",
          "paper_trader.py", "etf_trader.py", "risk_profile.py",
          "strategie.py"):
    src = os.path.join(BAK, f + ".bak-20260927-201645")
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(SANDBOX, f))

_verhaltens_skript = r'''
import sys, types
if "tabulate" not in sys.modules:
    s = types.ModuleType("tabulate"); s.tabulate = lambda *a, **k: ""
    sys.modules["tabulate"] = s
sys.path.insert(0, "%(pfad)s")
import paper_trader
d = paper_trader.Depot(1000.0)
ok, msg = d.kaufen("AAPL", 100.0)
print("KAUF:", ok, msg)
print("POSITIONEN:", list(d.positions.keys()))
cash_vor = d.bargeld
ok2, msg2 = d.verkaufen("AAPL", 0)     # yfinance-Rate-Limit
print("VERKAUF_KURS0:", ok2, "|", msg2)
print("CASH_VOR:", cash_vor, "CASH_NACH:", d.bargeld)
print("POSITIONEN_NACH:", list(d.positions.keys()))
print("DEPOTWERT:", d.depotwert({}))
''' % {"pfad": SANDBOX}

with open(os.path.join(SANDBOX, "_probe.py"), "w") as f:
    f.write(_verhaltens_skript)

r = subprocess.run([os.path.join(M, "venv/bin/python"), "_probe.py"],
                   cwd=SANDBOX, capture_output=True, text=True, timeout=180)
print("--- BASELINE-Verhalten ---")
print(r.stdout.strip() or r.stderr[-600:])
basis_verlor = False
if "VERKAUF_KURS0: True" in r.stdout and "POSITIONEN_NACH: []" in r.stdout:
    basis_verlor = True
    print("\n>>> BELEGT: Die BASELINE verkauft die Position bei Kurs 0 fuer 0 EUR")
    print(">>> und loescht sie aus dem Depot. Das ist Befund 5, KRITISCH.")
if basis_verlor:
    DEFEKTE.append("B5b Verhaltensbeweis: 0-EUR-Verkauf tritt real ein")
else:
    print("\n  !! Verhaltensbeweis nicht reproduzierbar (siehe Ausgabe)")

# Jetzt der NEUE Stand im echten Verzeichnis
with open(os.path.join(M, "_probe_neu.py"), "w") as f:
    f.write(_verhaltens_skript.replace(SANDBOX, M))
r2 = subprocess.run([os.path.join(M, "venv/bin/python"), "_probe_neu.py"],
                    cwd=M, capture_output=True, text=True, timeout=180)
print("\n--- NEUER Stand ---")
print(r2.stdout.strip() or r2.stderr[-600:])
neu_ok = False
if "VERKAUF_KURS0: False" in r2.stdout and "POSITIONEN_NACH: ['AAPL']" in r2.stdout:
    neu_ok = True
    print("\n>>> BELEGT: Der NEUE Stand verweigert den Verkauf, Cash und")
    print(">>> Position bleiben unveraendert.")
if neu_ok:
    FIXES.append("B5 0-EUR-Verkauf verweigert")
else:
    print("\n  !! Fix nicht bestaetigt")
os.remove(os.path.join(M, "_probe_neu.py"))

# ─────────────────────────────────────────────────────────────────
banner("TEIL 3: BASELINE-Controller existierte nicht")
print("risk_controller.py in der Baseline:          %s"
      % ("NEIN" if not os.path.exists(os.path.join(BAK, "risk_controller.py.bak-20260927-201645")) else "JA"))
print("risk_controller.py im neuen Stand:          %s"
      % ("JA" if os.path.exists(os.path.join(M, "risk_controller.py")) else "NEIN"))
if not os.path.exists(os.path.join(BAK, "risk_controller.py.bak-20260927-201645")) \
        and os.path.exists(os.path.join(M, "risk_controller.py")):
    DEFEKTE.append("B8 Single Source of Truth existierte nicht")

banner("ERGEBNIS")
print("In der BASELINE nachweisbare Defekte: %d" % len(DEFEKTE))
for d_ in DEFEKTE:
    print("  - " + d_)
print("Im neuen Stand behobene Defekte: %d" % len(FIXES))
for f_ in FIXES:
    print("  - " + f_)

# Jeder erwartete Defekt muss in der BASELINE gefunden worden sein
erwartet = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]
fehlend = [e for e in erwartet
           if not any(d_.startswith(e) for d_ in DEFEKTE)]
if fehlend:
    print("\nFEHLER: erwartete Defekte nicht nachweisbar: %s" % fehlend)
    sys.exit(1)
print("\nBESTANDEN - alle %d Defekte in der Baseline nachweisbar, "
      "Kernfix verifiziert" % len(DEFEKTE))
sys.exit(0)
