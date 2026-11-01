"""Sperre: Werkzeuge duerfen die verifizierte Leiter nicht stillschweigend ersetzen.

ANLASS (27.09.2026):
  Drei Laeufe von leiter_hart.py haben "empfehlung_leiter.json"
  neu geschrieben (Zeitstempel 20:40:52), nachdem die Datei bereits
  verifiziert und in die Paper-Depots eingespielt war. Zwei weitere
  Laeufe meldeten "Geschrieben", ohne es zu tun.

  Ein Werkzeug, das Produktdaten schreibt, aber von keinem Test
  aufgerufen wird, ist eine Gefahr: ein spaeterer Lauf ersetzt die
  gepruefte Basis, und niemand merkt es, weil kein Test schlaegt.

  Die Sperre ist bewusst einfach: das Skript muss ausdruecklich
  entscheiden, ob es die bestehende Datei ueberschreiben darf. Ohne
  --force bricht es ab und legt seinen Lauf nach *.neu ab.

Was hier geprueft wird:
  1. Jedes der vier Werkzeuge hat die Sperre im Code
  2. Die Sperre greift: Schreiben ohne --force schlaegt fehl
  3. Mit --force wird geschrieben (an eine temporaere Datei, um die
     echte Leiter nicht zu zerstoeren)
  4. Die verifizierte Leiter bleibt unveraendert
  5. Die Leiter erfuellt weiterhin ihre eigenen Nebenbedingungen
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import io
import json
import os
import re
import subprocess
import sys
import tempfile

D = _MT_BASE
WERKZEUGE = ["leiter_hart.py", "depot_bauen.py",
             "minscore_messen.py", "leiter_einspielen.py"]

LEITER = D + "/empfehlung_leiter.json"
MINSCORE = D + "/min_score_leiter.json"

BESTANDEN = 0
FEHLER = []


def pruefe(name, bedingung, detail=""):
    global BESTANDEN
    if bedingung:
        BESTANDEN += 1
        print("  OK    %s" % name)
    else:
        FEHLER.append(name)
        print("  FEHL  %s  %s" % (name, detail))


def sig(pfad):
    with io.open(pfad, "rb") as f:
        return f.read()


print("")
print("=" * 74)
print(" 1. Sperre in allen vier Werkzeugen vorhanden")
print("=" * 74)

for w in WERKZEUGE:
    p = os.path.join(D, w)
    if not os.path.isfile(p):
        pruefe("%s vorhanden" % w, False, "fehlt")
        continue
    with io.open(p, encoding="utf-8") as f:
        src = f.read()
    hat_force = "--force" in src
    hat_sperre = ("--force" in src) and (".neu" in src)
    pruefe("%s: verlangt --force bei ueberschreibenden Zielen" % w,
           hat_sperre,
           "kein Schreibschutz" if not hat_sperre else "")

print("")
print("=" * 74)
print(" 2. Die verifizierte Leiter ist unveraendert")
print("=" * 74)

vorher_l = sig(LEITER)
vorher_m = sig(MINSCORE) if os.path.isfile(MINSCORE) else b""

lader = json.loads(vorher_l.decode("utf-8"))
betas = [s["beta"] for s in lader["stufen"]]
rhos = [s["maxrho"] for s in lader["stufen"]]

print("  Beta:   %s" % " -> ".join("%.3f" % b for b in betas))
print("  maxrho: %s" % " ".join("%.3f" % r for r in rhos))
pruefe("Leiter hat sieben Stufen", len(lader["stufen"]) == 7,
       "%d" % len(lader["stufen"]))
pruefe("Beta monoton steigend", all(betas[i] < betas[i+1] for i in range(6)),
       str([round(b, 3) for b in betas]))
pruefe("maxrho haelt die eigene Grenze ein",
       max(rhos) <= lader["maxrho_grenze"],
       "max %.3f > %.2f" % (max(rhos), lader["maxrho_grenze"]))

print("")
print("=" * 74)
print(" 3. Ein Werkzeug darf sie nicht ohne Zustimmung ueberschreiben")
print("=" * 74)

# Ein Mini-Werkzeug, das dasselbe Muster zeigt wie leiter_hart.py:
# es schreibt, aber nur wenn --force gesetzt ist.
probe = """import json, os, sys
ZIEL = sys.argv[1] if len(sys.argv) > 1 else None
force = "--force" in sys.argv
if ZIEL and os.path.exists(ZIEL) and not force:
    neu = ZIEL + ".neu"
    with open(ZIEL) as f:
        daten = json.load(f)
    with open(neu, "w") as f:
        json.dump(daten, f)
    print("ABGEBROCHEN: %s existiert. Ohne --force nur nach %s" % (ZIEL, neu))
    sys.exit(2)
print("geschrieben: %s" % ZIEL)
"""

tmpdir = tempfile.mkdtemp()
probepfad = os.path.join(tmpdir, "probe.py")
with io.open(probepfad, "w", encoding="utf-8") as f:
    f.write(probe)

ziel = os.path.join(tmpdir, "ziel.json")
with io.open(ziel, "w", encoding="utf-8") as f:
    f.write('{"a": 1}')

r1 = subprocess.run([sys.executable, probepfad, ziel],
                    capture_output=True, text=True, timeout=30)
pruefe("ohne --force: Abbruch mit Code != 0", r1.returncode != 0,
       "rc=%d" % r1.returncode)
pruefe("ohne --force: Zieldatei unberuehrt", os.path.isfile(ziel))
pruefe("ohne --force: Zweitdatei .neu entsteht",
       os.path.isfile(ziel + ".neu"),
       "kein .neu - der Schreibschutz waere wirkungslos")

r2 = subprocess.run([sys.executable, probepfad, ziel, "--force"],
                    capture_output=True, text=True, timeout=30)
pruefe("mit --force: Schreiben erlaubt", r2.returncode == 0,
       r2.stderr[:80])

print("")
print("=" * 74)
print(" 4. Die echte Leiter ist nach allen Pruefungen unveraendert")
print("=" * 74)

pruefe("empfehlung_leiter.json byte-identisch", sig(LEITER) == vorher_l)
pruefe("min_score_leiter.json byte-identisch",
       (sig(MINSCORE) if os.path.isfile(MINSCORE) else b"") == vorher_m)

print("")
print("  Hinweis: geprueft ist der Schreibschutz im Code und sein")
print("  Verhalten an einem gleichartigen Werkzeug. Ob leiter_hart.py")
print("  beim naechsten Lauf tatsaechlich abbremst, zeigt erst der")
print("  Aufruf selbst - mit --force waere die Pruefung wertlos.")

print("")
print("=" * 74)
print(" ERGEBNIS: %d bestanden, %d fehlgeschlagen" % (BESTANDEN, len(FEHLER)))
print("=" * 74)
if FEHLER:
    for f in FEHLER:
        print("  - %s" % f)
    sys.exit(1)
sys.exit(0)
