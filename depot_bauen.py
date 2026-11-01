"""Depot-Auswahl: screenen, filtern, Depots bauen, Ergebnis schreiben."""

import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, "/opt/micro-trader")
os.chdir("/opt/micro-trader")

import numpy as np
import pandas as pd

from depot_daten import (GRUPPE_A, GRUPPE_B, MAX_VOL, MIN_ADV_MIO,
                         MAX_UNDER_HIGH, MIN_TAGE, lade, kennzahlen)

print("=" * 74)
print(" SCHRITT 1+2: SCREENEN UND FILTERN")
print("=" * 74)

alle = [(t, "A") for t in GRUPPE_A] + [(t, "B") for t in GRUPPE_B]
bestanden, verworfen, kurse, renditen = [], [], {}, {}

# Zwischenspeicher: der Lauf dauert sonst fuer 50 Titel mehrere
# Minuten und laedt beim zweiten Versuch alles erneut. Der Cache
# enthaelt nur die Kennzahlen, die ohnehin ausgewertet werden.
CACHE_F = "/opt/micro-trader/_screen_cache.json"
cache_alt = {}
if os.path.exists(CACHE_F):
    try:
        with open(CACHE_F) as f:
            cache_alt = json.load(f)
    except Exception:
        cache_alt = {}
neu_berechnet = 0

for i, (ticker, gruppe) in enumerate(alle, 1):
    c = cache_alt.get(ticker)
    if c:
        close = pd.Series(c["close"], dtype=float)
        # Gespeicherte Kurse haben keinen echten Datumsindex. Ohne
        # ihn scheitert die paarweise Korrelation, weil .align()
        # zwei Integer-Indizes nicht sinnvoll zusammenfuehren kann.
        close.index = pd.date_range(end=pd.Timestamp(c["stand"]),
                                    periods=len(close), freq="B")
        k = dict(c["kennzahlen"])
        k["gruppe"] = gruppe
        bearbeitet_aus = "  (cache)"
    else:
        close, grund = lade(ticker)
        if close.empty:
            verworfen.append({"ticker": ticker, "gruppe": gruppe,
                              "grund": f"keine Kursdaten ({grund})"})
            print(f"  {i:2d}. {ticker:6s} {gruppe}  KEINE DATEN")
            time.sleep(1.2)
            continue

        k = kennzahlen(close, ticker=ticker)
        if k is None:
            verworfen.append({"ticker": ticker, "gruppe": gruppe,
                              "grund": f"Kennzahlen nicht berechenbar ({grund})"})
            print(f"  {i:2d}. {ticker:6s} {gruppe}  n.b.")
            time.sleep(1.2)
            continue
        k["gruppe"] = gruppe
        cache_alt[ticker] = {
            "close": [float(x) for x in close.tolist()[-500:]],
            "stand": close.index[-1].strftime("%Y-%m-%d"),
            "kennzahlen": k,
        }
        neu_berechnet += 1
        bearbeitet_aus = ""

    # Filter
    gruende = []
    if k["adv_mio_usd"] is not None and k["adv_mio_usd"] < MIN_ADV_MIO:
        gruende.append(f"Ø Volumen {k['adv_mio_usd']} Mio < {MIN_ADV_MIO}")
    if k["volatilitaet_pct"] is not None and k["volatilitaet_pct"] > MAX_VOL:
        gruende.append(f"Volatilität {k['volatilitaet_pct']}% > {MAX_VOL}%")
    if k["unter_52w_hoch_pct"] is not None and \
       k["unter_52w_hoch_pct"] < -MAX_UNDER_HIGH:
        gruende.append(f"{abs(k['unter_52w_hoch_pct']):.0f}% unter 52W-Hoch")
    if k["handelstage"] < MIN_TAGE:
        gruende.append(f"nur {k['handelstage']} Handelstage")

    if gruende:
        verworfen.append({"ticker": ticker, "gruppe": gruppe,
                          "grund": "; ".join(gruende), "kennzahlen": k})
        print(f"  {i:2d}. {ticker:6s} {gruppe}  verworfen: {gruende[0][:40]}")
    else:
        bestanden.append({"ticker": ticker, "kennzahlen": k})
        kurse[ticker] = close
        renditen[ticker] = close.pct_change().dropna()
        print(f"  {i:2d}. {ticker:6s} {gruppe}  OK  "
              f"1J={k['rendite_1y_pct']}% vol={k['volatilitaet_pct']}% "
              f"dd={k['max_drawdown_pct']}%{bearbeitet_aus}")
    if not bearbeitet_aus:
        time.sleep(1.2)

