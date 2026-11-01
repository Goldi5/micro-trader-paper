"""Test-Luecke schliessen: der Hebel-Test deckt nur einen Aufrufer ab.

DIE LUECKE
==========
test_hebel_trennung.py:165 sucht nur nach

    rc_max_betrag(depot_obj.bargeld, _risk_bt)

Das ist der Aufruf in batch_trader.py. Der Aufruf in etf_trader.py
hat depot["bargeld"] statt depot_obj.bargeld und risk statt
_risk_bt - der Regex passt nicht, die Datei wird gar nicht
betrachtet. Ergebnis: der Test war gruen, waehrend der
ETF-Kaufpfad 169 Kaeufe an der ungeklemmten Positionsgroesse
scheitern liess.

DIE EIGENTLICHE EIGENSCHAFT
===========================
Nicht "dieser Aufruf an dieser Stelle", sondern: JEDER Aufruf von
max_betrag in einem Kaufpfad uebergibt tier= UND hebel=. Sonst
rechnet der Controller eine andere Position als das Gate, und das
faellt als Blockade auf statt als Fehler.

Damit der Test Zaehne hat, wird ueber AST gelesen statt ueber
Regex: jeder Aufruf von max_betrag bzw. rc_max_betrag in den
beiden Kaufdateien wird gegen die Liste seiner Keyword-Argumente
geprueft.

NACHWEIS, DASS ER ZAHNE HAT
==========================
Gegen den alten etf_trader.py-Stand muss er rot werden. Das ist
der Beweis, dass die Regel greift und nicht nur gruen ist.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import ast, os, subprocess, sys

BASE = _MT_BASE
os.chdir(BASE)

KAUFPFADE = ["etf_trader.py", "batch_trader.py"]


def pruefe(bed, zusatz=""):
    global bestanden, fehlgeschlagen
    if bed:
        bestanden += 1
        print("  OK      %s" % bed)
    else:
        fehlgeschlagen += 1
        print("  FEHLER  %s" % bed)
    if zusatz:
        print("          %s" % zusatz)


bestanden = fehlgeschlagen = 0

print("=" * 72)
print(" Jeder max_betrag-Aufruf im Kaufpfad uebergibt tier= und hebel=")
print("=" * 72)

gefunden = 0
luecken = []
for datei in KAUFPFADE:
    p = os.path.join(BASE, datei)
    if not os.path.exists(p):
        continue
    with open(p, encoding="utf-8-sig") as f:
        src = f.read()
    tree = ast.parse(src)
    fuer_fn = None
    for node in ast.walk(tree):
        # Funktionskontext mitfuehren, um Kaufpfade zu unterscheiden
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fuer_fn = node.name
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name not in ("max_betrag", "rc_max_betrag"):
            continue
        kwargs = {k.arg for k in node.keywords if k.arg}
        gefunden += 1
        fehlt = {"tier", "hebel"} - kwargs
        if fehlt:
            luecken.append((datei, node.lineno, sorted(fehlt)))

print()
print("  %d max_betrag-Aufrufe in den Kaufpfaden gefunden"
      % gefunden)
print()
if luecken:
    for datei, lineno, fehlt in luecken:
        print("    %-18s Zeile %-5d fehlt: %s"
              % (datei, lineno, ", ".join(fehlt)))
    print()
pruefe(not luecken,
       "kein Aufruf ohne tier= und hebel= (%d Luecken)" % len(luecken))

print()
print("=" * 72)
print(" Gegenprobe: der Test muss gegen den ALTEN Stand rot werden")
print("=" * 72)
print()
print("  Die Backups sind nicht dasselbe:")
print("    .bak_deckel   = Stand VOR jeder Aenderung (kein tier/hebel)")
print("    .bak_deckel2  = Zwischenstand, tier/hebel war schon drin,")
print("                   nur 'rc.HEBEL_TIERS' statt 'HEBEL_TIERS'")
for b in (".bak_deckel", ".bak_deckel2"):
    bp = os.path.join(BASE, "etf_trader.py" + b)
    print("    %-14s %s" % (b,
                          "vorhanden" if os.path.exists(bp) else "FEHLT"))

alt = os.path.join(BASE, "etf_trader.py.bak_deckel")
if not os.path.exists(alt):
    print()
    print("  (kein Altstand vorhanden - Gegenprobe uebersprungen)")
else:
    alt_src = open(alt, encoding="utf-8-sig").read()
    tree = ast.parse(alt_src)
    alt_luecken = []
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name not in ("max_betrag", "rc_max_betrag"):
            continue
        n += 1
        kwargs = {k.arg for k in node.keywords if k.arg}
        fehlt = {"tier", "hebel"} - kwargs
        if fehlt:
            alt_luecken.append((node.lineno, sorted(fehlt)))
    print("  Altstand: %d Aufrufe, %d ohne tier/hebel"
          % (n, len(alt_luecken)))
    for lineno, fehlt in alt_luecken:
        print("    Zeile %-5d fehlt: %s" % (lineno, ", ".join(fehlt)))
    pruefe(len(alt_luecken) > 0,
           "der Test erkennt den alten, fehlerhaften Stand")
    pruefe(not luecken,
           "der Test ist am neuen Stand gruen")

print()
print("=" * 72)
print(" Die Kopplung: risk_stufe liefert 0..4, HEBEL_TIERS = {3,6}")
print("=" * 72)
sys.path.insert(0, BASE)
try:
    from etf_profile import risk_stufe
    from risk_controller import HEBEL_TIERS
    werte = sorted({risk_stufe(s) for s in range(101)})
    print("  risk_stufe(0..100) liefert:", werte)
    pruefe(3 in werte,
           "Tier 3 (Hebel) wird von risk_stufe ueberhaupt erreicht")
    pruefe(3 in HEBEL_TIERS,
           "Tier 3 steht in HEBEL_TIERS - die Klemme greift")
    # Und die Umkehrung: ein Breit-ETF-Tier darf NICHT als Hebel gelten
    breit = risk_stufe(20)
    pruefe(breit not in HEBEL_TIERS,
           "Tier %d (breit) gilt nicht als Hebel" % breit)
except Exception as e:
    print("  %s: %s" % (type(e).__name__, e))

print()
print("=" * 72)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 72)
sys.exit(1 if fehlgeschlagen else 0)