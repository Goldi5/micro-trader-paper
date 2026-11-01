"""Regressionstest: KI-Aktionen werden nur EINMAL ausgefuehrt.

ANLASS (01.11.2026, Code-Review):
  batch_trader.py cachte KI-Aktionen 1 h und fuehrte sie bei jedem weiteren
  Lauf innerhalb dieser Stunde erneut aus. Im Pipeline-Modus "full" lief
  batch_trader zudem zweimal direkt hintereinander - der zweite Lauf
  wiederholte alle Kaeufe/Verkaeufe des ersten.

batch_trader.main() laesst sich ohne Live-Depots und KI nicht ausfuehren;
der Test prueft deshalb die beiden Stellen im Quelltext (wie
test_menge_floor.py) und die Pipeline-Steuerung per AST.
"""
import ast
import io
import os
import re
import sys

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + detail))
    if not ok:
        FEHLER.append(name)


bt = io.open(os.path.join(HIER, "batch_trader.py"), encoding="utf-8-sig").read()
i = bt.find('if cached and jetzt_ts - cached.get("ts", 0) < KI_CACHE_DAUER:')
pruefe("Cache-Zweig vorhanden", i > 0)
zweig = bt[i:i + 1500]
m = re.search(r'ki_ergebnisse\[risk\]\s*=\s*\(depot,\s*params,\s*\{"aktionen":\s*([^,]+),', zweig)
pruefe("Cache-Zweig uebergibt KEINE Aktionen zur Ausfuehrung",
       bool(m) and m.group(1).strip() == "[]", m.group(1) if m else "nicht gefunden")

pl = io.open(os.path.join(HIER, "micro-trader-pipeline.py"), encoding="utf-8").read()
baum = ast.parse(pl)
aufrufe = [n for n in ast.walk(baum) if isinstance(n, ast.Call)
           and getattr(n.func, "id", "") == "run" and n.args
           and isinstance(n.args[0], ast.Constant) and n.args[0].value == "batch_trader.py"]
pruefe("Pipeline kennt batch_trader-Aufrufe", len(aufrufe) >= 1)
pruefe("Zweiter Aufruf im Modus full ist gegen Doppellauf gesperrt",
       'if mode == "full" and not batch_gelaufen:' in pl and "batch_gelaufen = True" in pl)

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