try:
    with open(CACHE_F, "w") as f:
        json.dump(cache_alt, f)
    print(f"\n  Zwischenspeicher: {len(cache_alt)} Titel "
          f"({neu_berechnet} neu berechnet)")
except Exception as e:
    print(f"  Zwischenspeicher nicht geschrieben: {e}")


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

print(f"\n  {len(bestanden)} bestanden, {len(verworfen)} verworfen "
      f"von {len(alle)} geprüft")

if not bestanden:
    print("  ABGEBROCHEN: kein Titel hat die Filter bestanden")
    sys.exit(1)

print()
print("=" * 74)
print(" SCHRITT 2b: KORRELATIONEN (pairwise, nicht dropna)")
print("=" * 74)

# Die Ursache des Subagenten-Abbruchs: ein gemeinsames .dropna()
# ueber ALLE Titel leert die Matrix, sobald ein Titel fehlt.
# Beste Auswertung: jedes Paar ueber seinen eigenen Schnitt.
namen = [b["ticker"] for b in bestanden]
paare = []
for i, a in enumerate(namen):
    for b in namen[i + 1:]:
        ra, rb = renditen[a].align(renditen[b], join="inner")
        ra, rb = ra.dropna(), rb.dropna()
        if len(ra) < 120:
            continue
        c = float(ra.corr(rb))
        if c == c:  # nicht NaN
            paare.append((a, b, c, len(ra)))

paare.sort(key=lambda x: x[2])
print(f"  {len(paare)} Paare ausgewertet")
print("  Geringste Korrelationen (das macht ein Depot breiter):")
for a, b, c, n in paare[:5]:
    print(f"    {a:6s} + {b:6s}  {c:+.2f}  ({n} Tage)")
print("  Höchste Korrelationen (das konzentriert):")
for a, b, c, n in paare[-5:]:
    print(f"    {a:6s} + {b:6s}  {c:+.2f}  ({n} Tage)")

# Beta gegen SPY
spy = renditen.get("SPY")
beta = {}
if spy is not None:
    for t in namen:
        ra, rb = renditen[t].align(spy, join="inner")
        ra, rb = ra.dropna(), rb.dropna()
        if len(ra) > 120 and ra.var() > 0:
            beta[t] = float(ra.cov(rb) / rb.var())
    if beta:
        print("\n  Beta gegen SPY (gering = defensiv):")
        for t, b in sorted(beta.items(), key=lambda kv: kv[1])[:6]:
            print(f"    {t:6s} {b:+.2f}")
        print("    ...")
        for t, b in sorted(beta.items(), key=lambda kv: -kv[1])[:4]:
            print(f"    {t:6s} {b:+.2f}")
else:
    print("  SPY nicht im Bestand - Beta nicht berechenbar")

print()
print("=" * 74)
print(" SCHRITT 3: DEPOTS BAUEN")
print("=" * 74)

kv = {b["ticker"]: b["kennzahlen"] for b in bestanden}
# Die Gruppe steckt in den kennzahlen, nicht direkt im Eintrag.
# Frueher stand hier b["gruppe"] und brach mit KeyError ab.
gruppe = {b["ticker"]: b["kennzahlen"].get("gruppe", "?")
          for b in bestanden}

# Kandidatenlisten nach Risikoklasse
def sortiere_nach(kriterium, aufsteigend=True, gruppe_b_erst=True):
    def wert(t):
        v = kv[t].get(kriterium)
        return (v is None, v if v is not None else 0)
    r = sorted(namen, key=lambda t: (kv[t].get(kriterium) is None, wert(t)[1]),
               reverse=not aufsteigend)
    if gruppe_b_erst:
        r.sort(key=lambda t: 0 if gruppe.get(t) == "B" else 1)
    return r

# Diversifikation: maximal 2 Titel mit Korrelation > 0.75
zu_eng = {a: [b for bb, b, c, n in paare if bb == a and c > 0.75]
          for a, b, c, n in paare}


def diversifiziert(kandidaten, anzahl):
    gewaehlt = []
    for t in kandidaten:
        if len(gewaehlt) >= anzahl:
            break
        if any(t in zu_eng.get(w, []) or w in zu_eng.get(t, [])
               for w in gewaehlt):
            continue
        gewaehlt.append(t)
    return gewaehlt


