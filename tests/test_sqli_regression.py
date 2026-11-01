"""REGRESSIONSTEST LUECKE 1 - SQL-Injection in db.query_trades()/query_ki().

VORHER (db.py mit f-string "ORDER BY zeit {order}"): FEHLSCHLAGEN.
NACHHER (Whitelist _safe_order): BESTANDEN, Exit-Code 0.

Der Test prueft ausschliesslich das VERHALTEN ueber die oeffentliche API.
Er referenziert _safe_order bewusst NICHT als Vorbedingung, damit er auf dem
alten Code mit einer aussagekraeftigen Meldung und nicht mit einem ImportError
scheitert.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)
from db import MTDB  # noqa: E402

FEHLER = []

# Der laufende Dienst haelt die SQLite-Datei offen; der Test arbeitet auf einer
# Kopie, damit er weder blockiert noch Produktivdaten anfasst.
_tmpdir = tempfile.mkdtemp(prefix="sqli_test_")
_kopie = os.path.join(_tmpdir, "micro_trader.db")
shutil.copy2((_MT_BASE + "/micro_trader.db"), _kopie)
db = MTDB(_kopie)

# Die Angriffsvektoren aus der Verifikation vom 27.09.2026.
# Entscheidend: "DESC, " leitet die Zahl der Sortierkriterien um, ein
# Subquery auf secret_store schiebt fremde Tabellenwerte in die Sortierung.
ANGRIFFE = [
    ("ORDER-BY-Umleitung", ", (SELECT secret_key FROM secret_store ORDER BY secret_key LIMIT 1)"),
    ("Boolean-Oracle", ", abs(CASE WHEN (SELECT COUNT(*) FROM secret_store) > 0 THEN 0 ELSE 1 END)"),
    ("Direktwert", ", (SELECT secret_value FROM secret_store LIMIT 1)"),
    ("Stacking", "ASC; DROP TABLE trades"),
    ("Zusaetzliches Kriterium", "ASC, (SELECT 1 FROM secret_store)"),
    ("Divisions-Fehlerkanal", "abs(CASE WHEN 1=1 THEN 0 ELSE 1/0 END)"),
]

for meth, name in ((db.query_trades, "query_trades"), (db.query_ki, "query_ki")):
    # Referenz: was ein sauberer, zulaessiger Aufruf liefert
    referenz = meth(order="DESC", limit=5)

    for label, payload in ANGRIFFE:
        try:
            ist = meth(order=payload, limit=5)
        except Exception:
            # SQLite hat die Payload abgewiesen -> keine Injektion. In Ordnung.
            continue
        if ist != referenz:
            FEHLER.append(
                f"{name}: Payload {label!r} veraenderte das Ergebnis gegenueber "
                f"einem sauberen order='DESC' ({len(referenz)} vs {len(ist)} Zeilen) "
                "-> die Payload wird ausgefuehrt")
            continue
        # Zweite Pruefung: das Ergebnis darf nicht nach einem Schluesselnamen
        # aus secret_store sortiert sein. Ein injiziertes Skalar-Subquery
        # aendert die Zeilenreihenfolge.
        if len(ist) > 1 and [r.get("zeit") for r in ist] != \
                [r.get("zeit") for r in referenz]:
            FEHLER.append(f"{name}: Payload {label!r} hat die Zeilenreihenfolge "
                          "veraendert -> Injektion wirksam")

# Sortiersemantik muss intakt bleiben
try:
    asc = db.query_trades(order="ASC", limit=5)
    desc = db.query_trades(order="DESC", limit=5)
    if len(asc) != len(desc):
        FEHLER.append(f"ASC/DESC liefern unterschiedliche Zeilenzahlen: "
                      f"{len(asc)} vs {len(desc)}")
    if len(asc) > 1 and asc[0]["zeit"] > desc[0]["zeit"]:
        FEHLER.append("ASC liefert nicht die frueheste Zeile - Sortierung defekt")
except Exception as e:
    FEHLER.append(f"Legitimer Aufruf scheitert: {type(e).__name__}: {e}")

# Quelltext-Gegenprobe: die rohe Interpolation ist entfernt
src = Path((_MT_BASE + "/db.py")).read_text(encoding="utf-8")
if "ORDER BY zeit {order}" in src:
    FEHLER.append("db.py enthaelt weiterhin die ungeschuetzte Interpolation "
                  "'ORDER BY zeit {order}'")

# secret_store muss unversehrt sein
try:
    if db.conn.execute("SELECT COUNT(*) FROM secret_store").fetchone()[0] < 1:
        FEHLER.append("secret_store ist leer - evtl. durch die Tests beschaedigt")
except Exception as e:
    FEHLER.append(f"secret_store nicht lesbar: {e}")

if FEHLER:
    print("FEHLGESCHLAGEN - SQL-Injection weiterhin ausnutzbar:")
    for f in FEHLER:
        print("  - " + f)
    shutil.rmtree(_tmpdir, ignore_errors=True)
    sys.exit(1)
shutil.rmtree(_tmpdir, ignore_errors=True)
print(f"BESTANDEN: {len(ANGRIFFE)} Angriffsvektoren x 2 Senken ohne Wirkung, "
      "ASC/DESC-Semantik intakt, secret_store unversehrt.")
