"""Aktien-Kandidaten aus Yahoo, eingeordnet nach Beta.

Gegenstueck zu etf_beta.py fuer die Aktien-Seite. Gleiche Form,
gleiche Belege: erst breit fragen, dann selbst einordnen, und die
Einordnung an einer Stichprobe gegen die Quelle pruefen.

Warum ein eigenes Modul und nicht screener.py: screener.py macht
die Discovery fuer Aktien UND ETFs, aber ordnet nur die Aktien ueber
Beta ein und schreibt sie in screener_kandidaten.json. Der Trader
liest jedoch eine freigegebene Liste, und ein breites Universum ist
keine Freigabe. Hier steht dieselbe Logik fuer Aktien in einer
Datei, die nur Aktien enthaelt und daher als Quelle taugt.

29.09.2026: neu. Vorher kam die Aktien-Seite aus TICKER_TO_TIER in
risk_profile.py - 686 handgepflegte Symbole, ohne Yahoo-Abfrage und
ohne Beta. Diese Liste war die Ursache fuer leere Aktien-Depots.
"""

import io
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))  # war fest "/opt/micro-trader" (01.11.2026)
BETACACHE = os.path.join(BASE, ".beta_stock_cache.json")
ZIEL = os.path.join(BASE, "screener_aktien_beta.json")
MARKT = "NYSE/NASDAQ"

sys.path.insert(0, BASE)


def log(msg):
    print("  [aktien] %s" % msg, flush=True)


# ── Produktfamilien, die keine gewoehnliche Einzelaktie sind ────
# Die Abgrenzung ist dieselbe wie bei den ETFs, aber auf Aktien
# bezogen: Fonds, REITs, SPACs, Dividendenkuenste und Hefte sind
# keine Aktien und gehoeren in eine eigene Risikoklasse.

FONDS_TERME = re.compile(
    r"\b(fund|etf|trust|reit|spac|index|tracker|income|"
    r"dividend|notes|bond|debenture)\b", re.I)

HEBEL_TERME = re.compile(
    r"\b(leveraged?|inverse|ultra|[- ]?\d(\.\d)?x|"
    r"bull|bear|2x|3x|4x)\b", re.I)

# Reines Datenrauschen: diese Woerter stehen in ganz normalen
# Firmennamen ("Growth", "Value", "Bull & Bear Foods") und duerfen
# deshalb NICHT als Produktfamilie gelten. Nur zusammen mit einem
# eindeutigen Finanzwort zaehlen sie.

FALSCHE_TREFFER = re.compile(
    r"\b(bull|bear|growth|value|trust|index|income|capital|"
    r"holding|holdings|partners|group|corp|corporation|"
    r"resources|industries|international|technologies|"
    r"ventures|properties|financial|systems|technologies)\b", re.I)


def ist_fonds(name, typ):
    """Fondsartige Produkte aussortieren."""
    n = name or ""
    if typ and str(typ).lower() in ("etf", "mutualfund", "closedendfund"):
        return True
    if FONDS_TERME.search(n):
        # Nur zaehlen, wenn das Wort nicht Teil eines Firmennamens ist
        treffer = FONDS_TERME.search(n)
        rest = (n[:treffer.start()] + " " + n[treffer.end():])
        if not FALSCHE_TREFFER.search(rest):
            return True
    return False


def ist_hebel(name, typ):
    """Hebel- und Short-Produkte aussortieren."""
    n = name or ""
    if typ and str(typ).lower() in ("etf",):
        return True          # ETFs gehoeren in etf_beta.py
    if HEBEL_TERME.search(n):
        treffer = HEBEL_TERME.search(n)
        wort = treffer.group(0).lower().strip()
        # "Bull & Bear Foods" ist keine Short-Aktie
        if wort in ("bull", "bear") and not re.search(
                r"(bull|bear)\s*(etf|fund|trust|inverse)", n, re.I):
            return False
        return True
    return False


