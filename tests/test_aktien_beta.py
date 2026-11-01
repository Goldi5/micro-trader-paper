"""Filter- und Bandpruefung fuer aktien_beta.py - ohne Netz."""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import io
import os
import sys

os.chdir(_MT_BASE)
sys.path.insert(0, _MT_BASE)
import aktien_beta as AB

FEHLER = []
n = 0


def pruefe(name, bedingung, text=""):
    global n
    n += 1
    if not bedingung:
        FEHLER.append("%s: %s" % (name, text))
        print("  [FAIL] %-34s %s" % (name, text))


# ── 1) Fonds/ETF sollen draussen bleiben ────────────────────────
FONDS = [
    ("iShares Core S&P 500 ETF", "ETF", True),
    ("SPDR S&P 500 ETF Trust", "ETF", True),
    ("Vanguard Total Stock Market ETF", "ETF", True),
    ("Global X Data Center REIT ETF", "ETF", True),
    ("iShares iBoxx Investment Grade Corporate Bond ETF", "ETF", True),
    ("Realty Income Corporation", "EQUITY", False),
    ("Prologis, Inc.", "EQUITY", False),
    ("Annaly Capital Management", "EQUITY", False),
    ("Netflix, Inc.", "EQUITY", False),
    ("Johnson & Johnson", "EQUITY", False),
]
for name, typ, soll_aus in FONDS:
    r = AB.ist_fonds(name, typ)
    pruefe("fonds:%s" % name[:26], r == soll_aus,
           "erwartet %s, bekam %s" % (soll_aus, r))

# ── 2) Hebel/Short sollen draussen bleiben ──────────────────────
HEBEL = [
    ("ProShares Ultra Semiconductors", "ETF", True),
    ("T-Rex 2X Long XYZ Daily Target", "ETF", True),
    ("Direxion Daily Gold Miners Bear 3X", "ETF", True),
    ("Bull & Bear Foods, Inc.", "EQUITY", False),
    ("Bear Creek Mining Corporation", "EQUITY", False),
    ("Growth Capital Partners", "EQUITY", False),
    ("Value Line, Inc.", "EQUITY", False),
    ("Ares Capital Corporation", "EQUITY", False),
    ("Global X Data Center REIT ETF", "ETF", True),
]
for name, typ, soll_aus in HEBEL:
    r = AB.ist_hebel(name, typ)
    pruefe("hebel:%s" % name[:26], r == soll_aus,
           "erwartet %s, bekam %s" % (soll_aus, r))

# ── 3) Beta-Baender: lueckenlos und ueberlappungsfrei ───────────
stufen = AB.STUFEN
pruefe("stufenanzahl", len(stufen) == 10, str(len(stufen)))
letztes_hi = 0.0
for s in stufen:
    lo, hi = AB.band(s)
    pruefe("band %d lo" % s, lo >= letztes_hi - 1e-9,
           "lo %.2f < vorheriges hi %.2f" % (lo, letztes_hi))
    pruefe("band %d hi" % s, hi > lo, "lo=hi=%.2f" % lo)
    letztes_hi = hi
pruefe("band 0 startet bei 0", AB.band(0)[0] == 0.0, str(AB.band(0)))

# Gegenprobe: jede Beta muss genau eine Stufe treffen, und die
# Grenze gehoert zur oberen Stufe (halb-offenes Intervall).
for b in (0.0, 0.2, 0.54, 0.55, 0.8, 1.0, 1.15, 1.3, 1.45, 1.6, 1.9, 3.0):
    treffer = [s for s in stufen if AB.band(s)[0] <= b < AB.band(s)[1]]
    pruefe("beta %.2f genau eine Stufe" % b, len(treffer) == 1,
           "-> %s" % treffer)

# Bandkanten: der Wert am unteren Rand gehoert zur Stufe selbst
pruefe("0,55 -> Stufe 10", AB.band(10)[0] == 0.55,
       str(AB.band(10)[0]))
