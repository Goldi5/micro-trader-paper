"""REGRESSIONSTEST: QUIET-Bug (Phase 3.3 des Rebuild-Plans)

BEFORE-FIX: dieser Test muss FEHLSCHLAGEN.
Er dokumentiert zwei Bugs aus der IST-Analyse:

  Bug A: engine.py - QUIET wird in scan_markt() benutzt, war aber nicht
         modulweit definiert -> NameError, Abbruch des Batch-/ETF-Laufs
  Bug B: engine.py - "from ki_decisions import QUIET" stand INNERHALB
         eines Zweigs. Python kompiliert QUIET fuer die ganze Funktion
         als Lokal -> UnboundLocalError.

Kriterium fuer "behoben": Exit-Code 0.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import subprocess
import sys
from pathlib import Path

M = Path(_MT_BASE)
PY = M / "venv/bin/python"
FEHLER = []


def test_quiet_modulweit_definiert():
    # engine.py muss QUIET auf Modulebene definieren, sonst NameError.
    src = (M / "engine.py").read_text(encoding="utf-8")
    hat_def = False
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        if code.startswith("QUIET") and "=" in code:
            hat_def = True
            break
    if not hat_def:
        FEHLER.append(
            "engine.py definiert QUIET nicht modulweit -> NameError in scan_markt() "
            "und Abbruch des kompletten Batch-/ETF-Laufs"
        )


def test_kein_import_innen_im_funktionskoerper():
    # Der Import darf nicht in einem Zweig stehen (Bug B).
    # Kommentarzeilen werden uebersprungen, sonst matcht der Test die
    # Bugfix-Dokumentation, die den alten Import selbst zitiert.
    src = (M / "engine.py").read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        code = line.split("#", 1)[0]
        if "import QUIET" in code:
            FEHLER.append(
                f"engine.py:{i} importiert QUIET im Funktionskoerper - "
                "verursacht UnboundLocalError bei Verkaufsaktionen ohne vorherigen Kauf"
            )
            break


def test_engine_importiert():
    r = subprocess.run(
        [str(PY), "-c", "import sys; sys.path.insert(0,'.'); import engine"],
        cwd=str(M), capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        FEHLER.append("engine.py nicht importierbar: " + r.stderr[-300:])


def test_scan_markt_ohne_nameerror():
    # Der eigentliche Funktionstest: scan_markt() muss durchlaufen.
    # Vor dem Fix: NameError. Nach dem Fix: liefert Ergebnisse.
    r = subprocess.run(
        [str(PY), "-c",
         "import sys; sys.path.insert(0,'.'); import engine; "
         "res = engine.scan_markt(['AAPL'], force=True); "
         "print('ERGEBNIS', len(res))"],
        cwd=str(M), capture_output=True, text=True, timeout=300,
    )
    if "NameError" in r.stderr:
        FEHLER.append("scan_markt() wirft weiterhin NameError: QUIET")
    elif r.returncode != 0:
        # andere Fehler (Netz, API) sind kein Regressionstest-Fail
        if "QUIET" in r.stderr:
            FEHLER.append("scan_markt() scheitert an QUIET: " + r.stderr[-200:])


if __name__ == "__main__":
    for fn in (
        test_quiet_modulweit_definiert,
        test_kein_import_innen_im_funktionskoerper,
        test_engine_importiert,
        test_scan_markt_ohne_nameerror,
    ):
        try:
            fn()
        except Exception as e:
            FEHLER.append(f"{fn.__name__} crashte: {type(e).__name__}: {e}")

    if FEHLER:
        print("FEHLGESCHLAGEN - folgende Probleme:")
        for f in FEHLER:
            print("  - " + f)
        sys.exit(1)
    print("BESTANDEN - alle 4 Pruefungen gruen")
