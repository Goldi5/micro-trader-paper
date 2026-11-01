"""Neue Leiter in lauffaehige Paper-Depots umwandeln.

GRUND: empfehlung_leiter.json hat harte Nebenbedingungen
(maxrho <= 0,75, Anteil <= 30 %, erzwungene Monotonie) und ersetzt
die alte Empfehlung, die Risk 95 zu 96 % Korrelation hatte.

Die Leiter ist ausschliesslich eine Titelempfehlung. min_score
kommt weiterhin aus der alten Empfehlung, weil die Leiter keine
Kalibrierung enthaelt - die wurde fuer die alte Auswahl gemessen
und gilt unveraendert, die Titel sind nur anders.

ACHTUNG wie bei depot_umwandeln.py:
  ZIEL muss spec_depots_paper sein. batch_trader.py sammelt seine
  Depots ueber
      glob.glob(os.path.join(BASE, "spec_depots_paper", "*.json"))
  und sucht NICHT rekursiv. Ein Unterordner wuerde nie gelesen.
"""

import json
import os
import sys
from datetime import datetime, timezone

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


BASIS = os.path.dirname(os.path.abspath(__file__))  # war fest "/opt/micro-trader" (01.11.2026)
QUELLE = f"{BASIS}/empfehlung_leiter.json"
ALT_QUELLE = f"{BASIS}/empfehlung_depotreihe.json"
ZIEL = f"{BASIS}/spec_depots_paper"
LOG = f"{BASIS}/_umwandlung.log"

bestehend = []


def sag(t):
    print(t, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(t + "\n")


sag("")
sag("=" * 72)
sag(f" Leiter -> Paper-Depots   ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
sag("=" * 72)
sag("")

with open(QUELLE, encoding="utf-8") as f:
    leiter = json.load(f)
with open(ALT_QUELLE, encoding="utf-8") as f:
    alt = json.load(f)

# min_score aus der Leiter-Datei. Die Werte wurden per
# minscore_messen.py fuer DIESEN Titelbestand gemessen (40 % des
# besten erreichbaren Scores, Mindestgrenze 5).
#
# NICHT aus empfehlung_depotreihe.json uebernehmen: dort standen
# die kalibrierten Werte nur in der Git-Fassung a10f323, und sie
# galten fuer die alte Titelwahl. Die Titel haben sich geaendert,
# also musste neu gemessen werden - sonst waere der Wert eine
# Zahl ohne Bedeutung.
min_scores = {int(k): v for k, v in (leiter.get("min_score") or {}).items()}
if not min_scores:
    sag("  ABBRUCH: empfehlung_leiter.json enthaelt keine min_score.")
    sag("  Zuerst minscore_messen.py laufen lassen.")
    raise SystemExit(1)
sag(f"  min_score aus der Leiter (fuer diese Titel gemessen): {min_scores}")
sag(f"  Herkunft: {leiter.get('min_score_herkunft', 'unbekannt')}")
sag(f"  Ziel: {ZIEL}")
sag("")

os.makedirs(ZIEL, exist_ok=True)

neu = 0
for stufe in leiter["stufen"]:
    risk = stufe["risk"]
    ticker = list(stufe["ticker"])
    pfad = os.path.join(ZIEL, f"depot_{risk:03d}.json")

    jetzt = datetime.now(timezone.utc).isoformat()
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            alt_d = json.load(f)
        # Bestehende Positionen und Historie erhalten - das Depot
        # soll weiterlaufen, nicht neu anfangen
        start_wert = alt_d.get("start_wert", 10000.0)
        positionen = alt_d.get("positions") or {}
        historie = alt_d.get("historie") or []
        trades = alt_d.get("trades") or []
        bargeld = alt_d.get("bargeld", start_wert)
        bestehend.append((risk, len(positionen), len(trades)))
    else:
        start_wert = 10000.0
        positionen, historie, trades = {}, [], []
        bargeld = start_wert

    ms = min_scores.get(risk, -999)

    depot = {
        "tenant_id": "default",
        "risk": risk,
        "start_wert": start_wert,
        "bargeld": round(float(bargeld), 2),
        "max_positions": 3,
        "mode": "paper",
        "name": f"Risk {risk} (Leiter)",
        "erstellt": alt.get("erstellt_am") or jetzt,
        "aktualisiert": jetzt,
        "cash_floor": 0.06,
        "positions": positionen,
        "historie": historie,
        "trades": trades,
        "empfehlung": {
            "erstellt_am": leiter["erstellt_am"],
            "erlaubte_ticker": ticker,
            "begruendung": (
                f"Leiter mit harten Nebenbedingungen: "
                f"beta={stufe['beta']}, maxrho={stufe['maxrho']}, "
                f"max_anteil={leiter['max_anteil']}, "
                f"gleich gewichtet"
            ),
            "beta": stufe["beta"],
            "maxrho": stufe["maxrho"],
            "vol_pct": stufe["vol_pct"],
            "engstes_paar": stufe.get("rho_paar"),
            "beta_ziel_erreicht": stufe.get("beta_ziel_erreicht"),
            "min_score": ms,
            "tier_ignore": True,
        },
    }

    _schreibgeschuetzt(pfad, depot, ensure_ascii=False, indent=2)
    neu += 1
    sag(f"  Risk {risk:2d}: {len(ticker):2d} Titel  beta={stufe['beta']:.2f} "
        f"maxrho={stufe['maxrho']:.2f}  min_score={ms}")
    sag(f"          {','.join(ticker)}")

sag("")
if bestehend:
    sag("  Bestehende Depots mit Fortschritt (Positionen bleiben erhalten):")
    for risk, npos, ntr in bestehend:
        sag(f"    Risk {risk:2d}: {npos} Positionen, {ntr} Trades")
sag("")
sag(f"  {neu} Depots geschrieben")
sag("=" * 72)
sys.exit(0)