# Nach der Stichprobe am 29.09.2026 gemessen: Yahoo liefert unter
# "region=us" Titel, deren Primaerboerse woanders liegt. UGP ist
# Ultrapar Participacoes, ein brasilianischer Minenkonzern, und
# erscheint unter den US-Aktien. Der Titel fiel in Risk 10 mit
# Beta 0.58 und liess sich nicht hinter dem Filter aus einer
# US-Notierung herausfinden - der screen hat ihn schlicht
# ausgegeben.
#
# Zweiter Fall: STEK bekam Beta 0.002 bei vollen 500 Datenpunkten.
# Das ist kein Rechenfehler, sondern eine Marktgrenze: ein
# brasilianischer Titel korreliert nicht mit SPY. Ein Beta nahe 0
# bedeutet also "kein gemeinsamer Markt", nicht "sicher".
# Beides wird ausgeschlossen, sonst behaeltten die Low-Risk-Stufen
# Titel, deren Risiko sich gerade nicht messen laesst.

# Exchange ist nicht "nasdaq" und enthaelt kein US-Muster.
# Positiv- statt Negativliste. Am Lauf vom 29.09.2026 gemessen
# lieferte Yahoo 224 Titel aus genau sieben Boersenkuerzeln:
#
#   NYQ 93   NMS 55   NCM 41   ASE 15   OID 10   NGM 8   PNK 2
#
# Eine Negativliste haette jede weitere Boerse durchrutschen
# lassen - BUE, AMS und TOR fielen im Gegentest durch, obwohl
# Yahoo sie gar nicht verwendet. Eine Positivliste kann eine
# unbekannte Boerse nicht uebersehen: sie faellt schlicht aus.
#
# NYQ/NYS = New York Stock Exchange, NMS/NAS = NASDAQ, NCM = Capital
# Market, ASE = American Stock Exchange (heute NYSE American),
# NGM = NASDAQ Global Market, OID = Cboe BZX, PNK = NASDAQ Pink.
# Penn-Aktien. Gemessen am Lauf vom 29.09.2026: 29 von 214
# Kandidaten lagen unter 1 USD, der billigste bei 0,0001 USD bei
# 17,8 Mio Stueck Handelsvolumen. Das sind keine Aktien, sondern
# verwaiste Gesellschaften, Warrants und Preferreds, die Yahoo
# unter region=us mitliefert - Zhibao Technology zu 0,0798 USD
# ist eine reale Aktie und damit kein Beweis fuer das Gegenteil.
#
# 5 USD ist keine Aesthetik, sondern Kosten: bei 50 EUR Positions-
# budget ergibt 0,08 USD eine Menge von 625 Stueck und damit
# eine Order fuer einen Bruchteil Cent. Davon fallen Broker-
# gebuehren proportional mehr an als vom Handel.
MIN_PREIS = 5.0

# Ebenso ein Guetekriterium: unter 100 Mio USD Marktkapital
# ein Titel, dessen Kurs man an einer Handvoll Tagen pro Jahr
# sieht. Die Beta ist dann rechenbar, aber der Markt ist es nicht.
MIN_MARKTKAPITAL = 100_000_000


# Ein Beta unter diesem Wert heisst "kein gemeinsamer Markt", nicht
# "geringes Risiko". Gemessen am Lauf vom 29.09.2026: zehn Titel
# lagen unter 0.15, darunter vier mit belegter Fremdnotierung und
# STEK mit 0.002 bei vollen 500 Datenpunkten. Wer die behalten
# haette, haette in Risk 0 Titel gefuehrt, deren Risiko nicht
# messbar ist.
MIN_BETA = 0.15

US_BOERSEN = {
    "NYQ", "NYS", "NMS", "NAS", "NGM", "NCM", "NCM", "ASE", "AMX",
    "OID", "BZX", "PNK", "PCX", "OQB", "OQX", "NBQ", "NIM",
}


def ist_nicht_us(exchange, name):
    """Titel ausserhalb der US-Boersen aussortieren.

    Ohne Exchange-Angabe wird der Titel behalten: Yahoo laesst das
    Feld gelegentlich leer, und ein fehlender Wert ist kein Beweis
    fuer eine auslaendische Notierung. Der Beta-Weg bleibt offen -
    ein Titel mit Beta < MIN_BETA faellt ohnehin heraus.
    """
    e = (exchange or "").strip().upper()
    if not e:
        return False
    return e not in US_BOERSEN





