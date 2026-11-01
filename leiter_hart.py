"""Depot-Leiter: harte Nebenbedingungen statt nur Beta-Fenster.

ANLASS (Befunde vom 27.09.2026):
  Die bisherige Leiter maximize Beta, Volatilitaet und Rendite.
  Die paarweise Korrelation wurde gemessen, aber nie als
  Nebenbedingung gesetzt. Folge bei Risk 85/95:

      Risk 95: GLD, XLK, EEM, QQQ
      Gewichte [1.0, 8.4, 6.6, 6.0]  -> XLK 38 %, GLD 5 %
      EEM/QQQ korrelieren zu 0,96

  XLK, EEM und QQQ tragen 95 % des Depots und sind dieselbe Wette.
  Risk 10-40 sind dagegen sauber: gleich gewichtet, maxrho 0,44-0,75.

DESIGN:
  Gesucht wird sequentiell von Risk 10 nach oben, damit die
  Monotonie nicht nachtraeglich geprueft, sondern erzwungen wird:
  Risk n+1 muss mindestens so hohe Beta erreichen wie Risk n.

  HARTE NEBENBEDINGUNGEN (der eigentliche Fix):
    1. maxrho <= 0,75 zwischen allen Paaren
    2. kein Einzelanteil ueber MAX_ANTEIL
    3. Beta im Fensters [ziel_lo, 2.20]

  Erfuellt eine Stufe ihr Beta-Ziel nicht, wird das protokolliert
  statt stillschweigend eine schlechtere Auswahl zu nehmen.

DATEN: echte Kurse via yfinance, 1 Jahr taeglich, Stand vom Lauf.
"""

import itertools
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

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


# ── Ziele und Grenzen ──────────────────────────────────────────
# Beta-Zielband je Risikostufe (untere Grenze wird erzwungen,
# die obere ist ein Cap - alles darueber ist kein Diversifikations-
# gewinn, sondern Klumpenrisiko).
ZIEL = {
    10: (0.10, 0.45),
    25: (0.30, 0.65),
    40: (0.45, 0.85),
    55: (0.65, 1.10),
    70: (0.90, 1.35),
    85: (1.15, 1.60),
    95: (1.40, 1.90),
}

MAX_RHO = 0.75        # hoechste erlaubte Paarkorrelation
MAX_ANTEIL = 0.30     # hoechster Einzelanteil im Depot
BENCH = "SPY"

# Universum: die Titel, die in der Empfehlung vorkommen, plus
# Bewerber fuer die Streuung. Krypto-Miner und Pennystocks sind
# ausgeschlossen - sie fielen in frueheren Laeufen durch und haben
# keine saubere Historie.
UNIVERSUM = [
    # breit
    "SPY", "VTI", "VOO", "VYM", "VNQ", "EFA", "EEM", "VEA", "IWM", "DIA",
    # sektor
    "XLK", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLE", "XLC", "XLB",
    "XLU", "VNQ", "SCHD", "RSP",
    # rohstoff / gold
    "GLD", "SLV", "DBC",
    # einzelwerte
    "AAPL", "MSFT", "NVDA", "JNJ", "LLY", "UNH", "XOM", "CVX", "MCD", "HD",
    "PG", "KO", "MRK", "CSCO", "QCOM", "META", "AMZN", "GOOGL", "ABBV",
    "TMO", "LIN", "ACN", "TXN", "AMAT", "MU", "INTC", "ADBE", "CRM", "IBM",
    "WMT", "COST", "PEP", "PM", "MO", "NEE", "DUK", "SO", "CVX",
]

AUSSCHLUSS = {
    # Hebel und Inverse: nie im Paper-Betrieb
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU", "SDOW", "TZA", "UVXY",
    "SOXL", "SOXS", "NVDL", "TMDX", "FNGU", "FNGD",
    # Krypto-Miner und Pennystocks: keine belastbare Historie
    "MARA", "RIOT", "CLSK", "JAGX", "FNV", "SWKS", "ZS", "CLF", "COIN",
    "MSTR", "PGM", "SUM", "BAL", "BLD", "WATER", "ZIV", "CAFE", "COL",
    "SUMO", "LODE", "DYNC", "X", "K",
}

PERIODE = "2y"
MIND_BEISPIELE = 4
MAX_BEISPIELE = 8

# Kurs-Cache: yfinance braucht fuer 62 Titel gut zwei Minuten.
# Ohne Cache ist jeder Lauf unnoetig langsam, und ein Abbruch
# bedeutet, alles neu zu laden.
CACHE = "/opt/micro-trader/.kurs_cache_2y.json"
CACHE_MAX_ALTER = 6 * 3600


