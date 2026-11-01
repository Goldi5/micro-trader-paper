"""Regressionstest: der KI-Pfad darf das Budget nicht ueberschreiten.

ANLASS (27.09.2026):
  Risk 25 und 55 blockierten mit "Betrag 2000.05 > erlaubt 2000.00"
  bzw. "Betrag 2600.01 > erlaubt 2600.00". Der Controller hat korrekt
  blockiert, aber grundlos.

  Der Betrag, den der Controller sieht, ist nicht der Bruchteil mal
  Kasse, sondern menge mal preis:

      budget 2000.00 -> menge 1.68995995 -> round 1.69
                     -> kosten 1.69 * 1183.46 = 2000.0474  BLOCKIERT

  round() hebt auf, sobald die 5. Nachkommastelle >= 5 ist. Von 1999
  gleichverteilten Werten liegen 999 ueber dem floor-Wert.

  engine.py:583-585 nutzt bereits math.floor und beschreibt genau
  diesen Fehler. Der KI-Pfad in batch_trader.py nutzte round().

  BEIDE Pfade muessen dieselbe Regel haben: abrunden.

Was hier geprueft wird:
  1. Die Rechnung aus dem Befund - vorher blockiert, jetzt nicht.
  2. floor haelt kosten <= budget ueber den ganzen Wertebereich.
  3. round haelt die Zusicherung NICHT - der Test belegt, dass die
     Aenderung noetig war und nicht kosmetisch.
  4. Beide Pfade im Quelltext nutzen floor.
  5. Der Controller laesst die tatsaechliche Abbuchung durch.

NICHT GETESTET wird die Tagesausfuehrung - dafuer waere ein
Markt-Login noetig. Geprueft wird die Rechnung, die den Block
ausgeloest hat.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import glob
import io
import json
import math
import os
import re
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

import risk_controller as rc

BESTANDEN = 0
FEHLER = []


def pruefe(name, bedingung, detail=""):
    global BESTANDEN
    if bedingung:
        BESTANDEN += 1
        print("  OK    %s" % name)
    else:
        FEHLER.append(name)
        print("  FEHL  %s  %s" % (name, detail))


def kosten(menge, preis, runden=True):
    m = round(menge, 4) if runden else math.floor(menge * 10000) / 10000.0
    return m * preis


print("")
print("=" * 74)
print(" 1. Die Rechnung aus dem Befund")
print("=" * 74)

# Das Budget kommt vom Controller selbst (rc.max_betrag), nicht als
# feste Zahl: Seit 62cd3db (01.10.2026, Risikoleiter 5-7 Positionen)
# ist position_size kleiner - die alten Festwerte 2000/2600 lagen dann
# ueber dem Limit, und der Test meldete einen Fehler, wo der Controller
# korrekt blockierte. Die Rundungsfrage ist von der Budgethoehe
# unabhaengig.
# Der Preis wird so gewaehlt, dass round() das Budget um mehr als die
# 1-Cent-Toleranz des Controllers (f6e2d17) ueberschreitet - sonst
# laesst der Controller die round-Menge zu Recht durch.
def _preis_mit_ueberschreitung(budget, start):
    p = start
    for _ in range(100000):
        if kosten(budget / p, p, runden=True) - budget > 0.05:
            return p
        p = round(p + 0.01, 2)
    raise RuntimeError("kein Preis mit round-Ueberschreitung gefunden")


for risk, startpreis in ((25, 1183.46), (55, 341.07)):
    budget = rc.max_betrag(10000.0, risk, tier=1)
    preis = _preis_mit_ueberschreitung(budget, startpreis)
    roh = budget / preis
    mit_round = kosten(roh, preis, runden=True)
    mit_floor = kosten(roh, preis, runden=False)

    print("")
    print("  Risk %d, Budget %.2f, Preis %.2f" % (risk, budget, preis))
    print("    roh          = %.8f" % roh)
    print("    round(,4)    = %.4f  ->  %.4f  (%+.4f)"
          % (round(roh, 4), mit_round, mit_round - budget))
    print("    floor(,4)    = %.4f  ->  %.4f  (%+.4f)"
          % (math.floor(roh * 10000) / 10000.0, mit_floor, mit_floor - budget))

    pruefe("Risk %d: round() ueberschreitet das Budget" % risk,
           mit_round > budget + 0.001,
           "erwartet > %.2f, war %.4f" % (budget, mit_round))
    pruefe("Risk %d: floor() haelt das Budget ein" % risk,
           mit_floor <= budget,
           "erwartet <= %.2f, war %.4f" % (budget, mit_floor))

    # Und der Controller: mit round blockiert, mit floor durchgelassen
    r_round = rc.pruefe_und_bremse(risk, ticker="X", tier=1, preis=preis,
                                   cash=10000.0, depot_wert=10000.0,
                                   anzahl_positionen=0, positionen=[],
                                   betrag=mit_round, drawdown_pct=0.0,
                                   quelle="test")
    r_floor = rc.pruefe_und_bremse(risk, ticker="X", tier=1, preis=preis,
                                   cash=10000.0, depot_wert=10000.0,
                                   anzahl_positionen=0, positionen=[],
                                   betrag=mit_floor, drawdown_pct=0.0,
                                   quelle="test")

    pruefe("Risk %d: round-Menge wird vom Controller blockiert" % risk,
           r_round.blockiert, "unerwartet erlaubt")
    pruefe("Risk %d: floor-Menge wird vom Controller erlaubt" % risk,
           not r_floor.blockiert,
           str(r_floor.reason or "")[:60])

print("")
print("=" * 74)
print(" 2. floor haelt die Zusicherung im ganzen Wertebereich")
print("=" * 74)

verletzungen_round = 0
verletzungen_floor = 0
geprueft = 0
for budget in (500.0, 1000.0, 2000.0, 2600.0, 3400.0, 10000.0):
    for preis in (12.34, 87.65, 341.07, 1183.46, 2477.13):
        roh = budget / preis
        if kosten(roh, preis, runden=True) > budget + 0.001:
            verletzungen_round += 1
        if kosten(roh, preis, runden=False) > budget:
            verletzungen_floor += 1
        geprueft += 1

print("  %d Kombinationen aus Budget x Preis geprueft" % geprueft)
print("  round() ueberschreitet in %d Faellen" % verletzungen_round)
print("  floor() ueberschreitet in %d Faellen" % verletzungen_floor)

pruefe("floor() verletzt die Budgetgrenze nie", verletzungen_floor == 0,
       "%d Verletzungen" % verletzungen_floor)
pruefe("round() verletzt sie oft - die Aenderung war noetig",
       verletzungen_round > geprueft // 4,
       "nur %d von %d - dann waere round() harmlos" % (verletzungen_round, geprueft))

print("")
print("=" * 74)
print(" 3. Beide Pfade im Quelltext nutzen floor")
print("=" * 74)

with io.open("batch_trader.py", encoding="utf-8") as f:
    bt = f.read()
with io.open("engine.py", encoding="utf-8") as f:
    en = f.read()

# Der KI-Pfad
ki_floor = "math.floor(menge * 10000) / 10000.0" in bt
pruefe("batch_trader.py: KI-Pfad nutzt floor statt round", ki_floor)

# Kein round(menge, 4) mehr im Kauf-Aktionsaufbau
ki_round = re.search(r'round\(menge,\s*4\)', bt)
pruefe("batch_trader.py: kein round(menge, 4) mehr", ki_round is None,
       "noch vorhanden" if ki_round else "")

# Order-Intent und Ausfuehrung muessen dieselbe Menge tragen.
# Sonst beschreibt der Intent eine andere Order als die Ausfuehrung.
pruefe("batch_trader.py: Order-Intent nutzt _menge_exec",
       "quantity=_menge_exec," in bt)
n_exec = bt.count('"menge": _menge_exec,')
pruefe("batch_trader.py: Aktion nutzt _menge_exec (1x)", n_exec == 1,
       "%d Treffer" % n_exec)
n_def = len(re.findall(r"_menge_exec = math\.floor", bt))
pruefe("batch_trader.py: _menge_exec genau einmal definiert", n_def == 1,
       "%d Definitionen" % n_def)

i_def = bt.find("_menge_exec = math.floor")
i_qty = bt.find("quantity=_menge_exec")
i_akt = bt.find('"menge": _menge_exec')
pruefe("batch_trader.py: Definition liegt vor beiden Verwendungen",
       -1 < i_def < i_qty and -1 < i_def < i_akt,
       "def=%d qty=%d akt=%d" % (i_def, i_qty, i_akt))

# Der Signalpfad (unveraendert, aber muss konsistent bleiben)
sig_floor = "math.floor(aktien * 100) / 100.0" in en
pruefe("engine.py: Signalpfad nutzt weiterhin floor", sig_floor)

pruefe("engine.py: dokumentiert den Grund fuer floor",
       "ABRUNDEN statt RUNDEN" in en)

# Import vorhanden?
pruefe("batch_trader.py: math importiert",
       bool(re.search(r"^import math$", bt, re.M)))

print("")
print("=" * 74)
print(" 4. Befund: der Ladder kannte die Benchmark-Regel nicht")
print("=" * 74)

# Regel r_20260801_07584 verbietet, den Benchmark zu kaufen.
# Die harte Leiter hat SPY in Risk 85 gewaehlt - deshalb blieb diese
# Stufe leer, obwohl sechs von sieben Stufen kaufen.
lader_titel = {}
for f in glob.glob((_MT_BASE + "/spec_depots_paper/depot_*.json")):
    d = json.load(open(f))
    e = (d.get("empfehlung") or {}).get("erlaubte_ticker") or []
    lader_titel[d["risk"]] = set(e)

r85 = lader_titel.get(85, set())
# Reine Information: Ist SPY nicht mehr in der Leiter, ist der Befund
# erledigt - das ist kein Fehler (frueher wurde das als FEHL gezaehlt).
if "SPY" in r85:
    print("  INFO  Risk 85: SPY ist in der Empfehlung (Benchmark-Konflikt besteht)")
else:
    print("  INFO  Risk 85: SPY nicht mehr in der Empfehlung - Befund erledigt")

# Die Regel steht NICHT im Code, sondern in ki_log.json - dem
# Regelschatten der KI. Deshalb kannte der Ladder sie nicht: er
# rechnet nur mit Kursdaten, nicht mit den erlernten Regeln.
# ki_log.json ist Laufzeitdatei (git-ignoriert) - fehlt sie, entfaellt
# die Pruefung, statt den ganzen Test abstuerzen zu lassen.
if os.path.exists("ki_log.json"):
    with io.open("ki_log.json", encoding="utf-8") as f:
        kilog = f.read()
    hat_regel = "r_20260801_07584" in kilog and "Benchmark" in kilog
    pruefe("ki_log.json enthaelt die Benchmark-Regel r_20260801_07584", hat_regel)
else:
    print("  SKIP  ki_log.json fehlt (Laufzeitdatei) - Regelpruefung entfaellt")

# Der Ladder liest ki_log.json nicht - genau deshalb kam SPY hinein.
with io.open("leiter_hart.py", encoding="utf-8") as f:
    lader = f.read()
pruefe("leiter_hart.py kennt die Benchmark-Regel nicht (erklaert den Befund)",
       "r_20260801_07584" not in lader and "ki_log" not in lader)

print("")
print("  Kein Fehler: die Regel hat Vorrang. Der Ladder ist der")
print("  schwaechere Vorschlag, die Regel aus ki_log.json entscheidet.")
print("  nur, ob der Ladder die Regel kennen sollte.")

print("")
print("=" * 74)
print(" ERGEBNIS: %d bestanden, %d fehlgeschlagen" % (BESTANDEN, len(FEHLER)))
print("=" * 74)

if FEHLER:
    for f in FEHLER:
        print("  - %s" % f)
    sys.exit(1)
sys.exit(0)