def band(risk):
    """Beta-Band je Risikostufe.

    Dieselben Grenzen wie bei den ETFs: eine Aktie mit Beta 0,3 und
    eine mit Beta 2,2 gehoeren in dieselbe Entfernung vom Depot-Mittelpunkt.
    """
    return {
        0: (0.00, 0.55), 10: (0.55, 0.75), 20: (0.75, 0.95),
        30: (0.95, 1.10), 40: (1.10, 1.25), 50: (1.25, 1.40),
        60: (1.40, 1.55), 70: (1.55, 1.75), 80: (1.75, 2.00),
        90: (2.00, 4.00),
    }[risk]


STUFEN = list(range(0, 100, 10))


def _cache_lesen():
    try:
        return json.load(io.open(BETACACHE, encoding="utf-8"))
    except Exception:
        return {}


def _cache_schreiben(c):
    tmp = BETACACHE + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(
        json.dumps(c, ensure_ascii=False, indent=1))
    os.replace(tmp, BETACACHE)


def markt_renditen(ticker, jahre=2):
    """Tagesrenditen gegen SPY, fuer die Beta-Rechnung."""
    import yfinance as yf
    h = yf.Ticker(ticker).history(period="%dy" % jahre, auto_adjust=True)
    b = yf.Ticker("SPY").history(period="%dy" % jahre, auto_adjust=True)
    if h is None or b is None or h.empty or b.empty:
        return None
    r1 = h["Close"].pct_change().dropna()
    r2 = b["Close"].pct_change().dropna()
    idx = r1.index.intersection(r2.index)
    if len(idx) < 120:
        return None
    return r1.loc[idx], r2.loc[idx]


def beta_rechnen(ticker):
    """Beta aus 2 Jahren Tagesrenditen gegen SPY."""
    try:
        d = markt_renditen(ticker)
        if not d:
            return None
        a, b = d
        var_b = float(b.var())
        if var_b <= 0:
            return None
        return round(float(a.cov(b)) / var_b, 3)
    except Exception:
        return None


def betas_nachladen(kandidaten, cache, grenze=40):
    """Beta fuer Kandidaten ohne Wert, mit Cache."""
    fehlen = [k for k in kandidaten
              if k not in cache or cache[k].get("beta") is None]
    if not fehlen:
        return cache
    log("Beta fehlt fuer %d Titel, lade nach (Cache: %d)"
        % (len(fehlen), len(cache)))
    n = 0
    for t in fehlen:
        b = beta_rechnen(t)
        cache[t] = {"beta": b, "ts": time.time()}
        n += 1
        if n % grenze == 0:
            _cache_schreiben(cache)
            log("  %d/%d" % (n, len(fehlen)))
    _cache_schreiben(cache)
    return cache


def kandidaten_sammeln():
    """Einmal breit fragen, dann selbst einordnen.

    Kein Rendite-Filter: eingeordnet wird ueber Beta. Ein Rendite-Band
    wuerde systematisch die schwach laufenden Aktien entfernen, und
    genau die sind in einer Risikostufe 80/90 gemeint.
    """
    import yfinance as yf
    from yfinance import EquityQuery
    r = yf.screen(EquityQuery("and", [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gt", ["avgdailyvol3m", 2_000_000]),
    ]), size=250)
    return r["quotes"]


def sektoren_nachladen(kandidaten, cache):
    """Sektor je Titel, wenn Yahoo ihn nicht mitliefert.

    Gemessen am 29.09.2026: EquityQuery gibt sector und industry
    als None zurueck, bei jedem der 250 Titel. Die Sektorstreuung
    in depot10_aktien.py braucht das Feld aber zwingend - ohne sie
    wuerde sie rein nach Liquiditaet sortieren und damit genau das
    tun, was sie vermeiden soll.

    .info kostet einen Abruf je Titel, deshalb mit Cache.
    """
    fehlen = [k for k in kandidaten
              if not (cache.get(k) or {}).get("sektor")]
    if not fehlen:
        return cache
    log("Sektor fehlt fuer %d Titel, lade nach (Cache: %d)"
        % (len(fehlen), len(cache)))
    import yfinance as yf
    n = 0
    for t in fehlen:
        try:
            info = yf.Ticker(t).info or {}
            e = cache.setdefault(t, {})
            e["sektor"] = info.get("sector") or ""
            e["branche"] = info.get("industry") or ""
            e["marktkapital"] = info.get("marketCap") or 0
        except Exception:
            pass
        n += 1
        if n % 25 == 0:
            _cache_schreiben(cache)
            log("  %d/%d" % (n, len(fehlen)))
    _cache_schreiben(cache)
    return cache


