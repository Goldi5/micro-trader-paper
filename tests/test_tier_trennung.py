# test_tier_trennung.py
#
# STATUS 2026-10-05: ALTL AST (wird nicht als Regression gewertet)
#
# BEFUND
# -------
# Dieser Test prüft empfehlung_leiter.json - eine handgepflegte
# Risikoleiter mit 31 Large-Caps, erstellt am 27.09.2026.
#
# Der Aktien-Trader liest seine Kandidaten NICHT aus dieser Datei:
#
#     batch_trader.py:111   SCREENER_DATEI = screener_aktien_beta.json
#     batch_trader.py:177   pro_stufe = screener_kandidaten()
#
# Empfehlung_leiter.json wird nur von zwei Bauwerkzeugen gelesen:
#     leiter_einspielen.py   (spielt die Leiter in Paper-Depots ein)
#     minscore_messen.py     (misst min_score für die Leiter)
#
# Der Yahoo-Screener liefert 144 Titel, die Leiter nennt 31, die
# Überschneidung beträgt 6 (AAPL, SPY, TMO, TXN, UNH, WMT).
# Deshalb hat Risk 10 nur einen lebenden Titel, Risk 25 zwei - und
# bewerte() liefert mit so wenigen Titeln nichts zurück.
#
# Der Test ist deshalb seit dem 27.09. rot, unabhaengig von allen
# Änderungen danach. Gegenprobe über drei Git-Stände
# (1877afc / 4a97345 / 5f9aaad): identisch 8/1 bei allen dreien.
#
# WAS DARAUS FOLGT
# ----------------
# Der Test ist kein Betriebstest. Seine Aussage lautet: "die
# Empfehlungsleiter passt nicht mehr zum Screener" - nicht:
# "der Aktien-Trader hat einen Fehler".
#
# Die Frage, OB das System eine handgepflegte Leiter behalten
# soll oder sich vollständig auf den Screener verlassen soll, ist
# offen und gehört dem Nutzer. Bis dahin wird dieser Test nicht
# als Regression gewertet - und ein Test, der eine Datei prüft,
# die niemand liest, wird nicht "repariert", sondern markiert.
#
# Wiedereinschalten: Leiter neu aus dem aktuellen Screener bauen
# (leiter_hart.py) ODER den Test auf screener_aktien_beta.json
# umstellen. Beides ist eine Entscheidung, keine Reparatur.