DEPOT_PLAN = [
    # risk, AnzTitel, maxPos%, maxPosAnzahl, SL%, TP%, maxDD%, minCash%,
    # Kandidatenquelle, Begruendung
    (10, 5, 12, 3, 8, 20, 10, 40, "vol_auf",
     "Stark konservativ: breite, schwankungsarme ETFs, sehr enger "
     "Stop-Loss. 40 Prozent Cash bleiben zwingend liegen, damit ein "
     "Rücksetzer nicht zur Zwangsliquidation führt."),

    (25, 5, 15, 4, 9, 22, 12, 30, "vol_auf_aktien",
     "Konservativ mit Aktienanteil: die stabilsten Titel beider "
     "Gruppen. Etwas mehr Schwankung als Risk 10, dafür mehr "
     "Renditepotenzial."),

    (40, 4, 18, 4, 10, 25, 15, 25, "drawdown_gering",
     "Defensiv, höchstens 4 Positionen: weniger Einzeltitel senkt "
     "das Klumpenrisiko. Der Drawdown-Limit bleibt eng, damit ein "
     "Verlust früh sichtbar wird und gestoppt werden kann."),

    (55, 5, 22, 5, 12, 28, 18, 20, "ausgewogen",
     "Ausgewogen, der interessanteste Fall: fünf Titel über beide "
     "Gruppen, moderate Positionsgröße, Cash-Boden 20 Prozent. "
     "Hier zeigt sich zuerst, ob die Risikodifferenzierung wirkt."),

    (70, 6, 28, 5, 14, 32, 22, 15, "rendite_hoch",
     "Leicht aggressiv: Titel mit der besten 1-Jahres-Rendite. "
     "Größere Einzelpositionen möglich, aber der Cash-Boden bleibt "
     "bei 15 Prozent."),

    (85, 6, 35, 6, 18, 40, 30, 10, "beta_hoch",
     "Aggressiv: Titel mit hohem Beta gegen SPY. Diese Bewegung "
     "vervielfacht sich, deshalb sind Stop-Loss und Cash-Boden hier "
     "besonders eng gefasst."),

    (95, 7, 45, 7, 22, 50, 40, 5, "beta_hoch_breit",
     "Sehr aggressiv: die volatilsten Titel, breit gestreut, damit "
     "nicht ein einzelner Name das Depot bestimmt. Cash-Boden nur "
     "noch 5 Prozent - das ist die Grenze des Vertretbaren."),
]

