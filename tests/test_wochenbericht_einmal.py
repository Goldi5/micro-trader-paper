"""Regressionstest: Der KI-Wochenbericht laeuft nur einmal pro Woche.

ANLASS (01.11.2026): micro_trader_scheduler.run_once() startete den
Bericht sonntags in jedem Loop-Durchlauf (alle 15 min). Jeder Lauf
uebernahm pending_rules -> learned_rules erneut.

Der Test laeuft ohne Live-Daten: der Stand wird in ein Temp-Verzeichnis
umgelenkt, reflexion_wochenbericht wird durch einen Zaehler ersetzt.
"""
import os
import sys
import tempfile
import types
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import micro_trader_scheduler as s  # noqa: E402

FEHLER = []


def pruefe(name, ok):
    print(("  OK    " if ok else "  FEHL  ") + name)
    if not ok:
        FEHLER.append(name)


tmp = tempfile.mkdtemp(prefix="wochenbericht_test_")
s.WOCHENBERICHT_STAND = os.path.join(tmp, "stand.json")

sonntag = datetime(2026, 11, 1, 10, 0)
montag = datetime(2026, 11, 2, 10, 0)
naechster_sonntag = datetime(2026, 11, 8, 10, 0)

pruefe("Montag: nicht faellig", not s._wochenbericht_faellig(montag))
pruefe("Sonntag ohne Stand: faellig", s._wochenbericht_faellig(sonntag))
s._wochenbericht_merken(sonntag)
pruefe("Sonntag nach Lauf: nicht mehr faellig",
       not s._wochenbericht_faellig(datetime(2026, 11, 1, 23, 45)))
pruefe("Naechster Sonntag: wieder faellig",
       s._wochenbericht_faellig(naechster_sonntag))

# run_once() mehrfach am selben Sonntag: Bericht genau einmal.
os.remove(s.WOCHENBERICHT_STAND)
aufrufe = []
fake = types.ModuleType("ki_reflexion")
fake.reflexion_wochenbericht = lambda: (aufrufe.append(1), (0, None))[1]
sys.modules["ki_reflexion"] = fake
s.log = lambda *a, **k: None
_echtes_dt = s.datetime


class _Sonntag(_echtes_dt):
    @classmethod
    def now(cls, tz=None):
        return sonntag


s.datetime = _Sonntag
# Danach nichts weiter ausfuehren: Pause-Flag in Temp-BASE setzen.
s.BASE = tmp
with open(os.path.join(tmp, "pause_flag.json"), "w") as f:
    f.write('{"paused": true, "grund": "test"}')
for _ in range(5):
    s.run_once()
s.datetime = _echtes_dt
pruefe("5x run_once am Sonntag -> 1 Wochenbericht (war: 5)", len(aufrufe) == 1)

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
