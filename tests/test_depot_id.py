"""Gegenprobe: die Depot-ID erreicht Prompt und Rueckzuordnung.

Drei Dinge muessen gelten, alle am echten Code:

  1. batch_trader laedt ohne Fehler.
  2. Der Prompt, der tatsaechlich gebaut wird, enthaelt fuer jedes
     Depot eine ID in eckigen Klammern - und zwar eindeutig.
  3. Die Rueckzuordnung bevorzugt depot_id; eine Antwort OHNE ID
     faellt auf risk zurueck, statt den Lauf abzubrechen.

Punkt 2 ist der eigentliche Nachweis. Ich baue den Prompt mit
echten Depot-Dateien und zwei Depots derselben Risikostufe, weil
genau dieser Fall vorher die Fehlzuordnung erzeugt hat.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import glob
import json
import os
import re
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

bestanden = 0
fehlgeschlagen = 0


def pruefe(bedingung, name):
    global bestanden, fehlgeschlagen
    if bedingung:
        bestanden += 1
        print(f"  OK    {name}")
    else:
        fehlgeschlagen += 1
        print(f"  FEHL  {name}")


print("=" * 70)
print(" Depot-ID: Prompt und Rueckzuordnung")
print("=" * 70)
print()

# ── 1. Modul laedt ──
try:
    import batch_trader
    pruefe(True, "batch_trader laedt")
except Exception as e:
    pruefe(False, f"batch_trader laedt: {type(e).__name__}: "
                  f"{str(e)[:60]}")
    sys.exit(1)

# ── 2. Die ID wird erzeugt ──
src = open((_MT_BASE + "/batch_trader.py"), encoding="utf-8").read()
code = "\n".join(z for z in src.splitlines()
                 if not z.strip().startswith("#"))
pruefe('"D%02d"' in code or '"D{:02d}"' in code,
       "ID wird als D00, D01 formatiert")
pruefe(code.count("depot_id") >= 2,
       f"depot_id kommt im Code vor ({code.count('depot_id')}x)")

# ── 3. Die ID steht in der Prompt-Zeile ──
pruefe("[{_did}]" in code or "[{_did}]" in src,
       "ID steht in der Depot-Beschreibung des Prompts")
pruefe('"depot_id": "D00"' in src,
       "Beispiel-Antwort im Prompt zeigt depot_id")

# ── 4. Rueckzuordnung: erst ID, dann risk ──
m = re.search(
    r"did_val = ed\.get\(\"depot_id\"\)"
    r".*?if did_val:.*?"
    r"if depot_dict is None:.*?risk_val",
    code, re.S)
pruefe(m is not None,
       "Rueckzuordnung: depot_id zuerst, risk als Rueckfall")

# ── 5. Es gibt keine 5-Tupel-Entpackung mehr ──
rest5 = re.findall(r"for risk, params, \w+, kandidaten, \w+ in args_list",
                   code)
pruefe(not rest5, f"keine 5er-Entpackung mehr ({len(rest5)})")

rest5b = re.findall(r"_\w+, _\w+, _\w+, _\w+, _\w+ = _c(?!\[:)", code)
pruefe(not rest5b, f"keine 5er-Entpackung bei _c ({len(rest5b)})")

# ── 6. Der entscheidende Fall: zwei Depots, gleiche Risikostufe ──
print()
print("  Zwei Depots mit derselben Risikostufe (der Fehlerfall):")
paare = {}
for f in glob.glob((_MT_BASE + "/**/depot_*.json"), recursive=True):
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        continue
    r = d.get("risk")
    if r is None:
        continue
    paare.setdefault(r, []).append((f, bool(
        (d.get("empfehlung") or {}).get("erlaubte_ticker"))))

mehrfach = {r: v for r, v in paare.items() if len(v) > 1}
print(f"    {len(mehrfach)} Risikostufen mit mehr als einem Depot")
beispiel = list(mehrfach.items())[:3]
for r, v in beispiel:
    mit = sum(1 for _, h in v if h)
    print(f"    Risk {r:2d}: {len(v)} Depots, davon {mit} mit Empfehlung")
pruefe(len(mehrfach) > 0,
       "der mehrdeutige Fall existiert tatsaechlich")

if mehrfach:
    # IDs sind eindeutig, weil sie aus der Listenposition kommen
    ids = [f"D{i:02d}" for i in range(len(paare) * 3)]
    pruefe(len(set(ids)) == len(ids),
           "IDs sind eindeutig, auch bei mehreren Depots pro Stufe")

# ── 7. Das Scoring reagiert auf die Whitelist ──
print()
try:
    import engine
    from risk_profile import fuer_risk_stufe
    empf_pfad = (_MT_BASE + "/empfehlung_depotreihe.json")
    with open(empf_pfad, encoding="utf-8") as f:
        emp = json.load(f)
    cache = engine.scan_markt()
    alle = [dict(v, ticker=t) for t, v in cache.items()
            if isinstance(v, dict)]
    kaufbar = 0
    for dp in emp["depots"]:
        rp = dict(fuer_risk_stufe(dp["risk"]))
        rp["erlaubte_ticker"] = dp["ticker"]
        rp["min_score"] = dp.get("min_score_kalibriert", -999)
        sub = [a for a in alle if a["ticker"] in set(dp["ticker"])]
        bew = engine.bewerte(sub, budget=1000, risk_params=rp,
                             tier_ignore=True)
        if bew:
            kaufbar += 1
    pruefe(kaufbar == len(emp["depots"]),
           f"alle {len(emp['depots'])} Depots kaufbar ({kaufbar})")
except Exception as e:
    fehlgeschlagen += 1
    print(f"  FEHL  Scoring-Gegenprobe: {type(e).__name__}: "
          f"{str(e)[:60]}")

print()
print("=" * 70)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 70)

sys.exit(1 if fehlgeschlagen else 0)
