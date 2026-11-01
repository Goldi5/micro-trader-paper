"""Regressionstest: Kurs 0 (Rate-Limit) darf weder Depotwert noch Positionen zerstoeren.

ANLASS (01.11.2026, Code-Review):
  - spec_trader.SpecDepot.wert(force_price=0) bewertete die Position mit 0;
    aktualisiere_peak() konnte das Depot daraus DAUERHAFT sperren.
  - spec_trader.ausfuehren(): KI-Verkauf bei Kurs 0 verkaufte fuer 0.
  - SpecDepot.speichern() schreibt atomar.
Laeuft in einem Temp-Verzeichnis, ohne Netz.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import spec_trader as st  # noqa: E402
import marktdaten  # noqa: E402
marktdaten.hole_kurs = lambda t: 0.0  # Kursausfall simulieren, kein Netz

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + detail))
    if not ok:
        FEHLER.append(name)


tmp = tempfile.mkdtemp(prefix="spec_test_")
st.DEPOT_DIR = st.DEPOT_DIR_PAPER = tmp
st.QUIET = True

d = st.SpecDepot("TEST", name="Test", kategorie="aktie")
d.bargeld, d.shares, d.avg_price, d.peak_wert = 50.0, 1.0, 50.0, 100.0

pruefe("wert(force_price=0) nutzt Einstandspreis",
       abs(d.wert(force_price=0) - 100.0) < 1e-9, str(d.wert(force_price=0)))
d.aktualisiere_peak(0)
pruefe("Kurs 0 sperrt das Depot nicht", not d.gesperrt, d.gesperrt_grund)

d.gesperrt, d.gesperrt_grund = False, ""  # unabhaengig vom Test davor
st.ausführen(d, 0, {"aktion": "verkaufen", "konfidenz": 90, "menge": "voll", "grund": "t"})
pruefe("KI-Verkauf bei Kurs 0 behaelt die Position", d.shares == 1.0 and d.bargeld == 50.0,
       "shares=%s bargeld=%s" % (d.shares, d.bargeld))

d.speichern()
with open(d.pfad()) as f:
    pruefe("speichern(): gueltiges JSON", json.load(f)["shares"] == 1.0)
pruefe("speichern(): keine .tmp-Datei", not os.path.exists(d.pfad() + ".tmp"))

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