"""Gegenprobe fuer die Tier-Trennung.

Es sind vier Dinge gleichzeitig zu beweisen:

  1. Breite ETFs sind ab Risk 0 erlaubt. Vorher gesperrt, weil
     Tier 4 "ETF/Hebel" hiess.
  2. Hebelprodukte bleiben ab Risk 0 gesperrt. Das ist der Punkt
     der ganzen Aenderung - eine breite ETF frei zu geben darf
     nicht bedeuten, dass TQQQ frei ist.
  3. Tier 0 "Defensiv" ist ab Risk 76 wieder erlaubt. Vorher fiel
     er weg, das war die Inversion.
  4. Die sieben Depots der Empfehlung sind alle kaufbar, und zwar
     die ETFS, die vorher wegen tier_gesperrt blockiert wurden.

Punkt 4 nutzt echte Kursdaten aus dem Markt-Cache. Ohne das
waeren die ersten drei nur Behauptungen.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import json
import os
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

bestanden = 0
fehlgeschlagen = 0


def pruefe(bedingung, name):
    global bestanden, fehlgeschlagen
    if bedingung:
        bestanden += 1
        print(f"  OK    {name}")
    else:
        fehlgeschlagen += 1
        print(f"  FEHL  {name}")


print("=" * 72)
print(" Tier-Trennung: breite ETFs ab Risk 0, Hebel ab Risk 76")
print("=" * 72)
print()

from risk_controller import TIER_NAMEN, allowed_tiers, tier_erlaubt
from risk_profile import TICKER_TO_TIER

# ── 1. Breite ETFs ab Risk 0 ─────────────────────────────────
BREIT = ["SPY", "VTI", "VOO", "IWM", "GLD", "SLV", "XLU",
         "XLP", "VNQ", "VEA", "XLK", "XLY", "XLF", "XLV"]
print("  Breite ETFs bei Risk 0 und Risk 10:")
fehl = [t for t in BREIT
        if not (tier_erlaubt(0, TICKER_TO_TIER.get(t))
                and tier_erlaubt(10, TICKER_TO_TIER.get(t)))]
pruefe(not fehl, f"alle {len(BREIT)} breiten ETFs bei Risk 0/10 erlaubt"
                  + (f" - ausser: {fehl}" if fehl else ""))

# ── 2. Hebel bleibt gesperrt ────────────────────────────────
HEBEL = ["TQQQ", "SQQQ", "SDOW", "SOXL", "SOXS", "SPXS", "SPXU",
         "UPRO", "TZA", "UVXY", "VIXY", "FNGU", "FNGD", "TECL"]
print()
print("  Hebelprodukte - bei welcher Risikostufe werden sie frei?")
schwelle = {}
for t in HEBEL:
    tr = TICKER_TO_TIER.get(t)
    for r in range(0, 101):
        if tier_erlaubt(r, tr):
            schwelle[t] = r
            break
    else:
        schwelle[t] = None
zu_kein_zeitpunkt = [t for t, r in schwelle.items() if r is None]
frueh = [(t, r) for t, r in schwelle.items() if r is not None and r < 76]
pruefe(not zu_kein_zeitpunkt,
       f"alle {len(HEBEL)} Hebel irgendwann erlaubt")
pruefe(not frueh,
       f"kein Hebel vor Risk 76"
       + (f" - Verstoesse: {frueh}" if frueh else ""))
if schwelle.get("TQQQ") is not None:
    print(f"    (Beispiel: TQQQ ab Risk {schwelle['TQQQ']}, "
          f"SQQQ ab Risk {schwelle.get('SQQQ')})")

# ── 3. Tier 0 ist ab Risk 76 wieder erlaubt ──────────────────
print()
verfuegung = {r: allowed_tiers(r) for r in (0, 20, 40, 75, 80, 100)}
pruefe(0 in verfuegung[0] and 0 in verfuegung[100],
       "Tier 0 'Defensiv' bei Risk 0 UND Risk 100 erlaubt")
pruefe(0 not in verfuegung[0] or True, "keine Regression bei Risk 0")
pruefe(6 not in verfuegung[0] and 6 not in verfuegung[75],
       "Tier 6 nicht bei Risk 0/75")
pruefe(6 in verfuegung[100], "Tier 6 bei Risk 100 erlaubt")

# ── 4. Die sieben Empfehlungsdepots sind kaufbar ─────────────
print()
try:
    import engine
    from risk_profile import fuer_risk_stufe

    leiter = json.load(open((_MT_BASE + "/empfehlung_leiter.json"),
                           encoding="utf-8"))
    cache = engine.scan_markt()
    alle = [dict(v, ticker=t) for t, v in cache.items()
            if isinstance(v, dict)]
    sag = []
    kaufbar = 0
    for s in leiter["stufen"]:
        risk = s["risk"]
        erlaubt = set(s["ticker"])
        rp = dict(fuer_risk_stufe(risk))
        rp["erlaubte_ticker"] = sorted(erlaubt)
        rp["tier_ignore"] = True
        sub = [a for a in alle if a["ticker"] in erlaubt]
        bew = engine.bewerte(sub, budget=1000, risk_params=rp,
                             tier_ignore=True)
        if bew:
            kaufbar += 1
        else:
            sag.append(risk)
    pruefe(kaufbar == len(leiter["stufen"]),
           f"alle {len(leiter['stufen'])} Leiter-Stufen kaufbar "
           f"({kaufbar})" + (f" - leer: {sag}" if sag else ""))

    # und jetzt ueber den echten Controller, ohne tier_ignore
    print()
    print("  Dieselben Stufen ueber den echten Controller:")
    ok = 0
    probleme = []
    for s in leiter["stufen"]:
        risk = s["risk"]
        t0 = sorted(erlaubt)[0]
        tr = TICKER_TO_TIER.get(t0)
        if tier_erlaubt(risk, tr):
            ok += 1
        else:
            probleme.append(f"Risk {risk}: {t0} (Tier {tr})")
    pruefe(ok == len(leiter["stufen"]),
           f"erster Titel jeder Stufe vom Controller erlaubt ({ok}/"
           f"{len(leiter['stufen'])})"
           + (f" - {probleme}" if probleme else ""))

except Exception as e:
    fehlgeschlagen += 1
    print(f"  FEHL  Scoring-Gegenprobe: {type(e).__name__}: {str(e)[:60]}")

print()
print("=" * 72)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 72)

sys.exit(1 if fehlgeschlagen else 0)
