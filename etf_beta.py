"""ETF-Risikostufen nach selbst berechnetem Beta.

ANLASS (29.09.2026, Nachpruefung nach dem annualreturnnavy1-Fund):
  Die ETF-Stufen liefen ueber 52-Wochen-Change. Das ist keine
  Risikoeinstufung, sondern die Performance der LETZTEN 12 MONATE.
  Gemessene Folge: SPY (+15 %) landete in Risk 70, QQQ (+23 %) in
  Risk 80, ARKK (+3 %) in Risk 50. Ein breit gestreuter ETF ist
  "sicherer" als ein Tech-ETF, sobald der Tech-Sektor laeuft.

  Zusaetzlich fiel auf: 8 der 13 gaengigsten ETFs fehlten in der
  Auswahl, darunter VTI, ARKK, SOXL. Grund war nicht Liquiditaet
  (VTI hat 3 Mio Stueck pro Tag), sondern das Rendite-Band.

  Yahoo liefert fuer ETFs KEIN beta-Feld (verifiziert: SPY, QQQ,
  BND, TQQQ, VTI, SCHD, XBI, USO liefern alle beta=None). Fuer
  Aktien liefert Yahoo Beta, fuer ETFs nicht - dieselbe Quelle,
  unterschiedliche Felder.

LOESUNG: Beta selbst rechnen, aus denselben Kursen, mit derselben
Methode wie bei Aktien: Regression der Tagesrenditen gegen SPY
ueber 2 Jahre.

  Gemessen am 29.09.2026 (n=500 Handelstage):
    BND  0,054    SCHD 0,514    VTI  1,001
    SPY  1,000    QQQ  1,248    TQQQ 3,702    SOXL 5,860
    XBI  0,966    USO -0,152
  USO ist negativ, weil Rohoel derzeit gegen den Markt laeuft -
  niedrige Korrelation heisst nicht "sicher", sondern "anderes".
  Fuer die Risikostufe zaehlt die BANDBREITE, nicht das Vorzeichen;
  deshalb wird |Beta| fuer die Stufe verwendet und das Vorzeichen
  in der Begruendung genannt.

BETA-BAENDER wie bei Aktien, damit beide Universen vergleichbar sind:
  Risk  0: 0,00-0,35     Risk 50: 1,05-1,20
  Risk 10: 0,35-0,55     Risk 60: 1,20-1,40
  Risk 20: 0,55-0,70     Risk 70: 1,40-1,65
  Risk 30: 0,70-0,85     Risk 80: 1,65-1,90
  Risk 40: 0,85-1,05     Risk 90: 1,90-6,00
"""
import io
import json
import math
import os
import re
import time

BASE = os.path.dirname(os.path.abspath(__file__))  # war fest "/opt/micro-trader" (01.11.2026)
BETACACHE = os.path.join(BASE, ".beta_etf_cache.json")
MARKT = "SPY"


def log(msg=""):
    print(msg, flush=True)


# ─── Derivate ausschliessen ────────────────────────────────────────────
#
# Yahoo fuehrt sie in den ETF-Listen, weil sie an Boersen gehandelt
# werden. Sie sind keine Fonds, sondern Terminscheine auf einen Index.
#
# Die Konsequenz des Rollens: Der Kontrakt laeuft aus, es muss ein
# neuer gekauft werden, und der Preis des neuen liegt in der Regel
# ueber dem alten. Das kostet jedes Mal - unabhaengig davon, ob der
# Markt steigt oder faellt. Ueber ein Jahr geht dadurch ein spuerbarer
# Teil des Wertes verloren.
#
# Nachgemessen an den 13 Funden dieser Liste: sie standen alle in
# Risk 90, also in der Stufe, die das System als "am schaerfsten"
# verkauft. Genau dort waeren sie am verlockendsten.