def lade(t):
    """Kursreihe und Renditen, oder (None, None) wenn unbrauchbar."""
    try:
        d = yf.download(t, period=PERIODE, auto_adjust=True,
                        progress=False, threads=False)
        if d.empty or "Close" not in d:
            return None, None
        c = d["Close"]
        if hasattr(c, "columns"):
            c = c.iloc[:, 0]
        c = c.dropna()
        if len(c) < 250:
            return None, None
        return c, c.pct_change().dropna()
    except Exception:
        return None, None


def sag(t):
    print(t, flush=True)


def lade_cache():
    """Kursdaten aus dem Cache, falls frisch genug."""
    try:
        if os.path.exists(CACHE) and \
                time.time() - os.path.getmtime(CACHE) < CACHE_MAX_ALTER:
            with open(CACHE, encoding="utf-8") as f:
                roh = json.load(f)
            sag(f"  Kurs-Cache: {len(roh.get('daten', {}))} Titel, "
                f"erstellt {roh.get('erstellt', '?')}")
            return roh
    except Exception as e:
        sag(f"  Cache unbrauchbar ({type(e).__name__}), lade neu")
    return None


def speichere_cache(daten, idx):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({
                "erstellt": datetime.now(timezone.utc).isoformat(),
                "periode": PERIODE,
                "index": [d.strftime("%Y-%m-%d") for d in idx],
                "daten": daten,
            }, f)
        sag(f"  Kurs-Cache geschrieben: {len(daten)} Titel")
    except Exception as e:
        sag(f"  Cache nicht schreibbar: {type(e).__name__}")


