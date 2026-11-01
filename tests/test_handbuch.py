"""Test: Handbuch-PDF laesst sich aus docs/handbuch/HANDBUCH.md erzeugen. Offline."""
import os
import sys
import tempfile

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HIER, "tools"))
import handbuch_pdf  # noqa: E402

aus = os.path.join(tempfile.mkdtemp(), "h.pdf")
handbuch_pdf.erzeuge("vTEST", aus, quelle=os.path.join(HIER, "docs", "handbuch", "HANDBUCH.md"))
groesse = os.path.getsize(aus)
with open(aus, "rb") as f:
    kopf = f.read(5)
ok = kopf == b"%PDF-" and groesse > 10000
print(("  OK    " if ok else "  FEHL  ") + "Handbuch-PDF erzeugt (%d Bytes)" % groesse)
print("ERGEBNIS: %d Fehler" % (0 if ok else 1))
sys.exit(0 if ok else 1)
