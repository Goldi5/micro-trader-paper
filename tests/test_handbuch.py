"""Test: Handbuch-PDF laesst sich aus docs/handbuch/HANDBUCH.md erzeugen. Offline."""
import os
import sys
import tempfile

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HIER, "tools"))
import handbuch_pdf  # noqa: E402

aus = os.path.join(tempfile.mkdtemp(), "h.pdf")
os.environ["MT_HANDBUCH_OFFLINE"] = "1"
handbuch_pdf.erzeuge("vTEST", aus, quelle=os.path.join(HIER, "docs", "handbuch", "HANDBUCH.md"))
groesse = os.path.getsize(aus)
fehler = 0
try:
    import markdown  # noqa: F401
    with open(os.path.join(HIER, "docs", "handbuch", "HANDBUCH.md"), encoding="utf-8") as f:
        seite = handbuch_pdf.html_bauen(f.read(), "vTEST", schriften="")
    pruef = {"Titelseite": 'class="cover"' in seite, "Inhalt": 'class="toc"' in seite,
             "Kapitel": seite.count('<span class="num">') >= 10, "Kasten": 'class="box ' in seite,
             "Ablauf-Grafik": "ERGEBNIS" in seite, "Kennzahlen": "class='kacheln'" in seite}
    for name, gut in pruef.items():
        print(("  OK    " if gut else "  FEHL  ") + "HTML: " + name)
        fehler += 0 if gut else 1
except ImportError:
    print("  --    HTML-Prüfung übersprungen (Paket markdown fehlt)")
with open(aus, "rb") as f:
    kopf = f.read(5)
ok = kopf == b"%PDF-" and groesse > 10000
print(("  OK    " if ok else "  FEHL  ") + "Handbuch-PDF erzeugt (%d Bytes)" % groesse)
fehler += 0 if ok else 1
print("ERGEBNIS: %d Fehler" % fehler)
sys.exit(1 if fehler else 0)
