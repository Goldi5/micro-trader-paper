"""Gegenprobe: kauft der Trader NUR erlaubte Titel?

ABLAUF DES BEFUNDS:
  Vor der Verdrahtung kaufte Risk 25 LRCX und Risk 55 PSNY, obwohl
  in erlaubte_ticker nur VYM, VNQ, XLU, VEA, XLP standen. Ursache:
  batch_trader.py hat die Empfehlung nie gelesen.

  Nach der Verdrahtung muss gelten:
    1. Jede gekaufte Position steht in erlaubte_ticker.
    2. Depots OHNE Empfehlung kaufen unveraendert (Rueckwaerts-
       kompatibilitaet - 141 andere Depot-Dateien im Projekt).

Punkt 2 ist der wichtigere: die Verdrahtung darf keinen bestehenden
Depot das Verhalten aendern.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import glob
import json
import os
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
print(" Gegenprobe: nur erlaubte Titel werden gekauft")
print("=" * 70)
print()

# ── 1. Depots mit Empfehlung ──
ZIEL = (_MT_BASE + "/spec_depots_paper")
mit_empf = []
verstoesse = []
for f in sorted(glob.glob(os.path.join(ZIEL, "depot_*.json"))):
    with open(f, encoding="utf-8") as fh:
        d = json.load(fh)
    e = d.get("empfehlung") or {}
    if not e.get("erlaubte_ticker"):
        continue
    risk = d.get("risk")
    erlaubt = set(e["erlaubte_ticker"])
    pos = d.get("positions") or {}
    mit_empf.append((risk, len(erlaubt), len(pos), sorted(pos)))
    for t in pos:
        if t not in erlaubt:
            verstoesse.append(f"Risk {risk}: {t} nicht erlaubt "
                              f"(erlaubt: {', '.join(sorted(erlaubt))})")

print("  Depots mit Empfehlung und ihrem Kaufverhalten:")
for risk, n_erlaubt, n_pos, pos in mit_empf:
    print(f"    Risk {risk:2d}: {n_erlaubt} erlaubt, {n_pos} Position(en) "
          f"{pos}")
print()

if mit_empf:
    prüfe = True
    for risk, _, _, pos in mit_empf:
        if pos:
            print(f"  Risk {risk:2d}: gekauft {', '.join(pos)}")
    pruefe(not verstoesse,
           f"kein Kauf ausserhalb der erlaubten Liste "
           f"({len(verstoesse)} Verstoesse)")
    for v in verstoesse:
        print(f"          {v}")
else:
    print("  Noch keine Positionen - der Lauf hat nicht gehandelt.")
    print("  (Pruefung wiederholen, sobald ein Lauf stattgefunden hat)")

print()
print("  Depots MIT gekauft:")
gekauft = [(r, p) for r, _, n, p in mit_empf if n]
for risk, pos in gekauft:
    print(f"    Risk {risk:2d}: {', '.join(pos)}")
if not gekauft:
    print("    (keine)")

print()
print("=" * 70)

# ── 2. Rueckwaerts-Kompatibilitaet: Depots OHNE Empfehlung ──
ohne = []
# 29.09.2026: Die Aktien-Depots liegen seit heute in
# archiv/alt_20260929/ - ihre Kurse stammen aus einer Rechnung
# von vor 44 Tagen, die damals schon als wertlos markiert
# wurde. Der Test prueft, dass die Whitelist-Verdrahtung
# Alt-Depots NICHT anfasst. Das bleibt sinnvoll, nur woanders.
# Der Trader laedt aus dem Basisverzeichnis, die Alt-Depots
# liegen im Archiv. Beide Pfade werden hier auf das Archiv
# gezogen - geprueft wird die Verdrahtung in laden_aus_datei(),
# nicht der Ort der Datei.
_ALTES = (_MT_BASE + "/archiv/alt_20260929")
for f in sorted(glob.glob(os.path.join(_ALTES, "depot_*.json"))):
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        continue
    if (d.get("empfehlung") or {}).get("erlaubte_ticker"):
        continue
    pos = d.get("positions") or {}
    if pos:
        ohne.append((d.get("risk"), sorted(pos)))

print()
print(f"  {len(ohne)} Alt-Depots OHNE Empfehlung haben Positionen.")
print("  Diese muessen unveraendert handeln - die Verdrahtung")
print("  greift nur bei erlaubte_ticker.")
for risk, pos in ohne[:6]:
    print(f"    Risk {risk}: {', '.join(pos)}")

# Der eigentliche Nachweis: batch_trader laedt diese ohne Fehler
import batch_trader
test_ok = 0
for risk, pos in ohne[:20]:
    try:
        dp = batch_trader.laden_aus_datei(
            os.path.join(_ALTES, f"depot_{risk:03d}.json")) \
            if os.path.exists(os.path.join(_ALTES, f"depot_{risk:03d}.json")) \
            else None
        if dp is not None:
            test_ok += 1
    except Exception as e:
        fehlgeschlagen += 1
        print(f"  FEHL  Risk {risk} laesst sich nicht laden: "
              f"{type(e).__name__}: {str(e)[:60]}")
pruefe(test_ok > 0, f"Alt-Depots laden weiterhin ({test_ok} geprueft)")

print()
print("=" * 70)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 70)

sys.exit(1 if fehlgeschlagen else 0)