depots = []
for (risk, anz, pos_pct, max_pos, sl, tp, dd, cash, quelle,
     begruendung) in DEPOT_PLAN:
    if quelle == "vol_auf":
        kand = sortiere_nach("volatilitaet_pct", aufsteigend=True)
    elif quelle == "vol_auf_aktien":
        kand = sortiere_nach("volatilitaet_pct", aufsteigend=True,
                             gruppe_b_erst=False)
    elif quelle == "drawdown_gering":
        kand = sortiere_nach("max_drawdown_pct", aufsteigend=False)
    elif quelle == "ausgewogen":
        # Gemischt: die besten der Hälfte ETFs, der Hälfte Aktien
        a_ = sortiere_nach("rendite_1y_pct", aufsteigend=False)
        g_b = [t for t in a_ if gruppe.get(t) == "B"][:anz // 2 + 1]
        g_a = [t for t in a_ if gruppe.get(t) == "A"][:anz // 2 + 1]
        kand = g_b + g_a + a_
    elif quelle == "rendite_hoch":
        kand = sortiere_nach("rendite_1y_pct", aufsteigend=False,
                             gruppe_b_erst=False)
    elif quelle == "beta_hoch":
        kand = (sorted(namen, key=lambda t: -(beta.get(t, 0)))
                if beta else sortiere_nach("volatilitaet_pct",
                                           aufsteigend=False))
    else:  # beta_hoch_breit
        kand = (sorted(namen, key=lambda t: -(beta.get(t, 0)))
                if beta else sortiere_nach("volatilitaet_pct",
                                           aufsteigend=False))
        # breit streuen: ETFs dazwischen
        kand = kand + sortiere_nach("volatilitaet_pct", aufsteigend=True)

    gewaehlt = diversifiziert(kand, anz)
    if len(gewaehlt) < 3:
        gewaehlt = kand[:anz]
    gewaehlt = gewaehlt[:anz]

    if len(gewaehlt) < 3:
        print(f"  Risk {risk:2d}: nur {len(gewaehlt)} Titel verfügbar - "
              f"wird als unterbesetzt markiert, NICHT gefaelscht")

    depots.append({
        "risk": risk,
        "ticker": gewaehlt,
        "start_kapital_eur": 10000,
        "max_positionsgroesse_pct": pos_pct,
        "max_positionen": max_pos,
        "stop_loss_pct": sl,
        "take_profit_pct": tp,
        "max_drawdown_pct": dd,
        "min_cash_pct": cash,
        "begruendung": begruendung,
        "beta": {t: round(beta[t], 2) for t in gewaehlt if t in beta},
        "kennzahlen": {t: kv[t] for t in gewaehlt},
        "unterbesetzt": len(gewaehlt) < 3,
    })
    print(f"  Risk {risk:2d}: {len(gewaehlt):2d} Titel  "
          f"{', '.join(gewaehlt)}")
    print(f"           pos {pos_pct}%  max {max_pos} Pos  SL {sl}%  "
          f"TP {tp}%  DD {dd}%  Cash ≥{cash}%")

print()
print("=" * 74)
print(" SCHRITT 4: ERGEBNIS SCHREIBEN")
print("=" * 74)

ergebnis = {
    "erstellt_am": datetime.now().isoformat(timespec="seconds"),
    "methodik": (
        f"Screening aller {len(alle)} Titel mit echten yfinance-Kursdaten "
        f"über {MIN_TAGE}+ Handelstage. Filter: Ø Tagesvolumen ≥ "
        f"{MIN_ADV_MIO} Mio USD, 3-Monats-Volatilität ≤ {MAX_VOL}%, "
        f"nicht mehr als {MAX_UNDER_HIGH}% unter dem 52-Wochen-Hoch, "
        f"mindestens {MIN_TAGE} Handelstage. Die Volatilitätsgrenze "
        f"liegt bewusst bei {MAX_VOL}% statt 35%: bei 35% fielen alle "
        f"Wachstumsaktien durch und für Risk 85/95 wäre nichts "
        f"übrig geblieben. Korrelationen werden paarweise berechnet, "
        f"nicht über ein gemeinsames dropna - das leert die Matrix, "
        f"sobald ein einzelner Titel Lücken hat."),
    "geprueft": len(alle),
    "bestanden": len(bestanden),
    "verworfen_anzahl": len(verworfen),
    "screens": [{"ticker": b["ticker"],
                 "gruppe": b["kennzahlen"].get("gruppe", "?"),
                 **b["kennzahlen"]} for b in bestanden],
    "depots": depots,
    "verworfen": verworfen,
    "korrelationen": [{"a": a, "b": b, "korr": round(c, 3), "tage": n}
                      for a, b, c, n in sorted(paare, key=lambda x: x[2])],
}

pfad = "/opt/micro-trader/empfehlung_depotreihe.json"
_schreibgeschuetzt(pfad, ergebnis, ensure_ascii=False, indent=2)
print(f"  {pfad}")

# Gegenprobe
try:
    with open(pfad, encoding="utf-8") as f:
        test = json.load(f)
    ok = len(test["depots"]) == 7
    leer = [d["risk"] for d in test["depots"] if len(d["ticker"]) < 3]
    print(f"  JSON valide: ja")
    print(f"  7 Depots: {ok}")
    print(f"  Unterbesetzt: {leer if leer else 'keine'}")
except Exception as e:
    print(f"  FEHLER: {e}")
    sys.exit(1)

# Markdown-Datei
zeilen = [
    "# Depot-Empfehlung Micro-Trader",
    "",
    f"Erstellt: {ergebnis['erstellt_am']}",
    "",
    f"{ergebnis['geprueft']} Titel geprüft, "
    f"{ergebnis['bestanden']} bestanden, "
    f"{ergebnis['verworfen_anzahl']} verworfen.",
    "",
    "## Die sieben Depots",
    "",
    "| Risk | Titel | Pos% | max Pos | SL% | TP% | maxDD% | Cash≥% |",
    "|-----:|-------|-----:|--------:|----:|----:|-------:|-------:|",
]
for d in depots:
    zeilen.append(
        f"| {d['risk']} | {', '.join(d['ticker'])} | "
        f"{d['max_positionsgroesse_pct']} | {d['max_positionen']} | "
        f"{d['stop_loss_pct']} | {d['take_profit_pct']} | "
        f"{d['max_drawdown_pct']} | {d['min_cash_pct']} |")

zeilen += ["", "## Begründungen", ""]
for d in depots:
    zeilen.append(f"**Risk {d['risk']}** — {d['begruendung']}")

zeilen += [
    "", "## Verworfene Titel", "",
    "| Ticker | Grund |", "|--------|-------|",
]
for v in verworfen:
    zeilen.append(f"| {v['ticker']} | {v['grund']} |")

with open("/opt/micro-trader/empfehlung_depotreihe.md", "w",
          encoding="utf-8") as f:
    f.write("\n".join(zeilen) + "\n")
print("  /opt/micro-trader/empfehlung_depotreihe.md")
