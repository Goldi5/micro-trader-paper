"""Beweis: die Depot-Empfehlung ueberlebt das Speichern.

BEFUND VORHER (drei Laeufe am 27.09.2026):
  Nach dem ersten Trade war "empfehlung" aus der Depot-Datei
  verschwunden. Ursache: Depot.speichern() schrieb ausschliesslich
  die Attribute der Klasse, "empfehlung" stand nicht darin.

DIESER TEST simuliert genau das, ohne den echten Handel:
  Depot anlegen -> Empfehlung als zusatz setzen -> speichern()
  -> neu laden -> pruefen, ob die Empfehlung noch da ist.

Zusaetzlich: ein Zusatzfeld darf die echten Depot-Felder nicht
ueberschreiben. Sonst koennte ein fehlerhaftes "positions" aus
einem Zusatz-Dict den Depot-Zustand zerstoeren.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import json
import os
import sys
import tempfile

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

import engine
import batch_trader

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
print(" Depot-Empfehlung ueberlebt das Speichern")
print("=" * 70)
print()

tmpdir = tempfile.mkdtemp(prefix="mt_zusatz_")
pfad = os.path.join(tmpdir, "depot_test.json")

# ── 1. Depot anlegen und Empfehlung setzen ──
d = engine.Depot(start_wert=10000, risk=55, depot_pfad=pfad)
d.zusatz = {
    "empfehlung": {
        "erlaubte_ticker": ["XLK", "XLE", "EEM", "MRK", "LLY"],
        "min_score": 21.4,
        "tier_ignore": True,
    }
}
# Einen Kauf simulieren, damit sichergestellt ist, dass es nicht
# nur das Neuanlegen schuetzt, sondern das Speichern nach einer
# Aenderung.
d.bargeld = 7400.0
d.positions = {"XLK": {"shares": 2.0, "avg_price": 1300.0,
                       "stop_loss": 1248.0, "take_profit": 1365.0}}
d.trades = [{"typ": "kauf", "ticker": "XLK", "menge": 2.0,
             "preis": 1300.0, "zeit": "2026-09-27T20:00:00"}]
d.speichern()
print("  Depot gespeichert (mit Position, wie nach einem Trade)")

# ── 2. Rohdatei pruefen ──
with open(pfad, encoding="utf-8") as f:
    roh = json.load(f)

pruefe("empfehlung" in roh,
       "empfehlung steht in der gespeicherten Datei")
if "empfehlung" in roh:
    e = roh["empfehlung"]
    pruefe(e.get("erlaubte_ticker") == ["XLK", "XLE", "EEM", "MRK", "LLY"],
           "erlaubte_ticker unveraendert")
    pruefe(e.get("min_score") == 21.4, "min_score unveraendert")
    pruefe(e.get("tier_ignore") is True, "tier_ignore unveraendert")

pruefe(roh.get("bargeld") == 7400.0, "Bargeld-Zustand korrekt")
pruefe(len(roh.get("positions") or {}) == 1, "Position-Zustand korrekt")
pruefe(len(roh.get("trades") or []) == 1, "Trade-Zustand korrekt")

# ── 3. Neu laden ──
d2 = batch_trader.laden_aus_datei(pfad)
pruefe("empfehlung" in (d2.zusatz or {}),
       "laden_aus_datei() fuellt zusatz")
if "empfehlung" in (d2.zusatz or {}):
    e2 = d2.zusatz["empfehlung"]
    pruefe(e2.get("erlaubte_ticker") == ["XLK", "XLE", "EEM", "MRK", "LLY"],
           "erlaubte_ticker ueberlebt Laden UND Speichern")
    pruefe(e2.get("tier_ignore") is True,
           "tier_ignore ueberlebt Laden UND Speichern")
pruefe(d2.bargeld == 7400.0, "Bargeld ueberlebt das Laden")
pruefe(len(d2.positions) == 1, "Positionen ueberleben das Laden")

# ── 4. Zweiter Speicherzyklus ──
print()
print("  Zweiter Zyklus (wie beim naechsten Handelstag)")
d2.trades.append({"typ": "verkauf", "ticker": "XLK", "menge": 2.0,
                  "preis": 1365.0, "zeit": "2026-09-28T20:00:00"})
d2.speichern()
with open(pfad, encoding="utf-8") as f:
    roh2 = json.load(f)
pruefe("empfehlung" in roh2,
       "empfehlung ueberlebt auch den zweiten Zyklus")
pruefe(len(roh2.get("trades") or []) == 2,
       "beide Trades gespeichert")

# ── 5. Schutz: Zusatz darf echte Felder nicht ueberschreiben ──
print()
print("  Schutz gegen Ueberschreibung")
d3 = engine.Depot(start_wert=5000, risk=20, depot_pfad=pfad)
d3.zusatz = {
    "bargeld": 999999,        # darf NICHT greifen
    "positions": {"HACKER": 1},  # darf NICHT greifen
    "empfehlung": {"erlaubte_ticker": ["SPY"]},
}
d3.speichern()
with open(pfad, encoding="utf-8") as f:
    roh3 = json.load(f)
pruefe(roh3.get("bargeld") == 5000.0,
       f"Zusatz 'bargeld' wird ignoriert (ist {roh3.get('bargeld')})")
pruefe(roh3.get("positions") == {},
       "Zusatz 'positions' wird ignoriert")
pruefe("empfehlung" in roh3, "echtes Zusatzfeld wird geschrieben")

# ── 6. Depots ohne Zusatz bleiben unveraendert ──
d4 = engine.Depot(start_wert=1000, risk=30, depot_pfad=pfad)
d4.speichern()
with open(pfad, encoding="utf-8") as f:
    roh4 = json.load(f)
erwartet = {"start_wert", "risk", "bargeld", "positions", "historie",
            "trades", "ki_letzte", "aktualisiert", "tenant_id",
            "mode", "exchanges"}
pruefe(set(roh4.keys()) <= erwartet,
       f"Depot ohne Zusatz schreibt keine Extra-Felder "
       f"({set(roh4.keys()) - erwartet or 'keine'})")

print()
print("=" * 70)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 70)

sys.exit(1 if fehlgeschlagen else 0)
