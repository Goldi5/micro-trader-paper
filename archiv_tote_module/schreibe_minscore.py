"""Kalibrierte min_score in die Empfehlung schreiben.

BEFUND DER MESSUNG:
  Die alten min_score-Werte (25-50) stammen aus einer Zeit, in der
  die Tiers [0,1] ausschliesslich Aktien zuliessen. Mit der
  ETF-Empfehlung sind die unteren Schwellen systematisch
  unerreichbar: Risk 10 verlangt 47, der beste ETF erreicht 17,6.

  Die Werte sind depot- und nicht weltweit gueltig, weil sie sich
  auf das jeweilige Titeluniversum beziehen. Deshalb gehoeren sie
  in die Empfehlung und nicht global in risk_profile.

BERECHNUNG (kaltibrier_minscore.py, Exit 0):
    schwelle = max(bester_titel * 0.55, depot_mittel * 0.60)

Ergebnis alt -> neu, wie viele Titel kaufbar sind:
    Risk 10   47 ->  9,7    0 -> 3 Titel
    Risk 25   42 -> 11,9    0 -> 3 Titel
    Risk 40   37 -> 17,8    0 -> 3 Titel
    Risk 55   32 -> 21,4    4 -> 4 Titel
    Risk 70   27 -> 24,1    4 -> 4 Titel
    Risk 85   25 -> 26,7    6 -> 6 Titel
    Risk 95   25 -> 28,3    7 -> 5 Titel

Risk 95 verliert zwei Titel, weil die jetzt unter dem Mittel
liegen. Das ist gewollt: der Filter soll auch dort noch etwas
aussortieren.

Die Werte sind ein Vorschlag aus einer Messung an einem
Marktstand. Sie muessen im Paper-Lauf bestaetigt werden und sind
kein Beleg fuer eine funktionierende Strategie.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, "/opt/micro-trader")
os.chdir("/opt/micro-trader")

import engine
from risk_profile import fuer_risk_stufe

FAKTOR = 0.55
BODEN = 0.60

EMP_PFAD = "/opt/micro-trader/empfehlung_depotreihe.json"
DEPOT_PFAD = "/opt/micro-trader/depot_umwandeln.py"

cache = engine.scan_markt()
with open(EMP_PFAD, encoding="utf-8") as f:
    emp = json.load(f)


def scores_fuer(dp):
    rp = dict(fuer_risk_stufe(dp["risk"]))
    rp["erlaubte_ticker"] = dp["ticker"]
    rp["min_score"] = -999
    sub = [dict(cache[t], ticker=t) for t in dp["ticker"] if t in cache]
    return engine.bewerte(sub, budget=1000, risk_params=rp,
                          tier_ignore=True)


print("=" * 74)
print(" KALIBRIERTE min_score IN DIE EMPFEHLUNG")
print("=" * 74)
print()

geaendert = 0
for dp in emp["depots"]:
    bew = scores_fuer(dp)
    sc = [b["score"] for b in bew]
    if not sc:
        continue
    bester = max(sc)
    mittel = sum(sc) / len(sc)
    neu = round(max(bester * FAKTOR, mittel * BODEN), 1)
    alt = fuer_risk_stufe(dp["risk"])["min_score"]
    dp["min_score_kalibriert"] = neu
    dp["min_score_alt"] = alt
    dp["score_bezug"] = {
        "bester_titel": round(bester, 1),
        "depot_mittel": round(mittel, 1),
        "berechnung": f"max({bester:.1f} x {FAKTOR}, "
                      f"{mittel:.1f} x {BODEN}) = {neu}",
    }
    dp["tier_ignore"] = True
    n_neu = sum(1 for s in sc if s >= neu)
    n_alt = sum(1 for s in sc if s >= alt)
    print(f"  Risk {dp['risk']:2d}: {alt:>4} -> {neu:>5}   "
          f"kaufbar {n_alt} -> {n_neu} von {len(sc)}")

emp["kalibrierung"] = {
    "erstellt_am": datetime.now().isoformat(timespec="seconds"),
    "faktor_relativ": FAKTOR,
    "boden_relativ": BODEN,
    "regel": "min_score = max(bester_titel * 0.55, depot_mittel * 0.60)",
    "gilt_fuer": "nur Depots mit erlaubte_ticker (Whitelist)",
    "nicht_gilt_fuer": "Depots ohne Whitelist - dort bleiben die "
                       "Werte aus risk_profile unveraendert",
    "marktstand": "25.09.2026",
    "vorbehalt": "Aus einer Messung an einem Marktstand abgeleitet. "
                 "Kein Beleg fuer eine funktionierende Strategie. "
                 "Im Paper-Lauf zu bestaetigen.",
}

with open(EMP_PFAD, "w", encoding="utf-8") as f:
    json.dump(emp, f, ensure_ascii=False, indent=2)
print()
print(f"  {EMP_PFAD} aktualisiert, {geaendert} Depots")

# Gegenprobe
with open(EMP_PFAD, encoding="utf-8") as f:
    test = json.load(f)
fehler = 0
for dp in test["depots"]:
    if "min_score_kalibriert" not in dp or "tier_ignore" not in dp:
        print(f"  Risk {dp['risk']}: unvollstaendig")
        fehler += 1
print(f"  Gegenprobe: {len(test['depots'])} Depots, {fehler} unvollstaendig")
sys.exit(1 if fehler else 0)
