"""Test: Kennzahlen fuer den Tagesbericht (performance.py), KI-Aufrufprotokoll
(ki_provider) und der neue Berichtsabschnitt Benchmark/KI. Offline."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import performance as perf  # noqa: E402

FEHLER = []


def pruefe(name, ok, detail=""):
    print(("  OK    " if ok else "  FEHL  ") + name + ("" if ok else "  " + str(detail)))
    if not ok:
        FEHLER.append(name)


tmp = tempfile.mkdtemp()

# 1) Handelskosten aus Trades
hk = perf.handelskosten_aus_trades([
    {"typ": "kauf", "menge": 2, "preis": 100.0, "kurs_eff": 100.1, "gebuehr": 1.0},
    {"typ": "verkauf", "menge": 2, "preis": 110.0, "kurs_eff": 109.89, "gebuehr": 1.0},
    {"typ": "kauf", "menge": 1, "preis": 50.0},  # alt, ohne Kostenfelder
])
pruefe("Gebuehren 2.00", hk["gebuehr"] == 2.0, hk)
pruefe("Slippage 0.42", abs(hk["slippage"] - 0.42) < 1e-9, hk)
pruefe("1 Trade ohne Kostenfelder gezaehlt", hk["trades_ohne_kosten"] == 1, hk)

# 2) KI-Aufrufprotokoll -> Kennzahlen
import ki_provider  # noqa: E402
ki_provider.AUFRUF_LOG = os.path.join(tmp, "ki_aufrufe.jsonl")
import time  # noqa: E402
for antwort, prov in (("ok", "openrouter"), ("ok", "openrouter"), ("ok", "zen"), (None, "ALLE_PROVIDER_KALT")):
    ki_provider._protokolliere_aufruf("cron", time.time() - 1.5, antwort, prov)
with open(ki_provider.AUFRUF_LOG, "a") as f:  # alter Eintrag, faellt raus
    f.write(json.dumps({"zeit": (datetime.now() - timedelta(days=3)).isoformat(), "ok": False,
                        "fehler": "alt", "sekunden": 1}) + "\n")
k = perf.ki_kennzahlen(24, pfad=ki_provider.AUFRUF_LOG)
pruefe("4 Aufrufe in 24 h (alter Eintrag ignoriert)", k["aufrufe"] == 4, k)
pruefe("Ausfallquote 25 %", k["ausfall_quote_pct"] == 25.0, k)
pruefe("Anbieter openrouter 2, zen 1", k["anbieter"] == {"openrouter": 2, "zen": 1}, k)
pruefe("Fehler ALLE_PROVIDER_KALT 1", k["fehler"] == {"ALLE_PROVIDER_KALT": 1}, k)
pruefe("fehlende Datei -> None", perf.ki_kennzahlen(24, pfad=os.path.join(tmp, "x")) is None)

# 3) Berichtsabschnitt rendert (Benchmark gestubbt, kein Netz)
perf.benchmark_seit = lambda d, symbol="SPY": 5.0
perf.ki_kennzahlen = lambda stunden=24, pfad=None: k
import report_pdf as rp  # noqa: E402
from reportlab.platypus import SimpleDocTemplate  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
ss = getSampleStyleSheet()
S = {"h2": ss["Heading2"], "small": ss["BodyText"], "body": ss["BodyText"]}
el = []
daten = {"ges_pnl_pct": 3.0, "kat": {"Aktien": {"pnl_pct": 7.5}, "ETF": {"pnl_pct": 1.0}}}
rp._abschnitt_benchmark_ki(el, S, 17 * 28.35, daten,
                           [{"zeit": "2026-09-30T10:00:00"}, {"zeit": "2026-10-05T10:00:00"}])
texte = json.dumps([getattr(e, "_cellvalues", None) for e in el], default=str)
pruefe("Benchmark-Tabelle: Alle Depots -2.00 %-Pkt", "-2.00 %-Pkt" in texte, texte[:300])
pruefe("Benchmark-Tabelle: Aktien +2.50 %-Pkt", "+2.50 %-Pkt" in texte)
pruefe("KI-Tabelle: Ausfallquote 25.0 %", "25.0 %" in texte)
pdf = os.path.join(tmp, "t.pdf")
SimpleDocTemplate(pdf, pagesize=A4).build(el)
pruefe("PDF wird erzeugt", os.path.getsize(pdf) > 1000)

print("ERGEBNIS: %d Fehler" % len(FEHLER))
sys.exit(1 if FEHLER else 0)