pruefe("2,00 -> Stufe 90", AB.band(90)[0] == 2.00, str(AB.band(90)[0]))

# ── 4) Einordnen: Anker-Proben ─────────────────────────────────
cache = {"NVDA": {"beta": 2.2}, "JNJ": {"beta": 0.55},
         "SPY": {"beta": 1.0}, "TQQQ": {"beta": 3.7},
         "SCZ": {"beta": 1.1}, "NOBL": {"beta": 1.2}}

proben = [
    {"symbol": "NVDA", "shortName": "NVIDIA Corporation",
     "quoteType": "EQUITY", "regularMarketPrice": 180.0,
     "averageDailyVolume3Month": 5e7, "sector": "Technology"},
    {"symbol": "JNJ", "shortName": "Johnson & Johnson",
     "quoteType": "EQUITY", "regularMarketPrice": 160.0,
     "averageDailyVolume3Month": 8e6, "sector": "Healthcare"},
    {"symbol": "SPY", "shortName": "SPDR S&P 500 ETF Trust",
     "quoteType": "ETF", "regularMarketPrice": 600.0,
     "averageDailyVolume3Month": 5e7},
    {"symbol": "TQQQ", "shortName": "ProShares UltraPro QQQ",
     "quoteType": "ETF", "regularMarketPrice": 70.0,
     "averageDailyVolume3Month": 4e7},
    {"symbol": "SCZ", "shortName": "iShares MSCI China ETF",
     "quoteType": "ETF", "regularMarketPrice": 45.0,
     "averageDailyVolume3Month": 9e6},
    {"symbol": "NOBL", "shortName": "Some New Biotech",
     "quoteType": "EQUITY", "regularMarketPrice": 0},
    {"symbol": "XYZW", "shortName": "Unknown Biotech",
     "quoteType": "EQUITY", "regularMarketPrice": 12.0,
     "averageDailyVolume3Month": 1e5},
]

stufen_map, raus = AB.einordnen(proben, cache)
gefunden = sorted((k["ticker"], k["risk_score"], k["beta"])
                  for v in stufen_map.values() for k in v)
print()
print("  Proben im Ergebnis:", gefunden)

# JNJ Beta 0,55 gehoert an die untere Kante von Risk 10.
pruefe("proben ergebnis", gefunden == [("JNJ", 10, 0.55), ("NVDA", 90, 2.2)],
       "erwartet [('JNJ', 10, 0.55), ('NVDA', 90, 2.2)]")
ticker = [g[0] for g in gefunden]
for weg in ("SPY", "TQQQ", "SCZ"):
    pruefe("%s nicht drin" % weg, weg not in ticker, "")

# Die Zaehlung muss stimmen: 3 ETFs (SPY, TQQQ, SCZ), kein Fond,
# kein Hebel getroffen, 1 ohne Preis, 1 ohne Beta.
pruefe("kein_preis gezaehlt", raus["kein_preis"] == 1, str(raus))
pruefe("kein_beta gezaehlt", raus["kein_beta"] == 1, str(raus))
pruefe("3 ETFs verworfen", raus["fonds"] + raus["hebel"] == 3, str(raus))
pruefe("keine Aktie als Fonds", raus["fonds"] == 0, str(raus))
pruefe("keine Aktie als Hebel", raus["hebel"] == 3, str(raus))

# ── 4b) Boerse: Positivliste, gemessen an den sieben Kuerzeln ────
# Der Lauf vom 29.09.2026 lieferte genau diese sieben:
BOERSEN = [
    ("NYQ", False), ("NMS", False), ("NCM", False), ("ASE", False),
    ("OID", False), ("NGM", False), ("PNK", False),
]
for ex, soll_raus in BOERSEN:
    r = AB.ist_nicht_us(ex, "Beispiel")
    pruefe("boerse %s" % ex, r == soll_raus, "bekam %s" % r)

FREMDE = [("SAO", True), ("SAO PAULO", True), ("BUE", True),
          ("AMS", True), ("LSE", True), ("TOR", True), ("TYO", True),
          ("HKSE", True), ("TYU", True), ("xyz", True)]
