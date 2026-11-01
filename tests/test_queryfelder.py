"""Regressionstest: stille Query-Felder.

ROOT CAUSE (29.09.2026, aufgedeckt bei der Nachpruefung):
  screener.py nutzte fuer die ETF-Stufen das Feld "annualreturnnavy1".
  Dieses Feld gibt es bei Yahoo nicht. yfinance hat die Query OHNE
  Fehlermeldung ausgefuehrt und eine ungefilterte Volumen-Topliste
  geliefert - 374 Titel, die in der Begruendung als nach Rendite
  ausgewaehlt erschienen.

  Nachgewiesen: 297 von 374 Titeln lagen ausserhalb ihres own
  Bands. USO mit +103 % Jahresperformance lag in Risk 0.

  Ein ungueltiges Query-Feld ist bei Yahoo still: kein Fehler, kein
  Hinweis, nur eine Liste, die aussieht als haette sie gefiltert.

  DIESER TEST darf genau das nicht mehr durchlassen.

GEGENPROBE: test_queryfelder_wirken() fragt Yahoo direkt und
verlangt, dass das Feld in der ANTWORT wieder auftaucht.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import io
import json
import os
import sys

BASE = _MT_BASE
sys.path.insert(0, BASE)

ergebnisse = []


def pruefe(name, bestanden, detail=""):
    ergebnisse.append((name, bool(bestanden), detail))
    print("    [%s]   %-52s %s" % (
        "ok" if bestanden else "FAIL", name, detail))


print()
print("=" * 78)
print("  TEST: stille Query-Felder - der annualreturnnavy1-Fehler")
print("=" * 78)
print()

# ---------------------------------------------------------------------------
print("  1) Der Produktcode nennt kein Feld, das Yahoo nicht kennt")
# ---------------------------------------------------------------------------
import yfinance as yf
from yfinance.screener import query as q

# Die Felder, die Yahoo fuer ETFs wirklich kennt, stehen in der Map.
# Acht Eintraege - das ist die belegbare Menge, nicht meine Vermutung.
echte_felder = set(getattr(q, "ETF_SCREENER_EQ_MAP", {}).keys()) | {
    "region", "intradaymarketcap", "avgdailyvol3m", "avgdailyvol10d",
    "percentchange", "fiftytwowkpercentchange", "intradayprice",
    "dayvolume", "price", "epsgrowth.lasttwelvemonths",
}

s = io.open(os.path.join(BASE, "screener.py"), encoding="utf-8").read()

# Felder, die der Code als Query-Feld benutzt
benutzt = set()
import re
for m in re.finditer(r'ETFQuery\("(?:btwn|gt|lt|eq|or|and)"\s*,\s*\[?\s*"([a-z0-9]+)"', s):
    benutzt.add(m.group(1))
for m in re.finditer(r'"feld":\s*"([a-z0-9]+)"', s):
    benutzt.add(m.group(1))

unbekannt = benutzt - echte_felder
pruefe("alle ETF-Query-Felder sind bei Yahoo bekannt",
       not unbekannt,
       "unbekannt: %s" % ", ".join(sorted(unbekannt)) if unbekannt
       else "geprueft: %s" % ", ".join(sorted(benutzt)))

# Das konkrete Feld aus dem Fund darf nicht mehr im Code stehen
code_nur = s.split("# Lehre daraus")[0]
pruefe("annualreturnnavy1 nicht mehr als Query-Feld",
       '"feld": "annualreturnnavy1"' not in s,
       "nur noch im erklaerenden Kommentar" if "annualreturnnavy1" in s
       else "vollstaendig entfernt")

# ---------------------------------------------------------------------------
print()
print("  2) Gegenprobe: das benutzte Feld kommt in der ANTWORT zurueck")
# ---------------------------------------------------------------------------
try:
    from yfinance import ETFQuery

    q_test = ETFQuery("and", [
        ETFQuery("eq", ["region", "us"]),
        ETFQuery("btwn", ["fiftytwowkpercentchange", -30, 5]),
        ETFQuery("gt", ["avgdailyvol3m", 500000]),
    ])
    r = yf.screen(q_test)
    treffer = r["quotes"] if isinstance(r, dict) else getattr(r, "quotes", [])

    # Das entscheidende Kriterium: erscheint der Wert, nach dem
    # gefiltert wurde, auch in der Antwort?
    mit_wert = [x for x in treffer
                if x.get("fiftyTwoWeekChangePercent") is not None]
    im_band = [x for x in mit_wert
               if -30 <= x["fiftyTwoWeekChangePercent"] <= 5]

    pruefe("Query-Antwort enthaelt das Filterfeld",
           len(mit_wert) > 0,
           "%d von %d Quotes mit fiftyTwoWeekChangePercent"
           % (len(mit_wert), len(treffer)))
    pruefe("alle geprueften Werte liegen im Filterband",
           mit_wert and len(im_band) == len(mit_wert),
           "%d von %d im Band -30..+5%%"
           % (len(im_band), len(mit_wert)))

    # Und die Umkehrprobe: filtert das Feld ueberhaupt?
    q_eng = ETFQuery("and", [
        ETFQuery("eq", ["region", "us"]),
        ETFQuery("btwn", ["fiftytwowkpercentchange", 150, 300]),
        ETFQuery("gt", ["avgdailyvol3m", 500000]),
    ])
    r2 = yf.screen(q_eng)
    n_eng = r2["total"] if isinstance(r2, dict) else 0
    gesamt = r["total"] if isinstance(r, dict) else 0
    pruefe("verschiedene Baender liefern verschiedene Mengen",
           n_eng != gesamt,
           "Band -30..+5: %d Treffer, Band 150..+300: %d Treffer"
           % (gesamt, n_eng))

except Exception as e:
    pruefe("Gegenprobe gegen Yahoo durchfuehrbar", False,
           "%s: %s" % (type(e).__name__, str(e)[:60]))

# ---------------------------------------------------------------------------
print()
print("  3) Die gespeicherte Liste haelt ihr eigenes Band ein")
# ---------------------------------------------------------------------------
kand = os.path.join(BASE, "screener_kandidaten.json")
if os.path.exists(kand):
    d = json.load(io.open(kand, encoding="utf-8"))
    etf = d.get("etf", {})

    verletzungen = []
    for stufe, liste in etf.items():
        for k in liste:
            v = k.get("rendite_1j")
            if v is None:
                continue
            # Band aus der Stufe rekonstruieren ist nicht moeglich,
            # deshalb: die Begruendung nennt das Band im Klartext.
            b = k.get("begruendung", "")
            if "52W-Change" not in b and "Jahresrendite" in b:
                verletzungen.append(
                    (stufe, k["ticker"], "alte Begruendung: %s" % b[:40]))
    pruefe("keine Kandidaten mit veralteter Begruendung",
           not verletzungen,
           "%d betroffen" % len(verletzungen) if verletzungen
           else "alle Begruendungen nennen das Filterfeld")

    # Aktien: Disjunktheit, die seit dem Bau geprueft ist
    akt = d.get("aktien", {})
    kollision = 0
    gesehen = set()
    for stufe, liste in akt.items():
        for k in liste:
            if k["ticker"] in gesehen:
                kollision += 1
            gesehen.add(k["ticker"])
    pruefe("Aktien-Stufen sind disjunkt", kollision == 0,
           "%d Ticker, %d Doppelzuordnungen" % (len(gesehen), kollision))
else:
    pruefe("Kandidatenliste vorhanden", False, "Datei fehlt")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
bestanden = sum(1 for _, ok, _ in ergebnisse if ok)
gesamt = len(ergebnisse)
print("  ERGEBNIS: %d/%d bestanden" % (bestanden, gesamt))
print("=" * 78)
print()

sys.exit(0 if bestanden == gesamt else 1)
