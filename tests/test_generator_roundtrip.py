"""Vergleicht die generierte risk_profile.py mit der handgepflegten.
Nur Kommentare und Docstrings duerfen abweichen – der AUSFUEHRBARE Code
muss identisch sein, sonst wuerde ein Generatorlauf den Code aendern."""
import ast
import sys


def ohne_docstrings(baum):
    for knoten in ast.walk(baum):
        if hasattr(knoten, "body") and isinstance(knoten.body, list):
            neu = []
            for k in knoten.body:
                if (isinstance(k, ast.Expr) and isinstance(k.value, ast.Constant)
                        and isinstance(k.value.value, str)):
                    continue  # Docstring entfernen
                neu.append(k)
            knoten.body = neu
    return baum


def lade(pfad):
    src = open(pfad, encoding="utf-8").read()
    zeilen = [l.split("#", 1)[0] for l in src.splitlines()]
    return ast.dump(ohne_docstrings(ast.parse("\n".join(
        z for z in zeilen if z.strip()))))


a = lade("/tmp/rp_before_gen.py")
b = lade("risk_profile.py")
if a == b:
    print("OK  Ausfuehrbarer Code (ohne Kommentare/Docstrings) ist IDENTISCH")
    print("    -> ein erneuter Generatorlauf setzt die Risikosteuerung NICHT zurueck")
    sys.exit(0)
print("FEHL Ausfuehrbarer Code unterscheidet sich")
# erste Abweichung zeigen
for i in range(min(len(a), len(b))):
    if a[i] != b[i]:
        print("  A: ..." + a[max(0, i - 120):i + 160])
        print("  B: ..." + b[max(0, i - 120):i + 160])
        break
sys.exit(1)