# 29.09.2026: Options-Einkommensfonds und strukturell verlust-
# fuehrende Ausschuettungsfonds. Sie fallen nicht ueber die
# Tickerliste, weil jeder Anbieter eigene Symbole hat, sondern
# ueber die Anbieter-Wortmarke im Namen. Als Regex, damit es zum
# Muster von ist_einzeltitel_hebel passt.
#
# Bisher durchgerutscht: SMCY (YieldMax SMCI Option Income
# Strategy), Beta 1,98, 52 Wochen -65,2 %. Dieselbe Produkt-
# klasse wie SPXS, das im alten Betrieb in 6 Depots lag.
#
# Warum raus: Der Fonds verkauft monatlich Optionen auf einen
# einzelnen Emittenten und zahlt die Ausschuettung aus dem
# Optionserlös. Im Kurs geht der Unterschied zwischen dem
# vereinnahmten und dem nicht mehr vorhandenen Wert verloren.
# Das ist keine Rendite, das ist Tilgung durch Eigenkapital.
AUSSCHUETTUNG_FONDS = re.compile(
    r"yieldmax|option\s?income|option\s?income\s?strategy"
    r"|defiance\s|trueshares|amplify\s+black|nexcap",
    re.I,
)

DERIVATE = {
    # Volatilitaet
    "VXX", "VIXY", "UVXY", "SVXY", "VIXM", "VIXL",
    # Short Markt
    "SDS", "SDOW", "SPXS", "SQQQ", "SH", "SPSY",
    # Long und Short Hebel
    "UPRO", "UPH", "SPXL", "SPLV", "SOXL", "SOXS", "SQQQ",
    "TQQQ", "TQA", "TZA", "TZL",
    # Long/Old Yield
    "TMF", "TMV", "TYL", "UST", "USF", "TBT",
    # China
    "YINN", "YANG", "FXP", "FXF", "MCHI",
    # Einzeltitel-Hebel
    "NVDY", "NVDU", "NVDL", "GGLL", "AMDL", "TSLL",
    "MSTY", "MSTU", "MSTX", "MSTZ",
    "SPXE", "SPXN", "SPXU", "SPXB",
}


# ─── Einzeltitel-Hebel und Short-Fonds ─────────────────────────────────
#
# Ein 2x-Hebel auf EINE Aktie ist kein ETF und gehoert in keine
# Risikostufe. Das Risiko ist nicht "etwas hoeher als ein Fonds",
# es ist untergang oder gar nichts - der Kontrakt laeuft aus, es
# muss zu einem anderen Preis neu gekauft werden, und der Roll
# kostet bei hoher Volatilitaet viel.
#
# Gemessen am 29.09.2026: Risk 90 bestand zu einem Drittel aus
# 2x-Produkten auf einzelne Aktien (TSLG 2x TSLA, MUU 2x MU,
# PLTU 2x PLTR, ORCU 2x ORCL, MVLL 2x MRVL). Die Auswahl war
# "die vier umsatzstaerksten" - und Umsatz messen Handelbarkeit,
# nicht Eignung.

EINZELTITEL_HEBEL = re.compile(
    # Ziffer vor dem Wort: "2X Long", "3X Bull", "Daily Target 2X"
    # Kein \b nach "leverag": Yahoo schneidet Namen bei 25
    # Zeichen ab ("AdvisorShares MSOS Daily Levera"), dann
    # greift die Wortgrenze nicht mehr. Siehe Ursache 1.
    r"\b\d+\s*x\s*(?:long|short|bull|bear|leverag\w*|inverse)"
    # Ziffer nach dem Wort: "Small Cap Bull 3X" - das war die Luecke
    r"|\b(?:long|short|bull|bear|leverag\w*)\s*\d+\s*x\b"
    # Daily/Target in beliebiger Reihenfolge zur Ziffer
    r"|\b(?:daily|target)\b[^|]*?\b(?:2x|3x|4x)\b"
    r"|\b(?:2x|3x|4x)\b[^|]*?\b(?:daily|target)\b"
    # Ultra-Familie ohne Ziffer im Namen, aber 2x gemeint
    r"|\bultra\s*pro\b"
    # "ProShares Ultra S&P500": nach "S&P" folgt eine ZIFFER,
    # also gibt es dort keine Wortgrenze. Das \b am Ende hat
    # den Zweig nie erreicht. Weglassen.
    # QQQ ist der NASDAQ-100 und war nicht dabei - die vierte
    # Luecke in dieser Alternative, weil ich Indexnamen
    # aufzaehle statt das Muster zu pruefen.
    r"|\bultra(?:pro)?\s+(?:s&p|nasdaq|qqq|dow|russell|midcap|smallcap)"
    r"|\buultra\b"
    # "Daily" und "Leveraged" OHNE Ziffer im Namen.
    # "AdvisorShares MSOS Daily Leveraged ETF" traegt keine 2X,
    # ist aber ein 2x-Fonds. Ebenso die Direxion-Reihe mit
    # "Daily" und beliebigem Faktor.
    r"|\bleveraged\b"
    # Yahoo schneidet Namen bei 25 Zeichen ab. Nach einem
    # "Daily" kann das Wort daher ABGESCHNITTEN sein:
    # "AdvisorShares MSOS Daily Levera". Ein Muster mit einem
    # vollstaendigen Wort greift dort nicht.
    #
    # Deshalb Praefix statt Wort: "levera" deckt "leveraged"
    # und "leverage" mit ab. Im Finanzkontext bedeutet
    # "leverage" immer Hebel, die Unschärfe ist hier richtig.
    r"|\bdaily\s+\w{0,12}\s*levera"
    r"|\bdaily\s+\w{0,12}\s*\btarget\b"
    # Bull/Bear nur zusammen mit "Daily": die Direxion-Reihe
    # nutzt "Daily Bull/Bear", ein gewoehnlicher Fonds
    # mit "Bull" im Namen dagegen nicht.
    r"|\bdaily\s+\w{0,12}\s*\b(?:bull|bear)\b"
    # Hersteller, die ausschliesslich Hebelprodukte machen
    r"|\bleverage shares\b",
    re.I)

