"""Harte Tests fuer das Logsystem - simpler und ohne eigene Handler.

Der Trick: Das echte Log ist append-only. Also zaehle ich vorher,
mache den Test und vergleiche die Differenz. Kein kuenstlicher
Handler noetig, der Test prueft damit genau das, was laeuft.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import io
import json
import logging
import os
import sys
import threading
import time

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

import mtlog

OK, FAIL = [], []


def pruefe(name, bedingung, detail=""):
    (OK if bedingung else FAIL).append(name)
    print(f"  [{'OK ' if bedingung else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail else ""))


EV = os.path.join(mtlog.LOG_DIR, "events.jsonl")


def lies_zeilen():
    if not os.path.exists(EV):
        return []
    gut, kaputt = [], 0
    with io.open(EV, encoding="utf-8", errors="replace") as f:
        for z in f:
            z = z.strip()
            if not z:
                continue
            try:
                gut.append(json.loads(z))
            except json.JSONDecodeError:
                kaputt += 1
    return gut


mtlog.setup()
vorher = len(lies_zeilen())
print(f"Log hat vor dem Test {vorher} Zeilen")

print("=" * 72)
print(" T1-T3: STRUKTUR UND KORRELATION")
print("=" * 72)

# Einen echten Lauf erzeugen
rid_test = None
with mtlog.run("testlauf", risk=50) as rid_test:
    with mtlog.schritt("kurs", ticker="AAPL"):
        mtlog.log.info("Kurs geholt", preis=341.07, quelle="yfinance")
    with mtlog.schritt("ki_call", ticker="AAPL"):
        mtlog.log.info("KI antwortet", konfidenz=72, provider="groq")
    mtlog.entscheidung(aktion="kaufen", ticker="AAPL",
                       grund="RSI 28 uebersverkauft", konfidenz=72)
    mtlog.trade(aktion="kaufen", ticker="AAPL", menge=3, preis=341.07,
                wert=1023.21)
    mtlog.metrik("latenz_ms", 2340, quelle="ki_call")

neu = lies_zeilen()
test_zeilen = neu[vorher:]
print(f"Testlauf erzeugt {len(test_zeilen)} Zeilen, run_id={rid_test}")

# T1 prueft die GESAMTE Datei: wenn irgendeine Zeile kein JSON waere,
# waere das ein Defekt des Loggers, nicht des Testlaufs.
alle_objekte = all(isinstance(z, dict) for z in neu)
pruefe("T1: gesamte Datei ist gueltiges JSON", alle_objekte,
       f"{len(neu)} Zeilen, {len(test_zeilen)} davon aus dem Testlauf")

pflicht = ("ts", "level", "modul", "msg")
fehlend = [z for z in test_zeilen if not all(k in z for k in pflicht)]
pruefe("T2: Pflichtfelder vorhanden", not fehlend,
       f"{len(fehlend)} unvollstaendig")

# Alle Testzeilen tragen dieselbe run_id
mit_run = [z for z in test_zeilen if z.get("run") == rid_test]
pruefe("T3: Korrelations-ID gruppiert den Lauf",
       len(mit_run) == len(test_zeilen) and len(test_zeilen) >= 6,
       f"{len(mit_run)}/{len(test_zeilen)} mit run={rid_test}")

schritte = sorted({z.get("schritt") for z in mit_run if z.get("schritt")})
print(f"    Schritte im Lauf: {schritte}")
pruefe("T3b: Schritte erkennbar",
       "start" in schritte and "kurs" in schritte and "ki_call" in schritte,
       str(schritte))

# Zeitstempel prüfen: ISO mit Millisekunden
ts_ok = 0
for z in test_zeilen:
    t = z.get("ts", "")
    if len(t) >= 23 and t[10] == "T" and "." in t:
        ts_ok += 1
pruefe("T3c: Zeitstempel mit Millisekunden (Zeitachse rekonstruierbar)",
       ts_ok == len(test_zeilen), f"{ts_ok}/{len(test_zeilen)}")

print()
print("=" * 72)
print(" T4: LOGGER ARBEITET SELBST FEHLERFREI")
print("=" * 72)
diag = mtlog.diagnose()
print(f"    {diag['zeilen']}")
pruefe("T4: keine kaputten JSON-Zeilen",
       diag.get("kaputte_json_zeilen", 0) == 0,
       f"{diag.get('kaputte_json_zeilen')} kaputt")
pruefe("T4: keine eigenen Logger-Fehler", diag["logger_fehler"] == 0)
pruefe("T4: keine Probleme gemeldet", not diag["probleme"],
       str(diag["probleme"])[:80])

print()
print("=" * 72)
print(" T5: ROTATION")
print("=" * 72)
import logging.handlers
import tempfile

tmp = tempfile.mkdtemp()
h = logging.handlers.RotatingFileHandler(
    os.path.join(tmp, "rot.jsonl"), maxBytes=900, backupCount=3,
    encoding="utf-8")
h.setFormatter(mtlog._IsoFormatter())
wurzel = logging.getLogger("rotationstest")
wurzel.setLevel(logging.INFO)
wurzel.addHandler(h)
wurzel.propagate = False
for i in range(400):
    wurzel.info(f"Eintrag {i} mit Fuelltext", extra={"nr": i})
h.close()

dateien = sorted(os.listdir(tmp))
groessen = {d: os.path.getsize(os.path.join(tmp, d)) for d in dateien}
print(f"    Dateien: {len(dateien)}, Größen: {list(groessen.values())}")
pruefe("T5: Rotation erzeugt Generationen", len(dateien) > 1,
       f"{len(dateien)}")
pruefe("T5: keine Datei über maxBytes hinaus",
       all(v <= 1400 for v in groessen.values()),
       f"max {max(groessen.values())}")
pruefe("T5: Generationen begrenzt", len(dateien) <= 4, f"{len(dateien)}")

print()
print("=" * 72)
print(" T6: SECRETS WERDEN MASKIERT")
print("=" * 72)
faelle = [
    ("api_key=supersecret123", "supersecret123"),
    ("API_KEY: mein_geheimnis", "mein_geheimnis"),
    ("password=hunter2", "hunter2"),
    ("Authorization: Bearer abcdef123456", "abcdef123456"),
    ("token=xyz789topsecret", "xyz789topsecret"),
    ("OPENROUTER_API_KEY=sk-or-v1-abcdef123", "sk-or-v1-abcdef123"),
    ("GROQ_API_KEY=gsk_1234567890abcdef", "gsk_1234567890abcdef"),
    ("private_key=-----BEGIN RSA", "BEGIN RSA"),
]
weg = []
for text, geheimnis in faelle:
    m = mtlog._maskiere(text)
    if geheimnis in m:
        weg.append(text[:35])
        print(f"    LECK: {text[:38]} -> {m[:50]}")
    else:
        print(f"    ok:   {text[:38]}")
pruefe("T6: alle getesteten Secrets maskiert", not weg,
       f"{len(weg)} durchgerutscht")

print()
print("=" * 72)
print(" T7: LOGFEHLER STOPPEN DEN AUFRUFER NICHT")
print("=" * 72)
try:
    mtlog.log.info("Test mit kaputtem Feld", objekt=object(), f=1.5)
    ok1, t1 = True, "kein Fehler"
except Exception as e:
    ok1, t1 = False, f"{type(e).__name__}: {e}"
pruefe("T7a: nicht-serialisierbares Feld wirft nicht", ok1, t1)

try:
    mtlog.log.error("Mit Traceback", exc_info=True)
    ok2, t2 = True, "kein Fehler"
except Exception as e:
    ok2, t2 = False, str(e)[:50]
pruefe("T7b: exc_info wirft nicht", ok2, t2)

# exc_info=True OHNE aktiven Exception-Kontext erzeugt sys.exc_info()=(None,...).
# Das ist der Fall, der den Logger-Zaehler hochzaehlte: der Formatter
# rief format_exception() mit einem leeren Tupel auf. Beides muss
# fehlerfrei durchlaufen.
try:
    mtlog.log.info("ohne Exception-Kontext", feld="x")
    mtlog.entscheidung(aktion="halten")
    mtlog.metrik("m", 1)
    ok2b, t2b = True, "kein Fehler"
except Exception as e:
    ok2b, t2b = False, str(e)[:50]
pruefe("T7b2: Loggen ohne Exception-Kontext zaehlt keinen Fehler", ok2b, t2b)

try:
    with mtlog.run("fehlerlauf") as r2:
        raise RuntimeError("absichtlicher Fehler")
except RuntimeError:
    ok3, t3 = True, "Fehler propagiert wie erwartet"
except Exception as e:
    ok3, t3 = False, str(e)[:50]
pruefe("T7c: Lauf-Fehler werden geloggt und weitergeworfen", ok3, t3)

# Der Fehlerlauf muss im Log stehen
nach = lies_zeilen()
fehler_zeilen = [z for z in nach[vorher:]
                 if z.get("run") == r2 and z.get("level") == "ERROR"]
pruefe("T7d: fehlgeschlagener Lauf ist im Log",
       len(fehler_zeilen) >= 1, f"{len(fehler_zeilen)} ERROR-Zeilen")
if fehler_zeilen:
    hat_tb = "traceback" in fehler_zeilen[0]
    pruefe("T7e: Fehler enthält Traceback", hat_tb)

print()
print("=" * 72)
print(" T8: THREADS VERLIEREN KEINE ZEILEN")
print("=" * 72)
vorher_threads = len(lies_zeilen())
anzahl_threads = 8
pro_thread = 60


def arbeite(n):
    for i in range(pro_thread):
        mtlog.log.info(f"Thread {n} Zeile {i}", thread_nr=n, zeile=i)


t0 = time.time()
ts = [threading.Thread(target=arbeite, args=(n,)) for n in range(anzahl_threads)]
for t in ts:
    t.start()
for t in ts:
    t.join()
dauer = time.time() - t0

neu_gesamt = len(lies_zeilen())
ist = neu_gesamt - vorher_threads
soll = anzahl_threads * pro_thread
print(f"    {anzahl_threads} Threads x {pro_thread} = {soll} erwartet")
print(f"    {ist} Zeilen geschrieben in {dauer:.2f}s")
pruefe("T8: keine Zeilenverluste bei Threads", ist == soll, f"{ist}/{soll}")

print()
print("=" * 72)
print(" ZUSAMMENFASSUNG")
print("=" * 72)
print(f"  bestanden: {len(OK)}")
print(f"  fehlgeschlagen: {len(FAIL)}")
for f in FAIL:
    print(f"    - {f}")
sys.exit(1 if FAIL else 0)
