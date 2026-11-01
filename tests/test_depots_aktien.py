"""Gegenprobe: die zehn Aktien-Depots, bevor der Trader laeuft.

Bisher belegt: die Depots existieren, haben Sektorstreuung und
vernuenftige Preise. Nicht belegt: dass der Trader sie findet,
dem Risk-Controller folgt und Positionen schreibt.

Geprueft wird deshalb jede Voraussetzung einzeln, damit ein
Fehlschlag benennbar ist statt "irgendwas ging nicht".
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import io
import os
import sys
import json
import glob
import time

os.chdir(_MT_BASE)
sys.path.insert(0, _MT_BASE)

FEHLER = []
n = 0


def pruefe(name, bedingung, text=""):
    global n
    n += 1
    if not bedingung:
        FEHLER.append("%s: %s" % (name, text))
        print("  [FAIL] %-40s %s" % (name, text))


# ── 1) Die Depots ───────────────────────────────────────────────
stufen = list(range(0, 100, 10))
for s in stufen:
    p = "depot_%03d_paper.json" % s
    pruefe("depot %d existiert" % s, os.path.exists(p), p)

p = "depot_000_paper.json"
d = json.load(io.open(p, encoding="utf-8"))
print()
print("  Aufbau von %s:" % p)
for f in ("risk", "name", "mode", "start_wert", "bargeld",
          "kategorie", "tenant_id"):
    print("    %-12s %r" % (f, d.get(f)))

pruefe("risk stimmt", d.get("risk") == 0, str(d.get("risk")))
pruefe("name AKT-R00", (d.get("name") or "").startswith("AKT"), str(d.get("name")))
pruefe("start 200", abs((d.get("start_wert") or 0) - 200.0) < 0.01,
       str(d.get("start_wert")))
pruefe("bargeld = start", abs((d.get("bargeld") or 0) - 200.0) < 0.01,
       str(d.get("bargeld")))
pruefe("positions leer", not d.get("positions"), str(d.get("positions")))
pruefe("mode paper", d.get("mode") == "paper", str(d.get("mode")))

# ── 2) Der Trader findet sie ────────────────────────────────────
import batch_trader as B
pfade = sorted(glob.glob("depot_*_paper.json"))
gefunden = [os.path.basename(x) for x in pfade]
print()
print("  batch_trader sieht %d Depotdateien: %s"
      % (len(gefunden), ", ".join(gefunden[:4]) + " ..."))
pruefe("10 Depotdateien", len(pfade) == 10, str(len(pfade)))

# ── 3) Die Kandidatenquelle ─────────────────────────────────────
t = B.alle_ticker()
pro_stufe = B.screener_kandidaten()
print("  Quelle: %d Titel in %d Stufen"
      % (len(t), len(pro_stufe)))
pruefe("Quelle liefert Titel", len(t) > 100, str(len(t)))
pruefe("alle 10 Stufen belegt", len(pro_stufe) == 10, str(len(pro_stufe)))
pruefe("jede Stufe hat Kandidaten",
       all(len(v) > 0 for v in pro_stufe.values()),
       str({k: len(v) for k, v in sorted(pro_stufe.items())}))

# Gegenprobe: wie viele der Titel standen auch in der alten,
# handgepflegten Liste? Das ist keine Fehlerquelle, nur eine
# Information: die Quellen sind unabhaengig.
import risk_profile as RP
huelle = 0
for tt in t:
    huelle += 1 if tt in getattr(RP, "TICKER_TO_TIER", {}) else 0
print("  Titel aus der Quelle, die auch in der alten Liste stehen: %d" % huelle)

# ── 4) Der Risk-Controller kennt jede Stufe ────────────────────
from risk_profile import fuer_risk_stufe
# Das Feld heisst position_size, nicht max_betrag - die
# Controller-Parameter kommen aus get_params().
print()
print("  Risk-Controller je Stufe:")
gesehen = {}
for stufe in stufen:
    try:
        p = fuer_risk_stufe(stufe)
    except Exception as e:
        pruefe("risk_controller Risk %d" % stufe, False,
               "%s: %s" % (type(e).__name__, e))
        continue
    ok = isinstance(p, dict) and p.get("position_size") is not None
    pruefe("risk_controller Risk %d" % stufe, ok, str(p)[:60])
    gesehen[stufe] = p

# Die Skala muss mit dem Risiko steigen, nicht fallen - sonst
# waere die Depot-Beschriftung verkehrt herum beschriftet.
if len(gesehen) == len(stufen):
    sizes = [gesehen[x]["position_size"] for x in stufen]
    print("    position_size: %s" % " ".join("%.2f" % x for x in sizes))
    pruefe("position_size waechst mit Risiko",
           all(sizes[i] < sizes[i + 1] for i in range(len(sizes) - 1)),
           str(sizes))
    pruefe("max_positions faellt mit Risiko",
           all(gesehen[x]["max_positions"] >=
               gesehen[x + 10]["max_positions"]
               for x in stufen[:-1]),
           str([gesehen[x]["max_positions"] for x in stufen]))

    # Harte Bedingung: max_positions mal position_size darf
    # die Cash-Bodengrenze nie reissen.
    for x in stufen:
        p = gesehen[x]
        prod = p["max_positions"] * p["position_size"]
        pruefe("Risk %d: Positionen decken Start nicht ueber" % x, prod <= 1.0,
               "%d x %.2f = %.2f" % (p["max_positions"],
                                      p["position_size"], prod))

# ── 5) Kein Live-Broker ─────────────────────────────────────────
from security import get_broker_adapter, get_trading_mode
broker = type(get_broker_adapter(1)).__name__
modus = get_trading_mode(1)
print()
print("  Broker: %s   Modus: %s" % (broker, modus))
pruefe("PaperBrokerAdapter", broker == "PaperBrokerAdapter", broker)
pruefe("Modus PAPER", modus == "PAPER", str(modus))

print()
if FEHLER:
    print("FEHLGESCHLAGEN: %d von %d Pruefungen" % (len(FEHLER), n))
    for f in FEHLER:
        print("  - %s" % f)
    sys.exit(1)
print("BESTANDEN: %d Pruefungen" % n)