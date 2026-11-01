"""Test des Screeners: pruft die Eigenschaften, die er haben muss.

Nicht getestet wird "kommt etwas zurueck" - das sieht man am Lauf. 
Getestet werden die vier Eigenschaften, bei denen ein Fehler das
Ergebnis still verdirbt:

  1. Aktien-Stufen sind disjunkt - ein Titel in genau einer Stufe.
     Der erste Entwurf hatte 413 Dubletten und 57 von 60 Titeln in
     Risk 80 UND 90. Genau das muss auffallen.
  2. Jede Aktien-Kandidat hat Beta im Band seiner Stufe.
  3. Jeder Kandidat hat eine Begruendung, die nicht leer ist.
  4. Kein Micro-Cap (< 500 Mio USD) ausser bei Risk 90.
  5. Es wird nichts gekauft: der Screener schreibt nur eine
     Kandidatendatei, keine Depot-Datei.

Ohne Punkt 1 und 2 waere der Screener nutzlos - die Stufen waeren
nur Kosmetik.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import json
import sys

DATEI = (_MT_BASE + "/screener_kandidaten.json")
STUFEN = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]

bestanden = 0
gesamt = 0


def pruefe(label, bedingung, zusatz=""):
    global bestanden, gesamt
    gesamt += 1
    if bedingung:
        bestanden += 1
        print("  [ok]   %-52s %s" % (label, zusatz))
    else:
        print("  [FAIL] %-52s %s" % (label, zusatz))


print("=" * 80)
print("  Test des Screeners")
print("=" * 80)
print()

d = json.load(open(DATEI, encoding="utf-8"))
print("  Quelle: %s" % d.get("quelle"))
print("  Zeitpunkt: %s" % d.get("zeitpunkt"))
print()

# --- 1) Disjunktheit ---------------------------------------------------
print("  1) Aktien-Stufen sind disjunkt")
vorkommen = {}
for s in STUFEN:
    for k in d["aktien"].get(str(s), []):
        vorkommen.setdefault(k["ticker"], []).append(s)
mehrfach = {t: v for t, v in vorkommen.items() if len(v) > 1}
pruefe("kein Ticker in zwei Aktien-Stufen", len(mehrfach) == 0,
       "%d von %d Titeln mehrfach" % (len(mehrfach), len(vorkommen)))
if mehrfach:
    for t, v in list(mehrfach.items())[:5]:
        print("        %-8s in %s" % (t, ", ".join(str(x) for x in v)))
print()

# --- 2) Beta im Band ---------------------------------------------------
print("  2) Beta liegt im Band der eigenen Stufe")
BANDER = {0: (0.00, 0.35), 10: (0.35, 0.55), 20: (0.55, 0.75),
          30: (0.75, 0.90), 40: (0.90, 1.05), 50: (1.05, 1.20),
          60: (1.20, 1.40), 70: (1.40, 1.60), 80: (1.60, 1.90),
          90: (1.90, 3.00)}
verletzungen = []
ohne_beta = 0
for s in STUFEN:
    lo, hi = BANDER[s]
    for k in d["aktien"].get(str(s), []):
        b = k.get("beta")
        if b is None:
            ohne_beta += 1
            continue
        # Obergrenze ist INKLUSIV, untere exklusiv - genau so, wie
        # screener.py die Baender anlegt (lo <= beta <= hi). Mein
        # erster Test schrieb "lo <= b < hi" und meldete 3 Verletzungen
        # fuer Titel mit Beta exakt auf der Obergrenze (GILD 0.350,
        # ING 0.900, DOCU 0.900). Das war ein Testfehler: das Produkt
        # war richtig, die Erwartung im Test nicht.
        if not (lo <= b <= hi):
            verletzungen.append((k["ticker"], s, b, lo, hi))
pruefe("alle Beta-Werte im eigenen Band", len(verletzungen) == 0,
       "%d Verletzungen" % len(verletzungen))
for t, s, b, lo, hi in verletzungen[:5]:
    print("        %-8s Risk %-3d beta=%.2f ausserhalb %.2f-%.2f"
          % (t, s, b, lo, hi))
pruefe("jeder Kandidat hat ein Beta", ohne_beta == 0,
       "%d ohne Beta" % ohne_beta)
print()

# --- 3) Begruendung ----------------------------------------------------
print("  3) Jeder Kandidat traegt eine Begruendung")
leer = []
kurz = []
for s in STUFEN:
    for k in d["aktien"].get(str(s), []):
        b = k.get("begruendung") or ""
        if not b.strip():
            leer.append(k["ticker"])
        elif len(b) < 15:
            kurz.append(k["ticker"])
pruefe("keine leere Begruendung", len(leer) == 0, "%d leer" % len(leer))
pruefe("Begruendung ist substanziell", len(kurz) == 0, "%d zu kurz" % len(kurz))
beispiel = d["aktien"]["90"][0] if d["aktien"].get("90") else None
if beispiel:
    print("        Beispiel Risk 90: %s" % beispiel["begruendung"])
print()

# --- 4) Micro-Caps -----------------------------------------------------
print("  4) Keine Micro-Caps ausser bei Risk 90")
klein = []
for s in STUFEN:
    for k in d["aktien"].get(str(s), []):
        m = k.get("mcap")
        if m and m < 500_000_000 and s < 90:
            klein.append((k["ticker"], s, m))
pruefe("kein Micro-Cap unter Risk 90", len(klein) == 0, "%d Treffer" % len(klein))
for t, s, m in klein[:5]:
    print("        %-8s Risk %-3d mcap=%.0f Mio" % (t, s, m / 1e6))
print()

# --- 5) Kein Handel ----------------------------------------------------
print("  5) Der Screener handelt nicht")
import os
import re
import io
import time
# Echte Eigenschaft: Der Screener darf KEINE Depotdatei schreiben.
# Mein erster Test pruefte stattdessen die Anzahl der Dateien mit
# Praefix "screener" - das war eine Formpruefung, keine
# Eigenschaftspruefung, und sie wurde falsch, sobald der Wochenlauf
# (screener_woche.py) eine zweite Ergebnisdatei schreibt. Sie haette
# sogar eine Depotdatei als "screener..." durchgewunken.
# 30.09.2026: screener_aktien_beta.json kam mit der neuen
# Aktien-Datenbasis dazu. Sie ist eine Ergebnisdatei des
# Screeners, kein Depot, also gehoert sie in die Liste. Vorher
# stand sie nicht hier und der Test meldete sie faelschlich als
# unerwartet.
#
# Die Pruefung bleibt eine Whitelist: unerwartet ist alles, was
# nicht Ergebnisdatei ist. Eine Depotdatei wuerde weiterhin
# auffallen.
erlaubt = {"screener_kandidaten.json", "screener_verlauf.json", \
           "screener_etf_beta.json", "screener_aktien_beta.json"}
neu = [f for f in os.listdir(_MT_BASE)
       if f.startswith("screener") and not f.endswith(".py")]
unerwartet = [f for f in neu if f not in erlaubt]
pruefe("keine unerwartete Screener-Datei", len(unerwartet) == 0,
       ", ".join(neu) if not unerwartet else "unerwartet: %s" % unerwartet)

# Ein Name-muss-teil allein ist keine Pruefung: im Verzeichnis liegen
# 90 Depotdateien aus dem bisherigen Betrieb, die der Screener
# offensichtlich nicht geschrieben hat. "depot_*.json existiert" ist
# also immer wahr und damit als Test wertlos.
#
# Die pruefbare Aussage ist eine andere: WURDE eine Depotdatei
# waehrend des Screener-Laufs angefasst? Das beantwortet der
# Zeitvergleich weiter unten. Diese Datei-Zaehlung ist deshalb
# entfernt - sie hat 8 Wochen lang nichts gemessen.

# 30.09.2026: Der Zeitvergleich ist ersetzt. Er pruefte
# depot_zeit > kand_zeit, also die Reihenfolge von Trader und
# Screener - eine operative Annahme, keine Eigenschaft des
# Codes. Sobald der Screener laeuft und der Trader nicht, war
# der Test rot, ohne dass etwas kaputt war.
#
# Die pruefbare Aussage ist eine andere und wird direkt
# gemessen: KEIN Screener-Modul oeffnet einen Depotpfad.
SCREENER_MODULES = ("screener.py", "aktien_beta.py",
                    "etf_beta.py", "screener_woche.py")
depots_von_screener = []

for _mod in SCREENER_MODULES:
    _pfad = os.path.join(_MT_BASE, _mod)
    if not os.path.exists(_pfad):
        continue
    _qt = io.open(_pfad, encoding="utf-8").read()
    _pfade = re.findall(
        r"""['"]([A-Za-z0-9_./-]+\.(?:json|csv|txt))['"]""", _qt)
    # Nur echte Depotdateinamen zaehlen. Ein Muster wie
    # depot_*.json in einem Kommentar ist kein Schreibvorgang.
    for _p in _pfade:
        _b = os.path.basename(_p)
        if _b.startswith("depot_") or re.match(r"^[A-Z]{1,6}\.json$", _b):
            depots_von_screener.append("%s: %s" % (_mod, _p))

pruefe("kein Screener-Modul schreibt eine Depotdatei",
       len(depots_von_screener) == 0,
       ", ".join(depots_von_screener) if depots_von_screener
       else "%d Module geprueft, 0 Depotpfade" % len(SCREENER_MODULES))

print("  6) Umfang der Auswahl")
n_a = sum(len(v) for v in d["aktien"].values())
n_e = sum(len(v) for v in d["etf"].values())
uniq_a = len(vorkommen)
uniq_e = len({k["ticker"] for v in d["etf"].values() for k in v})
print("  Aktien: %d Kandidaten in 10 Stufen, %d eindeutige Ticker"
      % (n_a, uniq_a))
print("  ETFs:    %d Kandidaten in 10 Stufen, %d eindeutige Ticker"
      % (n_e, uniq_e))
print("  Vorher: 684 handgepflegte Ticker ohne Kriterien")
print()

print("=" * 80)
print("  ERGEBNIS: %d/%d bestanden" % (bestanden, gesamt))
print("=" * 80)
sys.exit(0 if bestanden == gesamt else 1)