SHORT_FONDS = re.compile(r"\bshort\b|\bbear\b|\binverse\b|\bultrashort\b",
                         re.I)

# Titel, die nach diesem Muster KEIN ETF sind, aber als ETF
# gefuehrt werden. Ausgeschieden, nicht nur gemustert.
KEEP = {
    # Bewusst behalten: breite Short-Produkte in Risk 0 sind eine
    # Absicherung, kein Direktionswette. Wenn überhaupt, dann
    # ausdruecklich - nicht automatisch in der Stufenliste.
    "SPDN": "Risk 0",
    "SH": "Risk 0",
}


def ist_einzeltitel_hebel(name):
    return bool(EINZELTITEL_HEBEL.search(name or ""))


def ist_short_fonds(name):
    return bool(SHORT_FONDS.search(name or ""))


# ─── Krypto- und Weltraum-ETFs ─────────────────────────────────────────
#
# Ueber Beta 1,65 gibt es praktisch nur noch Halbleiter und Krypto
# (gemessen 29.09.2026, vollstaendig):
#   SOLZ 1,77   TETH 1,99   XRP 2,56   NASA 2,83
#
# Kein Fonds, sondern eine Wette auf eine Blockchain-Notierung.
# Fuer ein 50-Euro-Depot ist das keine Diversifikation: die
# vier Positionen folgen derselben Welle. Und sie handeln 24/7,
# waehrend die Depots nur zur Boersenzeit bewertet werden.
#
# Wer Krypto kaufen will, soll das ausdruecklich tun - nicht
# ueber eine Stufe, die "breit gestreut" verspricht.

KRYPTO = {
    "BTC", "IBIT", "FBTC", "GBTC", "ARKB", "BRRR", "EZBC", "BTCW",
    "BITQ", "WBTC", "BTCG", "BLOK", "BCH", "BSV",
    "ETH", "ETHA", "ETHE", "FETH", "EZET", "WETH", "CEX", "QETH",
    "SOL", "SOLT", "SOLV",
    "XRP", "XRPL", "TRIO",
    "LINK", "MSTR", "COIN", "HOOD",
    "DOG", "DOGE", "MEME",
    "LUNA", "LUNC", "UST",
    "SPACEX", "NASA",
    # TETH stand in Risk 90 und war nicht erfasst: der Praefix
    # "ETH" passt nicht auf "TETH", und in der Liste stand nur
    # ETH, ETHA, ETHE, EZET. Also: Liste pruefen reicht nicht,
    # der Titel muss auch gefunden werden.
    "TETH", "TETHW",
}


def ist_krypto(ticker):
    return ticker in KRYPTO or ticker.startswith(("BTC", "ETH", "SOL", "XRP"))


def ist_derivat(ticker, name=""):
    if ticker in DERIVATE or ticker.startswith(("MST", "NVD")):
        return True
    # 29.09.2026: Options-Einkommensfonds. Die fallen ueber die
    # Tickerliste nicht, weil jeder Anbieter eigene Symbole hat.
    # Der Abgleich laeuft auf dem normalisierten Namen, damit
    # "Option Income Strategy" und "Option Income" beide treffen.
    # Gleiches Muster wie ist_einzeltitel_hebel: Regex auf den
    # Namen, case-insensitive, ohne eigene Normalisierfunktion.
    return bool(AUSSCHUETTUNG_FONDS.search(name or ""))


