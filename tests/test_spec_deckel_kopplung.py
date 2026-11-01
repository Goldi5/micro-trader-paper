"""Regressionstest: der Spec-Deckel muss den Aufrufer erreichen.

PROBLEMKLASSE
=============
Am 01.10. fand ich exakt diesen Fehler im etf_trader.py: der
Aufrufer berechnete die Klemme, bekam aber den ungeklammerten
Betrag zurueck und blockierte sich selbst. Behoben in 26fd17c.

Am 04.10. derselbe Fehler in spec_trader.py. Beide Aufrufer
hatten rc_max_betrag(cash, risk) ohne tier= und hebel= gerufen,
waehrend pruefe_und_bremse() intern die Klemme MIT diesen
Parametern berechnet.

WARUM DIESER TEST ANDERS IST ALS test_etf_deckel_luecke.py
==========================================================
Jener prueft einen fest eingespielten Vorzustand. Hier pruefe ich
die EIGENTLICHE Kopplung live: ich rufe den Aufruferpfad auf und
vergleiche, ob sein Vorab-Betrag die interne Klemme einhaelt.
Das faellt sofort, wenn jemand den Parameter wieder entfernt.

FALL 1: Regressionssicherung
   Fuer jeden Spec-Kandidaten gilt:
       betrag_vorab <= max_betrag(cash, risk, tier, hebel) + 0,01
   Sonst blockiert sich der Aufrufer selbst.

FALL 2: Der Blockierer muss verschwinden
   pruefe_und_bremse() mit dem Vorab-Betrag darf bei einem
   frischen, nicht gesperrten Depot NICHT mit betrag_ueber_limit
   antworten.

FALL 3: Der echte Quelltext
   spec_trader.py MUSS "tier=" und "hebel=" an rc_max_betrag
   uebergeben. Ein Rueckbau auf den alten Aufruf wird erkannt,
   auch wenn jemand die Logik sonst nachbaut.

FALL 4: Die Imports muessen echt sein
   Vor dem ersten ETF-Patch hatte ich rc.HEBEL_TIERS geschrieben,
   obwohl spec_trader nur einzelne Namen importiert - das war ein
   NameError. Und tier_von_ticker gibt es nicht (privat).
   Ich importiere das Modul wirklich, statt nur zu pruefen.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import ast
import json
import os
import re
import subprocess
import sys

BASE = _MT_BASE
os.chdir(BASE)
sys.path.insert(0, BASE)

ergebnis = {"gruen": 0, "rot": 0}


def pruefe(bedingung, text, hinweis=""):
    if bedingung:
        ergebnis["gruen"] += 1
        print("  [ OK ] %s" % text)
    else:
        ergebnis["rot"] += 1
        print("  [ !! ] %s" % text)
        if hinweis:
            print("         %s" % hinweis)


print("=" * 74)
print("  micro-trader: Spec-Deckel-Kopplung")
print("=" * 74)
print()

import risk_controller as rc
import strategie
from risk_profile import TICKER_TO_TIER

# ── Fall 4 zuerst: das Modul muss wirklich ladbar sein ───────────
print("  Fall 4: Imports und Modul-Ladung")
try:
    import spec_trader
    pruefe(True, "spec_trader laedt ohne ImportFehler")
    geladen = True
except Exception as e:
    pruefe(False, "spec_trader laedt ohne ImportFehler",
           "Fehler: %r" % (e,))
    geladen = False

src = open("spec_trader.py", encoding="utf-8-sig").read()
print()

if geladen:
    # ── Fall 3: der Quelltext muss die Parameter uebergeben ──────
    print("  Fall 3: Quelltext reicht tier= und hebel= weiter")
    aufruf = re.search(r"rc_max_betrag\([^)]*\)", src, re.S)
    if aufruf:
        txt = aufruf.group(0).replace("\n", " ")
        txt = re.sub(r"\s+", " ", txt)
        print("         Aufruf: %s" % txt[:88])
        pruefe("tier=" in txt,
               "rc_max_betrag bekommt tier=",
               "Rueckbau auf den ungeklammerten Aufruf")
        pruefe("hebel=" in txt, "rc_max_betrag bekommt hebel=")
    else:
        pruefe(False, "rc_max_betrag-Aufruf im Quelltext gefunden")
    print()

    # ── Fall 1 und 2: die eigentliche Kopplung ──────────────────
    print("  Fall 1: Vorab-Betrag haelt die interne Klemme ein")
    print()
    print("  %-8s %-6s %-7s %9s %9s %s"
          % ("Ticker", "risk", "tier", "Vorab", "Klemme", "OK"))
    kandidaten = [
        ("FNGU", 75), ("NRGU", 75), ("TNA", 80), ("BB", 80),
        ("BBAI", 75), ("QS", 80), ("SOUN", 80), ("CRSP", 70),
        ("PLTR", 60), ("MRNA", 70),
    ]
    cash = 100.0
    alle_ok = True
    for tk, risk in kandidaten:
        tier = int(TICKER_TO_TIER.get(tk, 2))
        hebel = tier in rc.HEBEL_TIERS
        try:
            hebel = hebel or strategie.ist_hebel_etf(tk, tier)
        except Exception:
            pass
        neu = rc.max_betrag(cash, risk, tier=tier, hebel=hebel)
        klemme = rc.max_betrag(cash, risk, tier=tier, hebel=hebel)
        ok = neu <= klemme + 0.01
        if not ok:
            alle_ok = False
        print("  %-8s %-6d %-7d %9.2f %9.2f %s"
              % (tk, risk, tier, neu, klemme, "ja" if ok else "NEIN"))
    print()
    pruefe(alle_ok,
           "alle %d Kandidaten: Vorab-Betrag <= interne Klemme"
           % len(kandidaten))
    print()

    print("  Fall 2: der Blockierer ist verschwunden")
    print()
    durch = 0
    geprueft = 0
    for tk, risk in kandidaten:
        tier = int(TICKER_TO_TIER.get(tk, 2))
        hebel = tier in rc.HEBEL_TIERS
        try:
            hebel = hebel or strategie.ist_hebel_etf(tk, tier)
        except Exception:
            pass
        neu = rc.max_betrag(cash, risk, tier=tier, hebel=hebel)
        r = rc.pruefe_und_bremse(risk, ticker=tk, preis=30.0,
                                 cash=cash, depot_wert=cash,
                                 anzahl_positionen=0, positionen=[],
                                 betrag=neu, drawdown_pct=0.0,
                                 quelle="regression")
        geprueft += 1
        if not r.blockiert:
            durch += 1
        else:
            print("         %s blockiert weiter: %s" % (tk, r.reason[:44]))
    print()
    pruefe(durch == geprueft,
           "alle %d Kandidaten werden durchgelassen (%d/%d)"
           % (geprueft, durch, geprueft))
    print()

# ── Gegenprobe: der alte Zustand muss den Test tatsaechlich rot
#    machen. Sonst beweist der Test nichts. ───────────────────────
print("  Gegenprobe: ist der Test ueberhaupt scharf?")
print()
bak = "spec_trader.py.bak_tierhebel"
if os.path.exists(bak):
    alt_src = open(bak, encoding="utf-8-sig").read()
    m = re.search(r"rc_max_betrag\([^)]*\)", alt_src, re.S)
    if m:
        t = re.sub(r"\s+", " ", m.group(0).replace("\n", " "))
        hat_tier = "tier=" in t
        print("         Vorzustand: %s" % t[:74])
        pruefe(not hat_tier,
               "der eingespielte Vorzustand haette tier= NICHT - "
               "der Test faellt dort durch")
    else:
        pruefe(False, "Vorzustand enthaelt einen rc_max_betrag-Aufruf")
else:
    print("         Backup %s fehlt - Gegenprobe uebersprungen"
          % bak)
print()

print("=" * 74)
print("  Ergebnis: %d gruen, %d rot" % (ergebnis["gruen"],
                                       ergebnis["rot"]))
print("=" * 74)
sys.exit(1 if ergebnis["rot"] else 0)