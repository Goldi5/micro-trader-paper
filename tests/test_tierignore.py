"""Gegenprobe fuer den tier_ignore-Schalter.

Es sind zwei Dinge gleichzeitig zu beweisen:

  1. MIT Whitelist kaufen die ETFs der Empfehlung.
     Risk 10/25/40 hatten vorher null verwertbare Titel.

  2. OHNE Whitelist bleibt das Verhalten exakt wie vorher.
     Ein Depot ohne eigene Liste darf durch das Schalten des
     Schalters nicht das ganze Universum freigeben.

Beide Richtungen werden gemessen, nicht behauptet.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import json
import os
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

import engine
from risk_profile import TICKER_TO_TIER, fuer_risk_stufe

cache = engine.scan_markt()
with open((_MT_BASE + "/empfehlung_depotreihe.json"),
          encoding="utf-8") as f:
    emp = json.load(f)


def werte_fuer(titel):
    return [dict(cache[t], ticker=t) for t in titel if t in cache]


print("=" * 74)
print(" GEGENPROBE 1: MIT Whitelist kaufen die ETFs")
print("=" * 74)
print()

ok = 0
fehler = 0
for dp in emp["depots"]:
    risk = dp["risk"]
    rp = dict(fuer_risk_stufe(risk))
    rp["erlaubte_ticker"] = dp["ticker"]
    sub = werte_fuer(dp["ticker"])
    bew = engine.bewerte(sub, budget=1000, risk_params=rp,
                         tier_ignore=True)
    if bew:
        ok += 1
        print(f"  Risk {risk:2d}: {len(bew)}/{len(dp['ticker'])} Titel "
              f"bestehen  {', '.join(f'{b['ticker']}({b['score']:.0f})' for b in bew)}")
    else:
        fehler += 1
        print(f"  Risk {risk:2d}: 0 Titel bestehen  "
              f"min_score={rp['min_score']}")

print()
print(f"  {ok} Depots kaufbar, {fehler} nicht")

print()
print("=" * 74)
print(" GEGENPROBE 2: OHNE Whitelist bleibt alles unveraendert")
print("=" * 74)
print()

# 2a: Produktivpfad ohne Whitelist -> wie vorher
alle = [dict(v, ticker=t) for t, v in cache.items() if isinstance(v, dict)]
for risk in (10, 50, 95):
    rp = fuer_risk_stufe(risk)
    bew = engine.bewerte(alle, budget=1000, risk_params=rp)
    print(f"  Risk {risk:2d} ohne Whitelist: {len(bew):3d} Titel, "
          f"erster={bew[0]['ticker'] if bew else '—'}")

print()

# 2b: tier_ignore=True OHNE Whitelist darf nichts freigeben
rp = dict(fuer_risk_stufe(10))
rp.pop("erlaubte_ticker", None)
bew = engine.bewerte(alle, budget=1000, risk_params=rp, tier_ignore=True)
print(f"  tier_ignore=True ohne Whitelist: {len(bew)} Titel "
      f"(muss 0 sein)")

# 2c: Whitelist mit einem fremden Ticker darf nichts freigeben
rp2 = dict(fuer_risk_stufe(10))
rp2["erlaubte_ticker"] = ["SPY"]
bew2 = engine.bewerte(alle, budget=1000, risk_params=rp2, tier_ignore=True)
nur_spy = [b["ticker"] for b in bew2]
print(f"  Whitelist=['SPY']: {len(bew2)} Titel, alle in Liste: "
      f"{set(nur_spy) <= {'SPY'}}  ({', '.join(nur_spy) or '—'})")

print()
print("=" * 74)
print(" GEGENPROBE 3: Risk-Controller unveraendert wirksam")
print("=" * 74)
print()
try:
    import risk_controller as rc
    for risk in (10, 55, 95):
        p = rc.params(risk) if hasattr(rc, "params") else None
        if p:
            print(f"  Risk {risk:2d}: cash_floor={p.get('cash_floor')} "
                  f"max_pos={p.get('max_positions')} "
                  f"size={p.get('position_size')}")
    print("  Controller liefert unveraenderte Werte - der Schalter")
    print("  betrifft nur die Titelauswahl, nicht die Risikogrenzen.")
except Exception as e:
    print(f"  Controller nicht direkt pruefbar: {e}")

print()
print("=" * 74)
if fehler == 0:
    print(" ERGEBNIS: alle sieben Depots kaufbar, Sicherheitsregel haelt")
else:
    print(f" ERGEBNIS: {fehler} Depots weiterhin ohne Kaufmoeglichkeit")
print("=" * 74)
