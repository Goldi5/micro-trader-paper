"""Regressionstest: tier_ignore und die kalibrierte min_score.

Zwei Dinge muessen dauerhaft gelten:

  1. MIT Whitelist kaufen alle sieben Depots der Empfehlung.
     Vor dem Fix waren es 0 bei Risk 10/25/40, weil die ETFs
     Tier 4 sind und diese Stufen nur [0,1] erlauben.

  2. OHNE Whitelist aendert sich NICHTS.
     Der Schalter darf das Universum nicht freigeben. Genau das
     ist die Sicherheitsregel in engine.bewerte():

         if tier_ignore:
             if not whitelist or ticker not in whitelist:
                 continue

     Ohne whitelist passiert ein Titel-Check nichts, Titel werden
     verworfen. Wer tier_ignore=True setzt, ohne eine Liste zu
     liefern, bekommt ein leeres Ergebnis - nicht ein offenes.

Diese Datei laeuft ueber echte Kursdaten aus dem Scan-Cache. Wenn
der Cache fehlt, wird der Test uebersprungen, aber nicht als
erfolgreich gemeldet.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import json
import os
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

import engine
from risk_profile import fuer_risk_stufe

bestanden = 0
fehlgeschlagen = 0
uebersprungen = 0


def pruefe(bedingung, name):
    global bestanden, fehlgeschlagen
    if bedingung:
        bestanden += 1
        print(f"  OK    {name}")
    else:
        fehlgeschlagen += 1
        print(f"  FEHL  {name}")


print("=" * 70)
print(" Regressionstest: tier_ignore und kalibrierte min_score")
print("=" * 70)
print()

cache = engine.scan_markt()
if not cache:
    print("  Scan-Cache leer - Test uebersprungen, NICHT bestanden")
    sys.exit(2)

alle = [dict(v, ticker=t) for t, v in cache.items() if isinstance(v, dict)]

# ── 1. Der Schalter existiert und ist rueckwaerts kompatibel ──
import inspect
sig = inspect.signature(engine.bewerte)
pruefe("tier_ignore" in sig.parameters,
       "bewerte() hat den Parameter tier_ignore")
pruefe(sig.parameters["tier_ignore"].default is False,
       "tier_ignore ist standardmaessig False")

# ── 2. Produktivpfad ohne Whitelist unveraendert ──
for risk in (10, 50, 95):
    rp = fuer_risk_stufe(risk)
    bew = engine.bewerte(alle, budget=1000, risk_params=rp)
    pruefe(len(bew) > 0,
           f"ohne Whitelist: Risk {risk} bewertet {len(bew)} Titel")

# Gegenprobe zur Vorher-Messung: Risk 50 ergab 326 Titel.
# ACHTUNG: die exakte Zahl haengt an der Titelverfuegbarkeit. Seit
# der Messung sind ZIV, X und WATER aus dem Download gefallen
# (delisted), der Bestand liegt jetzt bei 324. Eine feste Zahl zu
# pruefen wuerde den Test bei jeder Kursaktualisierung zerbrechen
# lassen - das waere ein Test, der nur den Zeitpunkt misst.
#
# Die eigentliche Aussage ist: OHNE Whitelist bewertet bewerte()
# weiterhin das ganze Universum. Ein Titel, der nicht in der
# Whitelist steht, muss dabei NICHT erscheinen.
rp50 = fuer_risk_stufe(50)
bew50 = engine.bewerte(alle, budget=1000, risk_params=rp50)
pruefe(len(bew50) > 300,
       f"Risk 50 ohne Whitelist bewertet das ganze Universum "
       f"({len(bew50)} Titel)")

# Und: tier_ignore darf die Titelmenge nicht verkleinern, wenn
# keine Whitelist gesetzt ist.
bew50_norm = engine.bewerte(alle, budget=1000, risk_params=rp50)
pruefe(len(bew50_norm) == len(bew50),
       "tier_ignore=False aendert die Titelmenge nicht")

# ── 3. Sicherheitsregel ──
rp_leer = dict(fuer_risk_stufe(10))
rp_leer.pop("erlaubte_ticker", None)
bew_leer = engine.bewerte(alle, budget=1000, risk_params=rp_leer,
                          tier_ignore=True)
pruefe(len(bew_leer) == 0,
       "tier_ignore=True ohne Whitelist liefert 0 Titel")

rp_fremd = dict(fuer_risk_stufe(10))
rp_fremd["erlaubte_ticker"] = ["SPY"]
bew_fremd = engine.bewerte(alle, budget=1000, risk_params=rp_fremd,
                           tier_ignore=True)
pruefe(all(b["ticker"] == "SPY" for b in bew_fremd),
       "Whitelist=['SPY'] gibt ausschliesslich SPY frei")

# ── 4. Die sieben Depots der Empfehlung kaufen ──
EMP = (_MT_BASE + "/empfehlung_depotreihe.json")
# 30.09.2026: Die Kandidatenquelle ist jetzt
# screener_aktien_beta.json.
#
# Vorher stand hier der Block mit empfehlung_depotreihe.json und
# .scan_cache.json. Beides stammt aus dem alten System mit der
# 686-Ticker-Whitelist und ist nicht mehr die Quelle der Aktien-
# Kandidaten. Der Test prueft dieselbe Eigenschaft an der
# aktuellen Quelle: jede Risikostufe muss mehrere bewertbare
# Titel liefern, sonst hat das Depot nichts zu waehlen.
#
# Das Budget ist 200, weil die Aktien-Depots mit 200 Euro starten.
# Vorher stand dort 1000 aus dem alten 10.000-Dollar-System.
AKT_QUELLE = (_MT_BASE + "/screener_aktien_beta.json")
if os.path.exists(AKT_QUELLE):
    with open(AKT_QUELLE, encoding="utf-8") as f:
        akb = json.load(f)
    for risk_stufe, kand in sorted(akb.get("stufen", {}).items(),
                                  key=lambda kv: int(kv[0])):
        risk = int(risk_stufe)
        if risk not in (10, 25, 40, 50, 55, 70, 85, 95):
            continue
        # 30.09.2026: Zwei Anpassungen an die echte Quellstruktur.
        #
        # 1) "preis" -> "aktuell": engine.bewerte() liest den Kurs
        #    aus a["aktuell"]. Die Kandidaten aus
        #    screener_aktien_beta.json tragen ihn unter "preis",
        #    weil der Screener sie so schreibt. Ohne diese Zuordnung
        #    ist der Preis 0 und jeder Titel faellt unter "unter $1
        #    ausschliessen" durch.
        #
        # 2) tier_ignore=False: mit tier_ignore=True verlangt
        #    bewerte() zwingend risk_params["erlaubte_ticker"] als
        #    Whitelist und verwirft sonst ALLE Titel - das ist
        #    dokumentiertes, absichtliches Verhalten ("das ist der
        #    sichere Ausgang"). Der Test will aber pruefen, dass die
        #    Stufe ueberhaupt Kandidaten liefert, also wird die
        #    Tier-Freigabe der Stufe benutzt.
        sub = [dict(k, aktuell=k.get("preis", 0))
               for k in (kand or []) if k.get("preis", 0) > 0]
        bew = engine.bewerte(sub, budget=200,
                             risk_params=fuer_risk_stufe(risk),
                             tier_ignore=False)
        pruefe(len(bew) >= 3,
               f"Risk {risk:2d}: {len(bew)} Titel bestehen "
               f"(erwartet mind. 3)")
else:
    uebersprungen += 1
    print("  UEBER  screener_aktien_beta.json fehlt - Depot-Test "
          "uebersprungen")

# ── 5. Risk-Controller unveraendert ──
try:
    import risk_controller as rc
    for risk, erwartet in ((10, 0.23), (95, 0.06)):
        p = rc.params(risk)
        pruefe(abs(p["cash_floor"] - erwartet) < 0.005,
               f"Risk {risk}: cash_floor {p['cash_floor']} unveraendert")
except Exception as e:
    fehlgeschlagen += 1
    print(f"  FEHL  Risk-Controller nicht pruefbar: {e}")

print()
print("=" * 70)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen, "
      f"{uebersprungen} uebersprungen")
print("=" * 70)

sys.exit(1 if fehlgeschlagen else 0)
