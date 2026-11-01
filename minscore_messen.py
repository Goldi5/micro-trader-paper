"""min_score fuer die NEUE Leiter messen.

ANLASS:
  leiter_einspielen.py hat min_score=-999 geschrieben, weil die
  kalibrierten Werte nur in einer Git-Fassung von
  empfehlung_depotreihe.json standen (Commit a10f323) und nicht
  im aktuellen Stand. Sie zu uebernehmen waere falsch: sie
  wurden fuer die ALTE Titelwahl gemessen, und die Leiter hat
  andere Titel.

  Die kalibrierte_logik (aus der Messung vom 27.09.):
      min_score = 40 % des besten erreichbaren Scores der Stufe

  Diese Logik muss auf die neuen Titel angewendet werden. Also:
  erst messen, dann den Wert schreiben.

VORGEHEN:
  1. Alle Titel der Leiter aus dem Markt-Cache laden.
  2. Je Risikostufe mit der echten Tier-Freigabe bewerten.
  3. Besten erreichbaren Score nehmen.
  4. min_score = 40 % davon, mit einer Mindestuntergrenze, damit
     ein Titel mit fast null Score nicht plötzlich durchkommt.
"""

import json
import os
import sys

sys.path.insert(0, "/opt/micro-trader")
os.chdir("/opt/micro-trader")

import engine
from risk_controller import params as rc_params
from risk_profile import fuer_risk_stufe

# --- Schreibschutz gegen versehentliches Ueberschreiben (2026-09-27) ---
#
# Anlass: Laeufe dieses Werkzeugs haben eine bereits verifizierte
# Empfehlungsdatei ersetzt, ohne dass ein Test es bemerkte. Ohne
# Sperre heisst jeder Aufruf "ersetzt die gepruefte Basis".
#
# Mit --force wird wie zuvor geschrieben. Ohne --force liegt der
# neue Lauf in <ziel>.neu und die verifizierte Datei bleibt
# unangetastet.
import sys as _sys
import os as _os

def _schreibgeschuetzt(ziel, inhalt, **kw):
    """Schreibt nach ziel, aber nur mit --force. Sonst nach ziel.neu."""
    import json as _json
    if not _os.path.exists(ziel) or "--force" in _sys.argv:
        with open(ziel, "w", encoding="utf-8") as f:
            _json.dump(inhalt, f, **kw)
        return True
    _neu = str(ziel) + ".neu"
    with open(_neu, "w", encoding="utf-8") as f:
        _json.dump(inhalt, f, **kw)
    print("  GESPERRT: %s existiert bereits." % ziel)
    print("           Neuer Lauf liegt in %s" % _neu)
    print("           Ueberschreiben nur mit --force.")
    _sys.exit(2)


ANTEIL = 0.40
MINDEST = 5.0

print("=" * 72)
print(" min_score fuer die neue Leiter messen")
print("=" * 72)
print()

leiter = json.load(open("empfehlung_leiter.json", encoding="utf-8"))
cache = engine.scan_markt()
alle = [dict(v, ticker=t) for t, v in cache.items() if isinstance(v, dict)]
print(f"  Markt-Cache: {len(alle)} Titel")
print()

ergebnis = {}

for stufe in leiter["stufen"]:
    risk = stufe["risk"]
    erlaubt = set(stufe["ticker"])

    rp = dict(fuer_risk_stufe(risk))
    rp["erlaubte_ticker"] = sorted(erlaubt)
    rp["tier_ignore"] = True

    sub = [a for a in alle if a["ticker"] in erlaubt]
    fehlen = sorted(erlaubt - {a["ticker"] for a in sub})
    bew = engine.bewerte(sub, budget=1000, risk_params=rp, tier_ignore=True)

    if not bew:
        # Ergaenzen: ohne Kursdaten ist keine Bewertung moeglich.
        # Ein zu niedriger min_score waere schlimmer als gar keiner.
        print(f"  Risk {risk:2d}: KEINE bewertbaren Titel "
              f"({len(sub)}/{len(erlaubt)} im Cache)")
        if fehlen:
            print(f"           fehlend: {','.join(fehlen)}")
        continue

    bester = bew[0]
    ms = max(MINDEST, round(bester["score"] * ANTEIL, 1))

    ergebnis[risk] = ms
    print(f"  Risk {risk:2d}: {len(bew):2d}/{len(erlaubt)} bewertbar  "
          f"bester={bester['score']:5.1f} ({bester['ticker']})  "
          f"-> min_score={ms}")
    if fehlen:
        print(f"           ohne Kursdaten: {','.join(fehlen)}")

print()
print(f"  Ergebnis: {ergebnis}")

# In die Leiter-Datei schreiben, damit die Quelle stimmt
leiter["min_score"] = {str(k): v for k, v in ergebnis.items()}
leiter["min_score_herkunft"] = (
    f"40 % des besten erreichbaren Scores je Stufe, "
    f"Mindestgrenze {MINDEST}, gemessen am "
    f"Leiter-Titelbestand")
_schreibgeschuetzt("empfehlung_leiter.json", leiter, ensure_ascii=False, indent=2)
print("  -> empfehlung_leiter.json aktualisiert")

_schreibgeschuetzt("min_score_leiter.json", ergebnis, ensure_ascii=False, indent=2)
print("  -> min_score_leiter.json geschrieben")