def band(risk):
    return {
        0: (0.00, 0.35), 10: (0.35, 0.55), 20: (0.55, 0.70),
        30: (0.70, 0.85), 40: (0.85, 1.05), 50: (1.05, 1.20),
        # Risk 80 endet bei 1,90. Ein Versuch mit 2,05 ist
        # gemessen und wieder zurueckgenommen worden: Risk 80
        # waechst von 2 auf 6 Titel, Risk 90 schrumpft von 6 auf
        # 2. Nichts gewonnen, nur verschoben. Siehe Kopf.
        60: (1.20, 1.40), 70: (1.40, 1.65), 80: (1.65, 1.90),
        90: (1.90, 6.00),
    }[risk]


def _cache_lesen():
    if os.path.exists(BETACACHE):
        try:
            with io.open(BETACACHE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _cache_schreiben(c):
    tmp = BETACACHE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BETACACHE)


def markt_renditen(period="2y"):
    import yfinance as yf
    s = yf.Ticker(MARKT).history(period=period)["Close"]
    return s.pct_change().dropna()


def beta_rechnen(ticker, markt, periode="2y"):
    """Beta eines Titels gegen den Markt. Gibt (beta, n) zurueck."""
    import yfinance as yf
    try:
        s = yf.Ticker(ticker).history(period=periode)["Close"]
    except Exception:
        return None, 0
    if s is None or len(s) < 120:
        return None, 0
    r = s.pct_change().dropna()
    gemeinsam = r.index.intersection(markt.index)
    if len(gemeinsam) < 120:
        return None, len(gemeinsam)
    rv = r.loc[gemeinsam].values
    mv = markt.loc[gemeinsam].values
    m = float(mv.mean())
    var = float(((mv - m) ** 2).sum())
    if var <= 0:
        return None, len(gemeinsam)
    cov = float(((rv - rv.mean()) * (mv - m)).sum())
    return cov / var, len(gemeinsam)


def betas_nachladen(ticker_liste, markt=None, schlaf=0.2, meldung=True):
    """Betas fuer eine Tickerliste, mit Cache."""
    cache = _cache_lesen()
    if markt is None:
        markt = markt_renditen()
    fehlend = [t for t in dict.fromkeys(ticker_liste)
               if cache.get(t) is None]
    if fehlend:
        if meldung:
            log("    Beta fuer %d ETFs berechnen ..." % len(fehlend))
        for i, t in enumerate(fehlend, 1):
            b, n = beta_rechnen(t, markt)
            cache[t] = {"beta": b, "n": n} if b is not None else None
            if meldung and i % 25 == 0:
                log("      %d von %d" % (i, len(fehlend)))
            time.sleep(schlaf)
        _cache_schreiben(cache)
    return cache


def kandidaten_sammeln():
    """Einmal breit fragen, dann selbst einordnen.

    Kein Rendite-Filter: die ETFs werden ueber Beta eingeordnet, und
    ein Rendite-Band wuerde die breiten ETFs systematisch
    aussortieren (VTI, ARKK, VOO fielen so heraus).
    """
    import yfinance as yf
    from yfinance import ETFQuery
    r = yf.screen(ETFQuery("and", [
        ETFQuery("eq", ["region", "us"]),
        ETFQuery("gt", ["avgdailyvol3m", 1_000_000]),
    ]), size=250)   # Yahoo begrenzt die Query auf 250 (ValueError sonst)
    return r["quotes"]