for ex, soll_raus in FREMDE:
    r = AB.ist_nicht_us(ex, "Beispiel")
    pruefe("fremd %s" % ex, r == soll_raus, "bekam %s" % r)

# Ohne Exchange bleibt der Titel: fehlende Angabe ist kein Beweis
pruefe("boerse fehlt", AB.ist_nicht_us(None, "NVIDIA") is False, "")
pruefe("boerse leer", AB.ist_nicht_us("", "NVIDIA") is False, "")

# ── 4c) Beta zu klein heisst "kein gemeinsamer Markt" ────────────
pruefe("MIN_BETA gesetzt", AB.MIN_BETA == 0.15, str(AB.MIN_BETA))
pruefe("beta 0.14 faellt", 0.14 < AB.MIN_BETA, "")
pruefe("beta 0.15 bleibt", 0.15 >= AB.MIN_BETA, "")

cache2 = {"UGP": {"beta": 0.58}, "STEK": {"beta": 0.002},
          "NVDA": {"beta": 2.2}}
proben2 = [
    {"symbol": "UGP", "shortName": "Ultrapar Participacoes S.A.",
     "quoteType": "EQUITY", "regularMarketPrice": 4.2,
     "averageDailyVolume3Month": 2e6, "exchange": "OID"},
    {"symbol": "STEK", "shortName": "Stericycle Inc",
     "quoteType": "EQUITY", "regularMarketPrice": 54.0,
     "averageDailyVolume3Month": 9e5, "exchange": "NYQ"},
    {"symbol": "NVDA", "shortName": "NVIDIA Corporation",
     "quoteType": "EQUITY", "regularMarketPrice": 180.0,
     "averageDailyVolume3Month": 5e7, "exchange": "NGM"},
]
stufen2, raus2 = AB.einordnen(proben2, cache2)
nur = sorted(k["ticker"] for v in stufen2.values() for k in v)

# UGP ist jetzt ueber MIN_PREIS gefallen: gemessen 4.20 USD. Der
# Titel taugt damit als Anschauungsfall fuer zwei Filter, aber
# nicht mehr als Positivprobe.
pruefe("UGP faellt ueber MIN_PREIS",
       nur == ["NVDA"], "bekam %s" % nur)

# Gegenprobe: derselbe Titel ueber MIN_PREIS bleibt drin, wenn
# die Boerse US ist.
proben_ok = dict(proben2[0])
proben_ok["regularMarketPrice"] = 40.0
s_ok, _ = AB.einordnen([proben_ok], cache2)
t_ok = sorted(k["ticker"] for v in s_ok.values() for k in v)
pruefe("UGP bei 40 USD auf OID bleibt", t_ok == ["UGP"], "bekam %s" % t_ok)

# Und faellt, wenn die Boerse fremd ist - die beiden Filter sind
# unabhaengig voneinander.
proben_ausl = dict(proben_ok); proben_ausl["exchange"] = "SAO"
s_ausl, _ = AB.einordnen([proben_ausl], cache2)
t_ausl = sorted(k["ticker"] for v in s_ausl.values() for k in v)
pruefe("UGP bei 40 USD auf SAO faellt", t_ausl == [], "bekam %s" % t_ausl)

# ── 4d) Preis- und Kapitalgrenze ────────────────────────────────
pruefe("MIN_PREIS gesetzt", AB.MIN_PREIS == 5.0, str(AB.MIN_PREIS))
pruefe("MIN_MARKTKAPITAL gesetzt",
       AB.MIN_MARKTKAPITAL == 100_000_000, str(AB.MIN_MARKTKAPITAL))

cache3 = {"TME": {"beta": 1.0, "marktkapital": 5_000_000_000}}
pen = {"symbol": "TME", "shortName": "Tencent Music Entertainment",
       "quoteType": "EQUITY", "regularMarketPrice": 7.96,
       "averageDailyVolume3Month": 5e6, "exchange": "NMS"}
