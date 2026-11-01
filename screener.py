#!/usr/bin/env python3
"""Screener: findet Titel nach messbaren Kriterien, pro Risikostufe.

ANLASS (2026-09-29):
  Das System hatte 684 hart codierte Ticker in risk_profile.py. Der
  Markt hat rund 8.000 boersennotierte Unternehmen, dazu mehrere tausend
  ETFs. Ein System, das nur abtippt, kann nichts finden, was nicht vorher
  von Hand eingetragen wurde. Die Nutzerfrage war genau das:
  "wie viele spukt die Quelle, wo wird gefiltert, ist das plausibel".
  Antwort: 684, an drei festen Stellen, und nein.

  Dieser Screener ersetzt die Handauswahl durch eine messbare Abfrage.
  Grundlage: yfinance EquityQuery / ETFQuery, verifiziert am 29.09.2026 -
  eigene Kriterien funktionieren, 0,5-0,6 s je Abfrage, 19 vordefinierte
  Listen sind zusaetzlich verfuegbar.

GRUNDSAETZE:
  a) Jede Auswahl ist eine dokumentierte Filterung, keine Vermutung.
     Jeder Treffer bekommt seine Begruendung als Text mit.
  b) Es wird NICHTS gekauft. Dieser Screener liefert nur Kandidaten.
  c) Alle Kriterien sind messbar und im Code nachlesbar.
  d) Jede Abfrage bekommt Zeit zum Atmen (Rate-Limit Yahoo).
  e) Ein Fehler liefert KEINE Treffer, nie eine Notfallliste. Sonst
     waere eine kaputte Abfrage von einer gueltigen nicht zu unterscheiden.

RISIKOSTUFEN:
  Die Skala des Controllers ist 0..95. Der Screener bildet sie auf
  Beta ab, weil Beta die einzige Risikogroesse ist, die Yahoo direkt
  liefert und die mit der controller-Skala (0.275 bis 1.640) korreliert.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import yfinance as yf
from yfinance import EquityQuery, ETFQuery

BASE = os.path.dirname(os.path.abspath(__file__))
AUSGABE = os.path.join(BASE, "screener_kandidaten.json")

# ─── Risikostufen: Beta-Baender und Begleitkriterien ───────────────────
# beta_lt      : Beta-Obergrenze (Yahoo-Feld "beta")
# mcap_min     : Marktkapitalisierung in USD, mind.
# vol_min      : Durchschnittsvolumen 3 Monate, mind. (Liquiditaet)
# 52w_min      : minimale 52-Wochen-Performance in Prozent
# 52w_max      : maximale 52-Wochen-Performance
# erlaubt      : None oder eine Liste erlaubter Sektoren
#
# BEGRUENDUNG DER GRENZEN:
#   Die Beta-Grenzen folgen der verifizierten Leiter:
#   Risk 10 Beta 0,275 / Risk 95 Beta 1,640. Zwischenwerte werden
#   linear interpoliert. Kleinere Beta = defensiver.
#   Die Marktkapitalisierungs-Untergrenze schliesst Micro-Caps aus:
#   Test 3 am 29.09.2026 lieferte bei "52W > 20 Prozent" Titel wie
#   1812 Brewing (Mcap 114.464 USD, +95070 Prozent) - das ist Rauschen,
#   kein Investment. Ab 500 Mio USD sind Titel handelbar und die Kursdaten
#   belastbar genug fuer eine Position.
#   Das Volumeminimum ist die Handelsbarkeit: unter 1 Mio Stueck/Tag ist
#   ein Verkauf zum Kurs unrealistisch.
# Beta-BAENDER, keine Obergrenzen. Der erste Entwurf fragte nur
# "Beta < X" - dadurch enthielt Risk 90 fast alles, was auch in Risk 80
# lag (57 von 60 Titeln). Gemessen am 29.09.2026. Jetzt hat jede Stufe
# ein Fenster, und die Fenster sind disjunkt.
#
# Die Beta-Grenzen folgen der verifizierten Leiter (Betas 0,275 bis
# 1,640) mit einem Fenster um jede Stufe. Risiko 0 beginnt bei 0.
STUFEN = [
    {"risk": 0,  "beta_lo": 0.00, "beta_hi": 0.35, "mcap_min": 20_000_000_000,
     "vol_min": 3_000_000, "52w_min": -25, "52w_max": 40},
    {"risk": 10, "beta_lo": 0.35, "beta_hi": 0.55, "mcap_min": 10_000_000_000,
     "vol_min": 3_000_000, "52w_min": -20, "52w_max": 50},
    {"risk": 20, "beta_lo": 0.55, "beta_hi": 0.75, "mcap_min": 8_000_000_000,
     "vol_min": 2_000_000, "52w_min": -20, "52w_max": 60},
    {"risk": 30, "beta_lo": 0.75, "beta_hi": 0.90, "mcap_min": 5_000_000_000,
     "vol_min": 2_000_000, "52w_min": -15, "52w_max": 70},
    {"risk": 40, "beta_lo": 0.90, "beta_hi": 1.05, "mcap_min": 3_000_000_000,
     "vol_min": 1_500_000, "52w_min": -15, "52w_max": 80},
    {"risk": 50, "beta_lo": 1.05, "beta_hi": 1.20, "mcap_min": 2_000_000_000,
     "vol_min": 1_500_000, "52w_min": -10, "52w_max": 90},
    {"risk": 60, "beta_lo": 1.20, "beta_hi": 1.40, "mcap_min": 1_000_000_000,
     "vol_min": 1_000_000, "52w_min": -10, "52w_max": 110},
    {"risk": 70, "beta_lo": 1.40, "beta_hi": 1.60, "mcap_min": 1_000_000_000,
     "vol_min": 1_000_000, "52w_min": -5,  "52w_max": 150},
    {"risk": 80, "beta_lo": 1.60, "beta_hi": 1.90, "mcap_min": 500_000_000,
     "vol_min": 800_000,   "52w_min": 0,   "52w_max": 200},
    {"risk": 90, "beta_lo": 1.90, "beta_hi": 3.00, "mcap_min": 300_000_000,
     "vol_min": 800_000,   "52w_min": 0,   "52w_max": 300},
]

# ETF-spezifisch: Risiko ueber Volatilitaet, nicht Beta (Yahoo liefert
# bei ETFs kein verlaessliches Beta). Deshalb: Vorlaufperformance 1 Jahr
# als Risikomass.
# ETF-Stufen mit echten Yahoo-Feldern IN der Query.
#
# DER ERSTE ENTWURF WAR FALSCH: er fragte nur nach Volumen und filterte
# die Rendite danach in Python. Ergebnis: Risk 50 bis 90 lieferten
# 19 von 19 identische Titel, weil Yahoo immer dieselbe Volumen-Topliste
# zurueckgibt. Gemessen am 29.09.2026.
#
# Richtig ist, die Rendite IN die Query zu legen.
#
# KORREKTUR 29.09.2026, gefunden bei der Nachpruefung: der erste
# Versuch nutzte "annualreturnnavy1". Dieses Feld gibt es bei Yahoo
# nicht - die Query lief ohne Fehler, lieferte aber eine
# ungefilterte Volumen-Topliste. 297 von 374 Titeln lagen ausserhalb
# ihres own Bands, USO (+103 %) lag in Risk 0. Ein ungueltiges Feld
# wird stillschweigend ignoriert, es gibt keinen Fehler.
#
# Jetzt: fiftytwowkpercentchange. Das Feld wird von Yahoo geliefert
# UND kommt in der Antwort zurueck, damit die Zuordnung nachpruefbar
# ist (20 von 20 Stichproben im Band).
#
# Lehre daraus: ein Query-Feld gilt erst als benutzt, wenn eine
# Kontrollabfrage zeigt, dass die Antwort den Wert enthaelt, nach
# dem gefiltert wurde. Filterfeld und Antwortfeld muessen
# zusammenpassen.
# Operator-Hinweis: es heisst "btwn", nicht "between".
ETF_STUFEN = [
    {"risk": 0,  "r1j_lo": -30, "r1j_hi": 5,   "vol_min": 500_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 10, "r1j_lo": -20, "r1j_hi": 10,  "vol_min": 500_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 20, "r1j_lo": -10, "r1j_hi": 18,  "vol_min": 500_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 30, "r1j_lo": 0,   "r1j_hi": 25,  "vol_min": 800_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 40, "r1j_lo": 0,   "r1j_hi": 35,  "vol_min": 800_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 50, "r1j_lo": 5,   "r1j_hi": 50,  "vol_min": 1_000_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 60, "r1j_lo": 10,  "r1j_hi": 70,  "vol_min": 1_000_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 70, "r1j_lo": 15,  "r1j_hi": 100, "vol_min": 1_000_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 80, "r1j_lo": 20,  "r1j_hi": 150, "vol_min": 1_200_000,
     "feld": "fiftytwowkpercentchange"},
    {"risk": 90, "r1j_lo": 40,  "r1j_hi": 300, "vol_min": 1_500_000,
     "feld": "fiftytwowkpercentchange"},
]

PAUSE = 1.2   # Sekunden zwischen Abfragen


def log(msg=""):
    print(msg, flush=True)


def hole_werte(treffer):
    """Yahoo liefert verschiedene Feldnamen je Antwort. Hier wird
    robust ausgelesen, ein fehlendes Feld ist None, nicht 0."""
    preis = (treffer.get("regularMarketPrice")
             or treffer.get("eodprice") or treffer.get("intradayprice"))
    mcap = treffer.get("marketCap") or treffer.get("intradaymarketcap")
    vol = (treffer.get("regularMarketVolume")
           or treffer.get("dayvolume") or treffer.get("eodvolume"))
    r52 = treffer.get("fiftyTwoWeekChangePercent")
    r1j = None
    # Rendite 1 Jahr: je nach Antwort in verschiedenen Feldern
    for f in ("oneYearAverageReturn", "annualTotalReturn",
              "trailingAnnualReturn", "fiftyTwoWeekChangePercent"):
        v = treffer.get(f)
        if isinstance(v, (int, float)):
            r1j = v
            break
    return {
        "ticker": treffer.get("symbol"),
        "name": str(treffer.get("shortName")
                    or treffer.get("longName") or "")[:70],
        "preis": round(float(preis), 2) if isinstance(preis, (int, float)) else None,
        "beta": treffer.get("beta"),
        "mcap": mcap,
        "volumen": vol,
        "rendite_52w": round(float(r52), 1) if isinstance(r52, (int, float)) else None,
        "rendite_1j": round(float(r1j), 1) if isinstance(r1j, (int, float)) else None,
        "sektor": treffer.get("sector") or treffer.get("categoryname"),
    }


def begruendung(w, stufe, art):
    """Text, WARUM dieser Titel in dieser Stufe liegt. Das ist der
    Punkt, an dem die Auswahl nachvollziehbar wird."""
    teile = []
    teile.append("Beta %s" % (w["beta"] if w["beta"] is not None else "n/a"))
    if w["mcap"]:
        teile.append("Mcap %.1f Mrd" % (w["mcap"] / 1e9))
    if w["volumen"]:
        teile.append("Vol %.1f Mio" % (w["volumen"] / 1e6))
    if w["rendite_52w"] is not None:
        teile.append("52W %+.0f%%" % w["rendite_52w"])
    grenze = ("Beta zwischen %.2f und %.2f"
              % (stufe["beta_lo"], stufe["beta_hi"])) if art == "aktie" else \
             ("52W-Change %+d bis %+d%%" % (stufe["r1j_lo"], stufe["r1j_hi"]))
    return "%s, %s" % (", ".join(teile), grenze)


def screene_aktien(stufe, anzahl=60):
    """Eine Aktien-Abfrage fuer eine Risikostufe."""
    bedingungen = [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gt", ["intradaymarketcap", stufe["mcap_min"]]),
        EquityQuery("gt", ["avgdailyvol3m", stufe["vol_min"]]),
        # Beta-FENSTER, nicht nur Obergrenze - sonst ueberlappen sich
        # die Stufen (gemessen: 57 von 60 Titeln in Risk 80 UND 90).
        EquityQuery("gt", ["beta", stufe["beta_lo"]]),
        EquityQuery("lt", ["beta", stufe["beta_hi"]]),
        EquityQuery("gt", ["fiftytwowkpercentchange", stufe["52w_min"]]),
        EquityQuery("lt", ["fiftytwowkpercentchange", stufe["52w_max"]]),
    ]
    try:
        q = EquityQuery("and", bedingungen)
        r = yf.screen(q, size=anzahl, sortField="intradaymarketcap",
                      sortAsc=False)
        return r.get("quotes", [])
    except Exception as e:
        log("   ⚠ Stufe %d: Abfrage fehlgeschlagen: %s" % (stufe["risk"], str(e)[:70]))
        return []


def screene_etf(stufe, anzahl=40):
    """ETF-Abfrage mit der Rendite IN der Query.

    Wichtig: NICHT nach Volumen abfragen und die Rendite danach in
    Python filtern. Yahoo gibt dann immer dieselbe Topliste zurueck und
    alle Stufen sehen gleich aus (gemessen 29.09.2026: 19 von 19
    identisch bei Risk 50 bis 90).
    """
    feld = stufe.get("feld", "fiftytwowkpercentchange")
    bedingungen = [
        ETFQuery("eq", ["region", "us"]),
        ETFQuery("gt", ["dayvolume", stufe["vol_min"]]),
        ETFQuery("gte", [feld, stufe["r1j_lo"]]),
        ETFQuery("lte", [feld, stufe["r1j_hi"]]),
    ]
    try:
        q = ETFQuery("and", bedingungen)
        r = yf.screen(q, size=anzahl, sortField="dayvolume", sortAsc=False)
        return r.get("quotes", [])
    except Exception as e:
        log("   \u26a0 ETF Stufe %d: Abfrage fehlgeschlagen: %s"
            % (stufe["risk"], str(e)[:70]))
        return []


def firma_key(ticker):
    """Firmenidentitaet, damit Class-A/Class-C nicht doppelt gezaehlt
    werden. BRK-B und BRK.B sind dieselbe Firma, GOOG und GOOGL auch.
    Im selben Depot waere das dieselbe Position zweimal.

    Eine feste Liste ist hier richtig: die Sonderfaelle sind wenige und
    bekannt. Eine Heuristik wuerde neue Ticker falsch zusammenfassen.
    """
    ALIASE = {
        "BRK-B": "BRK", "BRK.B": "BRK", "BRK-BD": "BRK",
        "GOOG": "GOOGL", "GOOGL": "GOOGL",
        "FB": "META", "META": "META",
        "RDS-A": "RDS", "RDS-B": "RDS",
    }
    return ALIASE.get(ticker, ticker)


BETACACHE = os.path.join(BASE, ".beta_cache.json")


def beta_nachladen(kandidaten_alle, pause=0.15):
    """Beta kommt NICHT in der screener-Antwort zurueck - Yahoo filtert
    serverseitig, antwortet aber ohne das Feld. Belegt am 29.09.2026:
    alle 490 Kandidaten hatten beta=None.

    Deshalb wird es einzeln nachgeladen. Messung: 0,81 s je Titel,
    490 Titel also rund 6,6 Minuten. Zu lang fuer einen Lauf, deshalb
    mit Cache: Beta aendert sich selten, und der Cache macht den
    zweiten Lauf auf Sekunden.

    Der Cache speichert NUR das Beta je Ticker - keine Kurse, keine
    Positionen, nichts Geheimes.
    """
    cache = {}
    if os.path.exists(BETACACHE):
        try:
            with open(BETACACHE, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    # Alle eindeutigen Ticker, fuer die noch kein Beta im Cache liegt.
    # kandidaten_alle ist eine FLACHE Liste von Kandidat-Dicts, keine
    # Liste von Listen. Mein erster Entwurf hatte "for liste in ... for k
    # in liste" und bekam deshalb Strings statt Dicts
    # (AttributeError: 'str' object has no attribute 'get', 29.09.2026).
    fehlend = sorted({k.get("ticker") for k in kandidaten_alle
                      if isinstance(k, dict) and k.get("ticker")})
    todo = [t for t in fehlend if t not in cache]
    if not todo:
        log("   Beta-Cache vollstaendig (%d Ticker)" % len(cache))
        return cache

    log("   Lade %d Beta-Werte nach (Cache hat %d) ..." % (len(todo), len(cache)))
    t0 = time.time()
    neu_gesetzt = 0
    for i, tick in enumerate(todo):
        try:
            b = yf.Ticker(tick).info.get("beta")
            if isinstance(b, (int, float)):
                cache[tick] = round(float(b), 3)
                neu_gesetzt += 1
        except Exception:
            # Kein Beta verfuegbar: nicht raten, nicht 0 setzen.
            pass
        if (i + 1) % 50 == 0:
            log("     %d von %d (%.0f%%)" % (i + 1, len(todo),
                                             100.0 * (i + 1) / len(todo)))
        time.sleep(pause)
    log("   %d Beta-Werte geladen in %.0fs" % (neu_gesetzt, time.time() - t0))

    try:
        with open(BETACACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=0, sort_keys=True)
        log("   Cache gespeichert: %s (%d Eintraege)" % (BETACACHE, len(cache)))
    except Exception as e:
        log("   \u26a0 Cache nicht speicherbar: %s" % str(e)[:60])
    return cache


def main():
    log("=" * 74)
    log("  Screener: Kandidaten nach Risikostufe  (nur Auswahl, kein Kauf)")
    log("=" * 74)
    log()

    ergebnis = {
        "zeitpunkt": datetime.now(timezone.utc).isoformat(),
        "quelle": "yfinance EquityQuery/ETFQuery",
        "aktien": {},
        "etf": {},
    }

    # --- Aktien -------------------------------------------------------
    log("  AKTIEN")
    for stufe in STUFEN:
        roh = screene_aktien(stufe)
        kandidaten = []
        for t in roh:
            w = hole_werte(t)
            if not w["ticker"] or w["preis"] is None:
                continue
            w["begruendung"] = begruendung(w, stufe, "aktie")
            kandidaten.append(w)
        # Dubletten entfernen: Class-A/Class-C, dieselbe Firma
        gesehen = set()
        ohne_dubletten = []
        for k in kandidaten:
            key = firma_key(k["ticker"])
            if key in gesehen:
                continue
            gesehen.add(key)
            ohne_dubletten.append(k)
        entfernte = len(kandidaten) - len(ohne_dubletten)
        kandidaten = ohne_dubletten
        ergebnis["aktien"][str(stufe["risk"])] = kandidaten
        log("   Risk %-3d beta %.2f-%.2f  -> %3d Kandidaten%s   %s"
            % (stufe["risk"], stufe["beta_lo"], stufe["beta_hi"],
               len(kandidaten),
               " (-%d Dubletten)" % entfernte if entfernte else "",
               ", ".join(c["ticker"] for c in kandidaten[:6])))
        time.sleep(PAUSE)
    log()

    # --- ETFs ---------------------------------------------------------
    log("  ETFs")
    for stufe in ETF_STUFEN:
        roh = screene_etf(stufe)
        kandidaten = []
        for t in roh:
            w = hole_werte(t)
            if not w["ticker"] or w["preis"] is None:
                continue
            w["begruendung"] = begruendung(w, stufe, "etf")
            kandidaten.append(w)
        ergebnis["etf"][str(stufe["risk"])] = kandidaten
        log("   Risk %-3d Rendite 1J %+d..%d%%  -> %3d Kandidaten   %s"
            % (stufe["risk"], stufe["r1j_lo"], stufe["r1j_hi"],
               len(kandidaten), ", ".join(c["ticker"] for c in kandidaten[:6])))
        time.sleep(PAUSE)
    log()

    # --- Beta nachladen und zuschreiben --------------------------------
    alle = ([k for v in ergebnis["aktien"].values() for k in v]
            + [k for v in ergebnis["etf"].values() for k in v])
    cache = beta_nachladen(alle)
    fehlend_beta = 0
    for k in alle:
        b = cache.get(k["ticker"])
        if isinstance(b, (int, float)):
            k["beta"] = b
            # Begruendung mit dem echten Wert wiederholen
            if k.get("begruendung") and "Beta n/a" in k["begruendung"]:
                k["begruendung"] = k["begruendung"].replace("Beta n/a",
                                                            "Beta %.2f" % b)
        else:
            fehlend_beta += 1
    log("   Kandidaten ohne Beta: %d von %d" % (fehlend_beta, len(alle)))
    log()

    # --- Speichern ----------------------------------------------------
    with open(AUSGABE, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, indent=1, ensure_ascii=False)

    n_a = sum(len(v) for v in ergebnis["aktien"].values())
    n_e = sum(len(v) for v in ergebnis["etf"].values())
    log("  Gespeichert: %s" % AUSGABE)
    log("  Aktien-Kandidaten gesamt: %d" % n_a)
    log("  ETF-Kandidaten gesamt:    %d" % n_e)
    log("  Vorher: 684 handgepflegte Ticker -> jetzt gemessen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