def einordnen(quotes, cache):
    """Kandidaten filtern und in Risikostaeufen legen."""
    raus = {"fonds": 0, "hebel": 0, "nicht_us": 0, "beta_zu_klein": 0,
            "preis_zu_klein": 0, "kapital_zu_klein": 0,
            "kein_beta": 0, "kein_preis": 0}
    stufen = {s: [] for s in STUFEN}

    for q in quotes:
        t = (q.get("symbol") or "").strip().upper()
        if not t:
            continue
        name = q.get("shortName") or q.get("longName") or ""
        typ = q.get("quoteType") or ""
        if ist_hebel(name, typ):
            raus["hebel"] += 1
            continue
        if ist_fonds(name, typ):
            raus["fonds"] += 1
            continue
        if ist_nicht_us(q.get("exchange"), name):
            raus["nicht_us"] += 1
            continue
        preis = q.get("regularMarketPrice") or 0
        if not preis or preis <= 0:
            raus["kein_preis"] += 1
            continue
        if preis < MIN_PREIS:
            raus["preis_zu_klein"] += 1
            continue

        eintrag = cache.get(t) or {}
        b = eintrag.get("beta")
        if b is None:
            raus["kein_beta"] += 1
            continue
        if b < MIN_BETA:
            # Siehe Kopf: Beta nahe 0 heisst fehlende gemeinsame
            # Marktstruktur, nicht geringes Risiko.
            raus["beta_zu_klein"] += 1
            continue

        kapital = eintrag.get("marktkapital") or 0
        if kapital and kapital < MIN_MARKTKAPITAL:
            raus["kapital_zu_klein"] += 1
            continue

        stufe = None
        for s in STUFEN:
            lo, hi = band(s)
            if lo <= b < hi:
                stufe = s
                break
        if stufe is None:
            continue

        stufen[stufe].append({
            "ticker": t,
            "name": name[:70],
            "preis": round(float(preis), 2),
            "beta": b,
            "risk_score": stufe,
            "sektor": eintrag.get("sektor") or q.get("sector") or "",
            "branche": eintrag.get("branche") or q.get("industry") or "",
            "markt": q.get("exchange") or "unbekannt",
            "volumen": q.get("averageDailyVolume3Month") or 0,
            "ma_cap": q.get("marketCap") or 0,
            "typ": "aktie",
        })

    return stufen, raus


def speichern(stufen, raus, quelle):
    """Ergebnis atomar schreiben, alte Datei bleibt bei Fehler."""
    ergebnis = {
        "erstellt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "markt": MARKT,
        "quelle": quelle,
        "stufen": {str(s): sorted(v, key=lambda x: -x["volumen"])
                   for s, v in stufen.items()},
        "zahlen": {
            "kandidaten": sum(len(v) for v in stufen.values()),
            "verworfen": raus,
        },
    }
    tmp = ZIEL + ".neu"
    io.open(tmp, "w", encoding="utf-8").write(
        json.dumps(ergebnis, ensure_ascii=False, indent=1))
    os.replace(tmp, ZIEL)
    return ergebnis


def main():
    t0 = time.time()
    cache = _cache_lesen()

    log("frage Yahoo ab")
    try:
        quotes = kandidaten_sammeln()
    except Exception as e:
        log("Yahoo-Abfrage fehlgeschlagen: %s: %s" % (type(e).__name__, e))
        return 2
    log("%d Rohkandidaten von Yahoo" % len(quotes))

    symbole = [(q.get("symbol") or "").strip().upper() for q in quotes]
    cache = betas_nachladen(symbole, cache)
    cache = sektoren_nachladen(symbole, cache)

    stufen, raus = einordnen(quotes, cache)
    ergebnis = speichern(stufen, raus, "yfinance EquityQuery + Beta 2y/SPY")

    log("verworfen: %s" % raus)
    for s in STUFEN:
        log("  Risk %-3d %3d Titel" % (s, len(stufen[s])))
    log("Summe %d Kandidaten in %.0f s"
        % (ergebnis["zahlen"]["kandidaten"], time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())