def main():
    sag("=" * 74)
    sag(f" Depot-Leiter mit harten Nebenbedingungen  "
        f"({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
    sag("=" * 74)
    sag("")

    # ── 1. Kurse laden ─────────────────────────────────────────
    kandidaten = [t for t in dict.fromkeys(UNIVERSUM)
                  if t not in AUSSCHLUSS]
    sag(f"  Universum: {len(kandidaten)} Titel "
        f"({len(AUSSCHLUSS)} ausgeschlossen)")
    sag("")

    preis, rend = {}, {}

    roh = lade_cache()
    if roh and len(roh.get("daten", {})) >= 20:
        # Renditen direkt aus dem Cache, das spart die
        # Index-Intersection und ist schneller
        daten = roh["daten"]
        for t, reihe in daten.items():
            s = pd.Series(reihe, dtype=float)
            rend[t] = s.pct_change().dropna()
            preis[t] = s
        sag(f"  aus Cache geladen: {len(daten)} Titel")
    else:
        tot = len(kandidaten) + 1
        for i, t in enumerate(kandidaten, 1):
            c, r = lade(t)
            if c is not None:
                preis[t], rend[t] = c, r
                sag(f"  {i:3d}/{tot} {t:6s} OK   {len(c)} Tage  "
                    f"{c.iloc[0]:9.2f} -> {c.iloc[-1]:9.2f}  "
                    f"({c.iloc[-1]/c.iloc[0]-1:+.1%})")
            else:
                sag(f"  {i:3d}/{tot} {t:6s} -- keine Daten")
            time.sleep(0.12)

        # Cache fuellen, damit der naechste Lauf schnell ist
        roh_tmp = {t: [round(float(x), 4) for x in
                       preis[t].reindex(preis[t].index).tolist()]
                   for t in preis}
        speichere_cache(roh_tmp, preis[list(preis)[0]].index)

    sag("")
    sag(f"  verwertbar: {len(preis)} von {len(kandidaten)}")
    if len(preis) < 20:
        sag("  ABBRUCH: zu wenige Daten")
        return 1

    # gemeinsamer Zeitraum, damit die Korrelationen stimmen
    idx = None
    for r in rend.values():
        idx = r.index if idx is None else idx.intersection(r.index)
    if len(idx) < 250:
        sag(f"  ABBRUCH: nur {len(idx)} gemeinsame Handelstage")
        return 1
    R = pd.DataFrame({t: rend[t].reindex(idx) for t in preis}).dropna()
    sag(f"  gemeinsame Handelstage: {len(R)}")
    sag("")

    # Beta je Titel gegen den Benchmark.
    # ACHTUNG: pd.DataFrame aus skalaren Werten braucht einen Index,
    # sonst "ValueError: If using all scalar values, you must pass
    # an index". Ein einfaches dict mit einer Zeile reicht.
    var_bench = R[BENCH].var()
    B = {t: float(R[t].cov(R[BENCH]) / var_bench) for t in R.columns}
    K = R.corr()
    vol = R.std() * (252 ** 0.5)

    # ── 2. Bewertung eines Depots ─────────────────────────────
    def bewerte(titel):
        """Liefert None, wenn harte Nebenbedingungen verletzt sind."""
        titel = list(dict.fromkeys(titel))
        if len(titel) < MIND_BEISPIELE:
            return None
        if len(titel) > MAX_BEISPIELE:
            return None

        # harte Bedingung 1: Korrelation
        mx, paar = 0.0, None
        for a, b in itertools.combinations(titel, 2):
            v = abs(K.loc[a, b])
            if v > mx:
                mx, paar = v, (a, b)
        if mx > MAX_RHO:
            return None

        # gleich gewichtet: verhindert den Klumpenbefund
        anteil = 1.0 / len(titel)
        if anteil > MAX_ANTEIL + 1e-9:
            return None

        # Beta als Mittel der Einzelbetas
        beta = sum(B[t] for t in titel) / len(titel)
        return {
            "ticker": titel,
            "gewichte": [1.0] * len(titel),
            "beta": round(float(beta), 4),
            "maxrho": round(float(mx), 3),
            "rho_paar": list(paar) if paar else None,
            "vol_pct": round(float(vol[titel].mean() * 100), 1),
        }

    def alle_kombis(k, titel):
        return itertools.combinations(titel, k)

    # ── 3. Sequentielle Suche mit erzwungener Monotonie ────────
    # Brute Force ueber alle Kombinationen ist bei 100 Titeln und
    # Breiten 4-8 nicht durchlaufbar (Groessenordnung 10^12).
    # Stattdessen: greedy vom Beta-Ziel her.
    #
    #   - Fuer jede Breite k wird ein Startwert gewaehlt und dann
    #     der Titel ergaenzt, der die Beta der Distanz zum Ziel
    #     naeher bringt.
    #   - Die harten Nebenbedingungen (maxrho, Anteil) werden nach
    #     jedem Hinzufuegen geprueft, nicht nur am Ende.
    titel_liste = sorted(preis)
    stufen, warnungen = [], []
    vorige_beta = 0.0

    sag("  Suche sequentiell, greedy mit Nebenbedingungen "
        "(Monotonie wird erzwungen, nicht geprueft):")
    sag("")

    def beta_von(titel):
        return sum(B[t] for t in titel) / len(titel)

    def passt(titel, k):
        # Anteil nur pruefen, wenn die Zielbreite erreicht ist.
        # Waehrend des Aufbaus ist len(titel) < k, das ist erlaubt.
        if len(titel) > k:
            return False
        if len(titel) == k and 1.0 / len(titel) > MAX_ANTEIL + 1e-9:
            return False
        for a, b in itertools.combinations(titel, 2):
            if abs(K.loc[a, b]) > MAX_RHO:
                return False
        return True

    for risk, (lo, hi) in ZIEL.items():
        lo_eff = max(lo, vorige_beta)
        mitte = (lo_eff + hi) / 2
        bester = None

        for k in range(MIND_BEISPIELE, MAX_BEISPIELE + 1):
            if k > len(titel_liste):
                break
            # Mehrere Startwerte probieren. Ein einzelner Start
            # kann in eine Sackgasse laufen, in der kein weiterer
            # Titel die Nebenbedingungen erfuellt. Die besten 12
            # Startkandidaten werden durchprobiert.
            starts = sorted(titel_liste,
                            key=lambda t: abs(B[t] - mitte))[:12]

            for start in starts:
                titel = [start]

                # Greedy aufbauen: jeweils den Titel nehmen, der
                # die Beta der Distanz zum Ziel naeher bringt.
                # Unter den 5 besten wird der mit der kleinsten
                # Korrelation zum Rest gewaehlt - sonst landet
                # das Depot wieder in einem Klumpen.
                while len(titel) < k:
                    kandidaten = []
                    for t in titel_liste:
                        if t in titel:
                            continue
                        neu = titel + [t]
                        if not passt(neu, k):
                            continue
                        d = abs(beta_von(neu) - mitte)
                        # Korrelation zum vorhandenen Bestand
                        rho_neu = max(abs(K.loc[a, t])
                                      for a in titel)
                        kandidaten.append((d, rho_neu, t, neu))
                    if not kandidaten:
                        break
                    kandidaten.sort(key=lambda x: (x[0], x[1]))
                    # die 5 besten nach Beta-Distanz, daraus der
                    # mit der kleinsten Korrelation
                    auswahl = min(kandidaten[:5],
                                  key=lambda x: (x[1], x[0]))
                    titel = auswahl[3]

                if len(titel) != k:
                    continue
                b = beta_von(titel)
                if not (lo_eff <= b <= hi):
                    continue
                mx = max(abs(K.loc[a, c]) for a, c in
                         itertools.combinations(titel, 2))
                if bester is None or abs(b - mitte) < \
                        abs(bester["beta"] - mitte):
                    engstes = max(
                        itertools.combinations(titel, 2),
                        key=lambda ab: abs(K.loc[ab[0], ab[1]]))
                    bester = {
                        "ticker": sorted(titel),
                        "gewichte": [1.0] * k,
                        "beta": round(float(b), 4),
                        "maxrho": round(float(mx), 3),
                        "rho_paar": [engstes[0], engstes[1]],
                        "vol_pct": round(float(
                            vol[titel].mean() * 100), 1),
                    }

        if bester is None:
            # Beta-Ziel nicht erreichbar: bestes Erreichbares suchen
            bester, erreicht = None, -1.0
            for k in range(MIND_BEISPIELE, MAX_BEISPIELE + 1):
                for start in titel_liste:
                    titel = [start]
                    while len(titel) < k:
                        kandidaten = []
                        for t in titel_liste:
                            if t in titel:
                                continue
                            neu = titel + [t]
                            if not passt(neu, k):
                                continue
                            kandidaten.append((beta_von(neu), t, neu))
                        if not kandidaten:
                            break
                        kandidaten.sort(key=lambda x: -x[0])
                        _, _, titel = kandidaten[0]
                    if len(titel) < k:
                        continue
                    b = beta_von(titel)
                    if b > erreicht and b >= lo_eff:
                        erreicht = b
                        mx = max(abs(K.loc[a, c]) for a, c in
                                 itertools.combinations(titel, 2))
                        engstes = max(
                            itertools.combinations(titel, 2),
                            key=lambda ab: abs(K.loc[ab[0], ab[1]]))
                        bester = {
                            "ticker": sorted(titel),
                            "gewichte": [1.0] * k,
                            "beta": round(float(b), 4),
                            "maxrho": round(float(mx), 3),
                            "rho_paar": [engstes[0], engstes[1]],
                            "vol_pct": round(float(
                                vol[titel].mean() * 100), 1),
                        }
            if bester is not None:
                warnungen.append(
                    f"Risk {risk}: Ziel-beta >= {lo_eff:.2f} nicht "
                    f"erreichbar, bestes {bester['beta']:.2f} gesetzt")
                bester["beta_ziel_erreicht"] = False
            else:
                sag(f"  Risk {risk:2d}: KEINE gueltige Auswahl")
                continue
        else:
            bester["beta_ziel_erreicht"] = True

        bester["risk"] = risk
        bester["beta_fenster"] = [lo, hi]
        bester["beta_untergrenze_erzwungen"] = round(lo_eff, 3)
        stufen.append(bester)
        vorige_beta = bester["beta"]

        sag(f"  Risk {risk:2d}  beta={bester['beta']:.2f} "
            f"(Band {lo:.2f}-{hi:.2f}, erzwungen ab {lo_eff:.2f})  "
            f"maxrho={bester['maxrho']:.2f}  vol={bester['vol_pct']:.1f}%")
        sag(f"          {','.join(bester['ticker'])}")
        if bester["rho_paar"]:
            sag(f"          engstes Paar: "
                f"{bester['rho_paar'][0]}/{bester['rho_paar'][1]}")

    # ── 4. Monotonie nachweisen ───────────────────────────────
    sag("")
    sag("  Monotonie der Beta:")
    ok_mono = True
    for i in range(1, len(stufen)):
        a, b = stufen[i - 1], stufen[i]
        gut = b["beta"] >= a["beta"]
        ok_mono = ok_mono and gut
        sag(f"    Risk {a['risk']:2d} {a['beta']:.2f} -> "
            f"Risk {b['risk']:2d} {b['beta']:.2f}  "
            f"{'OK' if gut else 'NICHT MONOTON'}")
    sag(f"  GESAMT: {'monoton' if ok_mono else 'NICHT MONOTON'}")

    # ── 5. Nebenbedingungen nachweisen ─────────────────────────
    sag("")
    sag("  Harte Nebenbedingungen:")
    rho_ok = sum(1 for s in stufen if s["maxrho"] <= MAX_RHO)
    sag(f"    maxrho <= {MAX_RHO:.2f}: {rho_ok}/{len(stufen)} Stufen")
    sag(f"    Einzelanteil <= {MAX_ANTEIL:.0%}: "
        f"{len(stufen)}/{len(stufen)} (alle gleich gewichtet)")

    if warnungen:
        sag("")
        sag("  Warnungen:")
        for w in warnungen:
            sag(f"    ! {w}")

    # ── 6. Schreiben ──────────────────────────────────────────
    ziel = "/opt/micro-trader/empfehlung_leiter.json"
    ergebnis = {
        "erstellt_am": datetime.now(timezone.utc).isoformat(),
        "quelle": "leiter_hart.py - harte Nebenbedingungen",
        "maxrho_grenze": MAX_RHO,
        "max_anteil": MAX_ANTEIL,
        "monoton": ok_mono,
        "stufen": stufen,
        "warnungen": warnungen,
    }
    _schreibgeschuetzt(ziel, ergebnis, ensure_ascii=False, indent=2)
    sag("")
    sag(f"  -> {ziel}")

    return 0 if ok_mono else 1


if __name__ == "__main__":
    sys.exit(main())