def einordnen():
    """Erzeugt die 10 ETF-Stufen nach selbst berechnetem Beta."""
    quotes = kandidaten_sammeln()
    log("  Yahoo lieferte %d ETFs mit genuegend Volumen" % len(quotes))

    tickers = [q["symbol"] for q in quotes]
    markt = markt_renditen()
    cache = betas_nachladen(tickers, markt=markt)

    stufen = {s: [] for s in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90)}
    ohne_beta = 0

    ausgeschlossen = []

    for q in quotes:
        t = q["symbol"]

        # Der Anzeigename wird von Yahoo bei 25 Zeichen
        # abgeschnitten ("AdvisorShares MSOS Daily Levera").
        # Der lange Name ist vollstaendiger, also wird er
        # mitgeprueft - sonst haengt der Filter an der Laenge
        # des Anzeigenamens.
        #
        # 29.09.2026: Diese Zusammenstellung stand vorher NACH
        # ist_krypto() und wurde von ist_derivat() gebraucht,
        # das vorher nur den Ticker kannte. Beide Filter stehen
        # jetzt hier, hinter der Namensbildung - sonst gibt es
        # keine Namen, mit denen man sie fuettern kann.
        name_roh = " ".join(x for x in (q.get("shortName"),
                                        q.get("longName")) if x)

        if ist_derivat(t, name_roh):
            ausgeschlossen.append("%s (Derivat/Ausschuettung)" % t)
            continue
        if ist_krypto(t):
            ausgeschlossen.append("%s (Krypto/Weltraum)" % t)
            continue
        if ist_einzeltitel_hebel(name_roh):
            ausgeschlossen.append("%s (Einzeltitel-Hebel)" % t)
            continue
        if ist_short_fonds(name_roh) and t not in KEEP:
            ausgeschlossen.append("%s (Short-Fonds)" % t)
            continue
        eintrag = cache.get(t)
        b = eintrag.get("beta") if isinstance(eintrag, dict) else None
        if b is None:
            ohne_beta += 1
            continue
        b = float(b)
        av = abs(b)                      # Vorzeichen separat, s. Kopf
        for s in stufen:
            lo, hi = band(s)
            if lo <= av < hi:
                name = q.get("shortName") or q.get("longName") or t
                stufen[s].append({
                    "ticker": t,
                    "name": name[:40],
                    "preis": q.get("regularMarketPrice"),
                    "beta": round(b, 3),
                    "volumen": q.get("averageDailyVolume3Month"),
                    "rendite_52w": q.get("fiftyTwoWeekChangePercent"),
                    "netto": q.get("netAssets"),
                    "mehrfach": False,
                    "begruendung": (
                        "Beta %.2f selbst berechnet (n=%d Tage, 2y vs %s), "
                        "Vol %.1f Mio, 52W %+d%%, |Beta| in %.2f-%.2f%s"
                        % (b, eintrag.get("n", 0), MARKT,
                           (q.get("averageDailyVolume3Month") or 0) / 1e6,
                           q.get("fiftyTwoWeekChangePercent") or 0,
                           lo, hi,
                           " (negativ)" if b < 0 else "")),
                })
                break

    log("  ohne Beta: %d" % ohne_beta)
    log("  ausgeschlossen (Derivate, Einzeltitel-Hebel, Short): %d"
        % len(ausgeschlossen))
    for x in sorted(ausgeschlossen)[:14]:
        log("      %s" % x)
    if len(ausgeschlossen) > 14:
        log("      ... und %d weitere" % (len(ausgeschlossen) - 14))

    # Mehrfachzuordnung zaehlen (kommt bei |Beta| vor, wenn der
    # Marktwert 0,00 ist) und markieren
    zaehler = {}
    for s, liste in stufen.items():
        for k in liste:
            zaehler[k["ticker"]] = zaehler.get(k["ticker"], 0) + 1
    for s, liste in stufen.items():
        for k in liste:
            k["mehrfach"] = zaehler[k["ticker"]] > 1

    for s in sorted(stufen):
        log("    Risk %-3d %3d Kandidaten" % (s, len(stufen[s])))
    return stufen


def speichern(stufen):
    ziel = os.path.join(BASE, "screener_etf_beta.json")
    daten = {
        "zeitpunkt": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "quelle": "yfinance ETFQuery + selbst berechnetes Beta (2y vs %s)" % MARKT,
        "stufen": {str(s): stufen[s] for s in sorted(stufen)},
    }
    tmp = ziel + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ziel)
    log("  Gespeichert: %s" % ziel)
    return ziel


def main():
    log()
    log("=" * 70)
    log("  ETF-Stufen nach selbst berechnetem Beta")
    log("=" * 70)
    log()
    stufen = einordnen()
    speichern(stufen)
    gesamt = sum(len(v) for v in stufen.values())
    eindeutig = len({k["ticker"] for v in stufen.values() for k in v})
    log()
    log("  Gesamtkandidaten: %d, eindeutige Ticker: %d" % (gesamt, eindeutig))
    log()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
