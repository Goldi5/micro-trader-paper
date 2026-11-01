"""Test: Handelskosten-Simulation (handelskosten.py) und Einbau in engine.ausfuehren().
Offline, ohne Live-Daten."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import handelskosten as hk  # noqa: E402

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + str(detail)))
    if not ok:
        FEHLER.append(name)


def cfg(**k):
    c = dict(hk.STANDARD)
    c["slippage_prozent"] = dict(hk.STANDARD["slippage_prozent"])
    c.update(k)
    return lambda: c


# 1) Standard: 1.00 fix, Slippage Aktie 0,1 %
hk.konfiguration = cfg()
r = hk.kauf(2, 100.0, 1000.0, tier=1)
pruefe("Kauf: Kurs +0,1 % Slippage", abs(r["kurs_eff"] - 100.1) < 1e-9, r)
pruefe("Kauf: Gebuehr 1.00", r["gebuehr"] == 1.0, r)
pruefe("Kauf: gesamt = 2*100.1 + 1", abs(r["gesamt"] - 201.2) < 1e-9, r)

v = hk.verkauf(2, 100.0, tier=1)
pruefe("Verkauf: Erloes = 2*99.9 - 1", abs(v["erloes"] - 198.8) < 1e-9, v)
pruefe("ETF-Slippage 0,05 %", abs(hk.ausfuehrungskurs(100, "kauf", tier=4) - 100.05) < 1e-9)
pruefe("Spekulativ 0,3 %", abs(hk.ausfuehrungskurs(100, "kauf", art="spekulativ") - 100.3) < 1e-9)

# 2) Menge wird verkleinert, damit Kauf + Gebuehr ins Bargeld passen
r = hk.kauf(10, 10.0, 50.0, tier=1)
pruefe("Menge passt ins Bargeld inkl. Gebuehr", r["gesamt"] <= 50.0 and r["menge"] < 10, r)

# 3) Gebuehr-Anteil-Grenze
hk.konfiguration = cfg(max_gebuehr_anteil_prozent=5)
r = hk.kauf(1, 15.0, 100.0, tier=4)
pruefe("15-EUR-Kauf bei 1 EUR Gebuehr und 5 %-Grenze abgelehnt", r["abgelehnt"] is not None, r)

# 4) aus = exakt das alte Verhalten
hk.konfiguration = cfg(aktiv=False)
r = hk.kauf(2, 100.0, 1000.0, tier=1)
pruefe("aktiv=false: keine Kosten", r["gesamt"] == 200.0 and r["gebuehr"] == 0.0, r)
pruefe("aktiv=false: Verkauf ohne Abzug", hk.verkauf(2, 100.0)["erloes"] == 200.0)

# 5) Einbau in engine.ausfuehren()
import engine  # noqa: E402
import ki_kontext  # noqa: E402
import earnings  # noqa: E402
earnings.konfiguration = lambda: {"aktiv": False}  # kein Netz im Test


class _Frei:
    blockiert = False
    reason = "ok"


engine.rc_pruefe = lambda *a, **k: _Frei()
engine.ticker_zu_tier = lambda: {}
engine.hole_kurs = lambda t: 100.0
ki_kontext.ticker_konzentration = lambda t: 0
hk.konfiguration = cfg()
d = engine.Depot(start_wert=1000, risk=50,
                 depot_pfad=os.path.join(tempfile.mkdtemp(), "d.json"))
engine.ausführen(d, [{"typ": "kaufen", "ticker": "X", "menge": 2, "preis": 100.0,
                      "grund": "t", "tier": 1}], {})
pruefe("engine Kauf: Bargeld 1000 - 201.2", abs(d.bargeld - 798.8) < 1e-9, d.bargeld)
pruefe("engine Kauf: Einstand enthaelt Kosten (100.6)",
       abs(d.positions["X"]["avg_price"] - 100.6) < 1e-9, d.positions["X"])
pruefe("engine Kauf: Gebuehr im Trade", d.trades[-1].get("gebuehr") == 1.0, d.trades[-1])
engine.ausführen(d, [{"typ": "verkaufen", "ticker": "X", "menge": 2, "preis": 100.0,
                      "grund": "t", "tier": 1}], {})
pruefe("engine Verkauf: Bargeld + 198.8 (Round-Trip kostet 2.40)",
       abs(d.bargeld - 997.6) < 1e-9, d.bargeld)

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
