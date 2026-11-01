"""Test: neue Watchdog-Alarme (KI-Ausfallquote, neu gesperrte Depots). Offline."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mt_watchdog as w  # noqa: E402

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + str(detail)))
    if not ok:
        FEHLER.append(name)


tmp = tempfile.mkdtemp()
w.BASE = tmp
w.STATE = os.path.join(tmp, "state.json")
os.makedirs(os.path.join(tmp, "spec_depots_paper"))
json.dump({"gesperrt": True}, open(os.path.join(tmp, "spec_depots_paper", "AAA.json"), "w"))
json.dump({"gesperrt": False}, open(os.path.join(tmp, "etf_050_paper.json"), "w"))
pruefe("gesperrte_depots findet nur das gesperrte",
       w.gesperrte_depots() == [os.path.join("spec_depots_paper", "AAA.json")], w.gesperrte_depots())

basis = {"market_time": True, "working": True, "scheduler_active": True,
         "depot_rows_24h": 100, "disk_pct": 10, "age_ki_h": 1, "age_trade_h": 1,
         "last_ki": "x", "last_trade": "x", "last_depot_snapshot": "x"}

d = dict(basis, ki_2h={"aufrufe": 10, "ausfall_quote_pct": 60.0, "fehler": {"429": 6}},
         gesperrte_depots=[])
titel = [a["title"] for a in w.decide(d)]
pruefe("KI-Ausfall 60 % in Marktzeit -> Alarm", "KI faellt aus" in titel, titel)
d = dict(basis, ki_2h={"aufrufe": 3, "ausfall_quote_pct": 100.0, "fehler": {}}, gesperrte_depots=[])
pruefe("zu wenige Aufrufe -> kein KI-Alarm", not w.decide(d), w.decide(d))

d = dict(basis, ki_2h=None, gesperrte_depots=["spec_depots_paper/AAA.json"])
pruefe("neu gesperrtes Depot -> Alarm", [a["title"] for a in w.decide(d)] == ["Depot gesperrt (Drawdown)"])
w._merke_gesperrte(d)
pruefe("bereits gemeldet -> kein zweiter Alarm", not w.decide(d), w.decide(d))

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
