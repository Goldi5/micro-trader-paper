"""Gegenprobe: der Markt-Cache darf nicht mehr vernichtet werden.

BEFUND DES BUGS (vor dem Fix):
  scan_markt(['AAPL'], force=True) schrumpfte .scan_cache.json
  von 657 Titeln auf 1. Danach konnte der Trader nur noch einen
  Titel bewerten - ohne Fehlermeldung, einfach "nichts zu kaufen".

Diese Gegenprobe prueft in drei Schritten:

  1. Der Vollbestand wird hergestellt (falls er weg ist).
  2. Ein gezielter Abruf mit force=True laesst ihn intakt.
  3. Der Produktivpfad bewertet danach wieder viele Titel.

Schritt 1 ist wichtig, weil der Cache im Testlauf bereits
zerstoert war. Ohne Neuaufbau waere jeder Folgetest sinnlos.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import json
import os
import subprocess
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

import engine
from risk_profile import fuer_risk_stufe

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
print(" Gegenprobe: Markt-Cache bleibt erhalten")
print("=" * 70)
print()

# ── Schritt 1: Vollbestand sicherstellen ──
# WICHTIG: scan_markt() OHne Argument holt keine neuen Daten. Es
# liefert nur den Cache zurueck, weil die Titel-Liste fehlt. Der
# Produktivpfad ruft scan_markt(ticker) mit einer echten Liste.
# Mein erster Test rief scan_markt() auf und sah deshalb dauerhaft
# nur 1 Titel - das war ein Testfehler, kein Produktfehler.
from risk_profile import TICKER_TO_TIER

ALLE_TICKER = sorted(TICKER_TO_TIER.keys())
print(f"  Universum laut risk_profile: {len(ALLE_TICKER)} Titel")

vorher = engine.scan_markt()
print(f"  Bestand beim Start: {len(vorher)} Titel")
if len(vorher) < 100:
    print("  Cache war zerstoert - baue den Vollbestand neu auf ...")
    # In Bloecken, sonst fragt yfinance ein einziges Mal nach 657
    # Titeln und läuft in ein Rate-Limit.
    for i in range(0, len(ALLE_TICKER), 100):
        block = ALLE_TICKER[i:i + 100]
        engine.scan_markt(block, force=True)
        print(f"    {i + len(block)}/{len(ALLE_TICKER)}", end="\r")
    zwischen = engine.scan_markt()
    print(f"\n  Bestand nach Neubau: {len(zwischen)} Titel")
    vorher = zwischen

voll = len(vorher)
pruefe(voll >= 100, f"Vollbestand vorhanden ({voll} Titel)")

# ── Schritt 2: gezielter Abruf mit force=True ──
print()
print("  Rufe scan_markt(['AAPL','SPY'], force=True) - das war der Bug")
einzeln = engine.scan_markt(["AAPL", "SPY"], force=True)
print(f"  Bestand danach: {len(einzeln)} Titel")

pruefe(len(einzeln) >= voll,
       f"force=True vernichtet den Bestand nicht "
       f"({len(einzeln)} >= {voll})")
pruefe("AAPL" in einzeln and "SPY" in einzeln,
       "die angeforderten Titel sind frisch im Cache")

# Ein Titel, der vorher da war, muss noch da sein
weg = [t for t in vorher if t not in ("AAPL", "SPY")
       and t not in einzeln]
pruefe(not weg,
       f"kein fremder Titel verschwunden "
       f"({len(weg)} fehlen)" + (f": {', '.join(weg[:5])}" if weg else ""))

# ── Schritt 3: Produktivpfad bewertet wieder ──
print()
alle = [dict(v, ticker=t) for t, v in einzeln.items()
        if isinstance(v, dict)]
bew = engine.bewerte(alle, budget=1000, risk_params=fuer_risk_stufe(50))
pruefe(len(bew) > 100,
       f"Risk 50 bewertet wieder viele Titel ({len(bew)})")

print()
print("=" * 70)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 70)

sys.exit(1 if fehlgeschlagen else 0)
