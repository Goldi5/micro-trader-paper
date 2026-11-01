"""Test: harte Ausstiege und Trailing-Stop (exits.py) + Einbau in spec_trader. Offline."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import exits  # noqa: E402

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + str(detail)))
    if not ok:
        FEHLER.append(name)


exits.stop_faktor = lambda risk: 0.90  # 10 % Abstand, unabhaengig vom Controller

# Trailing zieht nach, faellt nie
s, h = exits.nachziehen(90.0, 100.0, 120.0, 0.9)
pruefe("Hoch 120 -> Stop 108", abs(s - 108.0) < 1e-9 and h == 120.0, (s, h))
s2, h2 = exits.nachziehen(s, h, 110.0, 0.9)
pruefe("Kurs faellt auf 110 -> Stop bleibt 108", abs(s2 - 108.0) < 1e-9 and h2 == 120.0, (s2, h2))
pruefe("Kurs 0 aendert nichts", exits.nachziehen(s, h, 0, 0.9) == (s, h))
pruefe("aktiv=False: Stop bleibt", exits.nachziehen(90.0, 100.0, 120.0, 0.9, aktiv=False)[0] == 90.0)

# pruefe_position
pos = {"avg_price": 100.0, "stop_loss": 90.0, "take_profit": 130.0, "shares": 1}
pruefe("Kurs 120: kein Ausstieg", exits.pruefe_position(pos, 120.0, 50, True) is None, pos)
pruefe("Stop auf 108 nachgezogen", abs(pos["stop_loss"] - 108.0) < 1e-9, pos)
pruefe("Kurs 107 -> trailing_stop", exits.pruefe_position(pos, 107.0, 50, True) == "trailing_stop")
pos = {"avg_price": 100.0, "stop_loss": 90.0, "take_profit": 130.0, "shares": 1}
pruefe("Kurs 89 -> stop_loss", exits.pruefe_position(pos, 89.0, 50, True) == "stop_loss")
pos = {"avg_price": 100.0, "stop_loss": 90.0, "take_profit": 112.0, "shares": 1}
pruefe("Kurs 113 -> take_profit", exits.pruefe_position(pos, 113.0, 50, True) == "take_profit")
pos = {"avg_price": 100.0, "shares": 1}
pruefe("ohne gespeicherten Stop: Stop aus Risikostufe (90)",
       exits.pruefe_position(pos, 95.0, 50, True) is None and abs(pos["stop_loss"] - 90.0) < 1e-9, pos)

# spec_trader: Komplettverkauf setzt Stop/Hoch zurueck
import spec_trader as st  # noqa: E402
import marktdaten  # noqa: E402
import handelskosten  # noqa: E402
marktdaten.hole_kurs = lambda t: 0.0
handelskosten.konfiguration = lambda: dict(handelskosten.STANDARD, aktiv=False)
st.DEPOT_DIR = st.DEPOT_DIR_PAPER = tempfile.mkdtemp()
st.QUIET = True
d = st.SpecDepot("TST", name="t", kategorie="aktie")
d.bargeld, d.shares, d.avg_price, d.peak_wert = 0.0, 1.0, 100.0, 150.0
d.stop_loss, d.take_profit, d.hoch_seit_kauf = 100.0, 200.0, 150.0
st.ausführen(d, 140.0, {"aktion": "verkaufen", "konfidenz": 90, "menge": "voll", "grund": "t"})
pruefe("spec: KI-Komplettverkauf setzt Stop/Hoch zurueck",
       d.shares == 0 and d.stop_loss is None and d.hoch_seit_kauf is None,
       (d.shares, d.stop_loss, d.hoch_seit_kauf))

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