s_pen, r_pen = AB.einordnen([pen], cache3)
pruefe("kapital OK bleibt",
       sorted(k["ticker"] for v in s_pen.values() for k in v) == ["TME"],
       str(r_pen))

cache4 = {"TINY": {"beta": 1.0, "marktkapital": 30_000_000}}
klein = {"symbol": "TINY", "shortName": "Tiny Corp",
         "quoteType": "EQUITY", "regularMarketPrice": 25.0,
         "averageDailyVolume3Month": 5e6, "exchange": "NMS"}
s_klein, r_klein = AB.einordnen([klein], cache4)
pruefe("kapital zu klein faellt",
       sorted(k["ticker"] for v in s_klein.values() for k in v) == [],
       str(r_klein))
pruefe("kapital_zu_klein gezaehlt",
       r_klein["kapital_zu_klein"] == 1, str(r_klein))

penn = dict(pen); penn["regularMarketPrice"] = 0.08
s_penn, r_penn = AB.einordnen([penn], cache3)
pruefe("penn faellt",
       sorted(k["ticker"] for v in s_penn.values() for k in v) == [],
       str(r_penn))
pruefe("preis_zu_klein gezaehlt",
       r_penn["preis_zu_klein"] == 1, str(r_penn))

# Grenzwerte genau an der Kante
genau = dict(pen); genau["regularMarketPrice"] = 5.0
s_g, r_g = AB.einordnen([genau], cache3)
pruefe("5.00 USD bleibt (Kante gehoert dazu)",
       sorted(k["ticker"] for v in s_g.values() for k in v) == ["TME"],
       str(r_g))
# STEK faellt ueber MIN_BETA, egal auf welcher Boerse
alle2 = sorted(k["ticker"] for v in stufen2.values() for k in v)
pruefe("STEK durch MIN_BETA gefallen", "STEK" not in alle2,
       "beta %.3f < %.2f" % (0.002, AB.MIN_BETA))

# Gegenprobe: derselbe Titel auf einer US-Boerse faellt nur
# ueber das Beta, nicht ueber die Boerse
proben3 = dict(proben2[1])
proben3["exchange"] = "SAO"
s3, r3 = AB.einordnen([proben3], cache2)
t3 = sorted(k["ticker"] for v in s3.values() for k in v)
pruefe("STEK auf SAO faellt", t3 == [], "bekam %s" % t3)

# ── 5) Speichern: atomar, Ergebnis vollstaendig ─────────────────
import tempfile
import json as _json
alt = None
try:
    alt = open(AB.ZIEL, encoding="utf-8").read()
except Exception:
    pass

stufen_map["20"] = [{"ticker": "AAA", "name": "A", "preis": 1.0,
                     "beta": 0.8, "risk_score": 20, "sektor": "x",
                     "markt": "y", "volumen": 1, "ma_cap": 1,
                     "typ": "aktie"}]
stufen_map[20] = stufen_map.pop("20")
erg = AB.speichern(stufen_map, raus, "test")
gelesen = _json.load(open(AB.ZIEL, encoding="utf-8"))
pruefe("datei lesbar", gelesen["quelle"] == "test", str(gelesen["quelle"]))
pruefe("stufen als text", "20" in gelesen["stufen"], str(list(gelesen["stufen"])))
pruefe("kandidat gezaehlt", gelesen["zahlen"]["kandidaten"] == 3,
       str(gelesen["zahlen"]))
pruefe("kein .neu liegen", not os.path.exists(AB.ZIEL + ".neu"), "")

if alt is not None:
    io.open(AB.ZIEL, "w", encoding="utf-8").write(alt)
else:
    os.remove(AB.ZIEL)

print()
if FEHLER:
    print("FEHLGESCHLAGEN: %d von %d Pruefungen" % (len(FEHLER), n))
    for f in FEHLER:
        print("  - %s" % f)
    sys.exit(1)
print("BESTANDEN: %d Pruefungen" % n)