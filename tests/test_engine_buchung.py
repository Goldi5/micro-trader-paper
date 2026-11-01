"""Regressionstest: Depot-Buchhaltung in engine.py (ohne Live-Daten, ohne Netz).

ANLASS (01.11.2026, Code-Review):
  1. Depot.wert(): hole_kurs() liefert bei Fehler 0.0 -> Position zaehlte 0.
  2. Verkauf: Menge > Bestand schrieb mehr Bargeld gut als Stueck vorhanden.
  3. Nachkauf in bestehende Position fehlte im Rueckgabewert von ausfuehren().
  4. Depot.speichern() schreibt atomar (keine .tmp-Reste, gueltiges JSON).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + detail))
    if not ok:
        FEHLER.append(name)


class _Frei:
    blockiert = False
    reason = "ok"


# Externe Abhaengigkeiten stilllegen: Kurse, Controller, Konzentration.
engine.rc_pruefe = lambda *a, **k: _Frei()
engine.ticker_zu_tier = lambda: {}
import ki_kontext  # noqa: E402
import earnings  # noqa: E402
earnings.konfiguration = lambda: {"aktiv": False}  # kein Netz im Test
import handelskosten  # noqa: E402
# Reine Buchhaltung pruefen: Kosten aus (eigener Test: test_handelskosten.py)
handelskosten.konfiguration = lambda: dict(handelskosten.STANDARD, aktiv=False)
ki_kontext.ticker_konzentration = lambda t: 0

tmp = tempfile.mkdtemp(prefix="engine_test_")
d = engine.Depot(start_wert=1000, risk=50, depot_pfad=os.path.join(tmp, "depot.json"))

# 1) Kursausfall -> Einstandspreis statt 0
d.positions["AAA"] = {"shares": 10, "avg_price": 50.0}
d.bargeld = 500.0
engine.hole_kurs = lambda t: 0.0
pruefe("wert() bei Kurs 0 nutzt Einstandspreis", abs(d.wert() - 1000.0) < 1e-9, str(d.wert()))
engine.hole_kurs = lambda t: 60.0
pruefe("wert() mit gueltigem Kurs", abs(d.wert() - 1100.0) < 1e-9, str(d.wert()))

# 2) Verkauf mit zu grosser Menge
aus = engine.ausführen(d, [{"typ": "verkaufen", "ticker": "AAA", "menge": 25,
                            "preis": 60.0, "grund": "test"}], {})
pruefe("Uebergrosser Verkauf schreibt nur Bestand gut (10 x 60)",
       abs(d.bargeld - 1100.0) < 1e-9, "bargeld=%s" % d.bargeld)
pruefe("Position danach geschlossen", "AAA" not in d.positions)
pruefe("Verkauf im Rueckgabewert mit Menge 10",
       len(aus) == 1 and aus[0]["menge"] == 10, str(aus))

# 3) Kauf + Nachkauf
k = {"typ": "kaufen", "ticker": "BBB", "menge": 2, "preis": 100.0, "grund": "t", "tier": 1}
a1 = engine.ausführen(d, [dict(k)], {})
a2 = engine.ausführen(d, [dict(k)], {})
pruefe("Erstkauf im Rueckgabewert", len(a1) == 1, str(a1))
pruefe("Nachkauf im Rueckgabewert (war leer)", len(a2) == 1, str(a2))
pruefe("Bestand 4 Stueck, Bargeld 700", d.positions["BBB"]["shares"] == 4
       and abs(d.bargeld - 700.0) < 1e-9, "%s / %s" % (d.positions.get("BBB"), d.bargeld))

# 4) atomares Speichern
d.speichern()
with open(d.depot_pfad) as f:
    gespeichert = json.load(f)
pruefe("speichern(): gueltiges JSON mit Bestand", gespeichert["positions"]["BBB"]["shares"] == 4)
pruefe("speichern(): keine .tmp-Datei zurueck", not os.path.exists(d.depot_pfad + ".tmp"))

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
