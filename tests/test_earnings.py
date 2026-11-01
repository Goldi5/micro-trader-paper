"""Test: Earnings-Sperre (earnings.py) und Einbau in engine.ausfuehren(). Offline."""
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import earnings  # noqa: E402

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + str(detail)))
    if not ok:
        FEHLER.append(name)


earnings.CACHE = os.path.join(tempfile.mkdtemp(), "cache.json")
earnings.konfiguration = lambda: {"aktiv": True, "tage_vorher": 2}
heute = date(2026, 11, 2)
termine = {"AAA": (heute + timedelta(days=1)).isoformat(),
           "BBB": (heute + timedelta(days=10)).isoformat(), "ETF": None}
abrufe = []


def fake(t):
    abrufe.append(t)
    if t == "ERR":
        raise RuntimeError("Netz weg")
    return termine.get(t)


earnings._hole_termin = fake
g, grund = earnings.kauf_gesperrt("AAA", heute)
pruefe("Zahlen morgen -> gesperrt", g and "03.11." in grund, grund)
pruefe("Zahlen in 10 Tagen -> frei", earnings.kauf_gesperrt("BBB", heute)[0] is False)
pruefe("kein Termin (ETF) -> frei", earnings.kauf_gesperrt("ETF", heute)[0] is False)
pruefe("Abruffehler -> frei (fail-open)", earnings.kauf_gesperrt("ERR", heute)[0] is False)
n = len(abrufe)
earnings.kauf_gesperrt("AAA", heute)
pruefe("zweiter Aufruf kommt aus dem Cache", len(abrufe) == n, abrufe)
earnings.konfiguration = lambda: {"aktiv": False}
pruefe("aktiv=false -> nie gesperrt", earnings.kauf_gesperrt("AAA", heute)[0] is False)

# Einbau in engine
earnings.konfiguration = lambda: {"aktiv": True, "tage_vorher": 400}
earnings.CACHE = os.path.join(tempfile.mkdtemp(), "cache.json")
termine["XYZ"] = (date.today() + timedelta(days=1)).isoformat()
import engine  # noqa: E402
import ki_kontext  # noqa: E402
import handelskosten  # noqa: E402


class _Frei:
    blockiert = False
    reason = "ok"


engine.rc_pruefe = lambda *a, **k: _Frei()
engine.ticker_zu_tier = lambda: {}
engine.hole_kurs = lambda t: 10.0
ki_kontext.ticker_konzentration = lambda t: 0
handelskosten.konfiguration = lambda: dict(handelskosten.STANDARD, aktiv=False)
d = engine.Depot(start_wert=100, risk=50, depot_pfad=os.path.join(tempfile.mkdtemp(), "d.json"))
aus = engine.ausführen(d, [{"typ": "kaufen", "ticker": "XYZ", "menge": 1, "preis": 10.0,
                            "grund": "t", "tier": 1}], {})
pruefe("engine: Kauf vor Quartalszahlen blockiert", aus == [] and "XYZ" not in d.positions
       and d.trades[-1]["grund"].startswith("Earnings-Sperre"), d.trades[-1:])
aus = engine.ausführen(d, [{"typ": "kaufen", "ticker": "SPYX", "menge": 1, "preis": 10.0,
                            "grund": "t", "tier": 4}], {})
pruefe("engine: Tier 4 (ETF) wird nicht abgefragt", "SPYX" not in abrufe and len(aus) == 1, abrufe)

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
