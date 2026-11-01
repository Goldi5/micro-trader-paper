#!/usr/bin/env python3
"""Börsenzeiten-Modul: bestimmt pro Ticker die Heimatbörse und ob sie offen hat.

Ermöglicht den Tradern, Ticker geschlossener Börsen zu überspringen → spart
yfinance-API-Calls (~90% bei US-Tickern, da NYSE nur 6,5h/24h offen ist).

Börsen:
  - US   → NYSE/NASDAQ (Eastern Time, 09:30–16:00 ET)
  - XETRA → Europe/Berlin (09:00–17:30)
  - TSE  → Japan (Asia/Tokyo, 09:00–15:30 JST, Mittagspause 11:30–12:30)
  - HK   → Hongkong (Asia/Hong_Kong, 09:30–16:00 HKT) — optional, für .HK-Suffix
"""
import os
from datetime import datetime, timedelta

try:
    import pytz
except ImportError:
    pytz = None

# Suffix → Börse (yfinance-Konvention: .DE = Xetra, .T = Tokyo, .HK = Hongkong, .L = London)
SUFFIX_BOERSE = {
    ".DE": "XETRA", ".F": "XETRA", ".D": "XETRA",
    ".T": "TSE", ".TSE": "TSE",
    ".HK": "HK",
    ".L": "LSE", ".LN": "LSE",
    ".PA": "EURONEXT", ".AS": "EURONEXT", ".BR": "EURONEXT",
}
# Bekannte US-Ticker ohne Suffix → default "US"

BOERSEN = {
    "US":      {"tz": "US/Eastern",     "offen": (9, 30),  "zu": (16, 0),  "label": "🇺🇸 NYSE/NASDAQ"},
    "XETRA":   {"tz": "Europe/Berlin",   "offen": (9, 0),   "zu": (17, 30), "label": "🇪🇺 Xetra"},
    "TSE":     {"tz": "Asia/Tokyo",      "offen": (9, 0),   "zu": (15, 30), "label": "🇯🇵 Tokyo"},
    "HK":      {"tz": "Asia/Hong_Kong",  "offen": (9, 30),  "zu": (16, 0),  "label": "🇭🇰 Hongkong"},
    "LSE":     {"tz": "Europe/London",   "offen": (8, 0),   "zu": (16, 30), "label": "🇬🇧 London"},
    "EURONEXT": {"tz": "Europe/Paris",   "offen": (9, 0),   "zu": (17, 30), "label": "🇪🇺 Euronext"},
}
# TSE hat Mittagspause 11:30–12:30
TSE_MITTAG = True

_cache = {}
_cache_zeit = 0


def boerse_fuer_ticker(ticker):
    """Bestimmt die Heimatbörse eines Tickers (Suffix-basiert)."""
    t = (ticker or "").upper().strip()
    for suffix, boerse in SUFFIX_BOERSE.items():
        if t.endswith(suffix):
            return boerse
    return "US"  # Default: US-Aktie


def _jetzt(tz_name):
    if pytz:
        return datetime.now(pytz.timezone(tz_name))
    # Fallback ohne pytz: grobe UTC-Offsets (Sommerzeit nicht exakt)
    offsets = {
        "US/Eastern": -4, "Europe/Berlin": 2, "Asia/Tokyo": 9,
        "Asia/Hong_Kong": 8, "Europe/London": 1, "Europe/Paris": 2,
    }
    return datetime.utcnow() + timedelta(hours=offsets.get(tz_name, 0))


def jetzt_lokal():
    """Aktuelle Zeit in der Container-Zeitzone (Europe/Berlin), aware.

    Noetig fuer den Tagesbericht: ein naiver datetime.now() laesst
    den Vergleich mit schlusszeit() mit
    "can't compare offset-naive and offset-aware datetimes"
    scheitern - und die Pruefung faellt dann still auf die
    Stunden-Notloesung zurueck, die im Winter daneben liegt.
    """
    return _jetzt("Europe/Berlin")


def ist_offen(boerse, jetzt=None):
    """True, wenn die Börse gerade geöffnet hat (Werktag + Handelszeit + KEIN Feiertag)."""
    b = BOERSEN.get(boerse)
    if not b:
        return False
    now = jetzt or _jetzt(b["tz"])

    # Feiertags-Check (§12: keine falschen Ausführungen an Feiertagen)
    try:
        from feiertage import markt_geschlossen
        markt_map = {"NYSE": "US", "NASDAQ": "US", "XETRA": "DE", "TSE": "JP",
                     "US": "US", "DE": "DE", "JP": "JP"}
        m = markt_map.get(boerse, boerse)
        # Datum aus now extrahieren (datetime → date)
        datum = now.date() if hasattr(now, "date") else now
        geschlossen, grund = markt_geschlossen(m, datum)
        if geschlossen:
            return False
    except Exception:
        pass  # Fallback: ohne Feiertags-Check weiter

    if now.weekday() >= 5:  # Sa/So
        return False
    offen = now.replace(hour=b["offen"][0], minute=b["offen"][1], second=0, microsecond=0)
    zu = now.replace(hour=b["zu"][0], minute=b["zu"][1], second=0, microsecond=0)
    if boerse == "TSE" and TSE_MITTAG:
        # Mittagspause 11:30–12:30 JST
        pause_start = now.replace(hour=11, minute=30, second=0, microsecond=0)
        pause_ende = now.replace(hour=12, minute=30, second=0, microsecond=0)
        if pause_start <= now < pause_ende:
            return False
    return offen <= now < zu


def offene_boersen():
    """Liste aller gerade offenen Börsen."""
    return [b for b in BOERSEN if ist_offen(b)]

def next_open(boerse):
    """Berechnet die naechste Oeffnungszeit einer (auch geschlossenen) Boerse.
    Liefert (datetime, label) oder (None, '') wenn nicht berechenbar."""
    b = BOERSEN.get(boerse)
    if not b:
        return None, ''
    try:
        tz = pytz.timezone(b["tz"]) if pytz else None
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    # naechste 7 Tage durchsuchen (Werktag + Oeffnungszeit)
    for d in range(0, 8):
        tag = now + timedelta(days=d)
        if tag.weekday() >= 5:  # Sa/So ueberspringen
            continue
        open_t = tag.replace(hour=b["offen"][0], minute=b["offen"][1], second=0, microsecond=0)
        if open_t > now:
            return open_t, BOERSEN[boerse]["label"]
    return None, ''
def schlusszeit(boerse, jetzt=None):
    """Schlusszeit der Boerse am Tag von `jetzt` (aware datetime).

    Gegenstueck zu next_open(): nicht "wann faengt sie an",
    sondern "wann ist heute Schluss". Der Tagesreport braucht
    das, um den Handelstag zu definieren - eine feste Stunde
    im Code (22 Uhr) ist im Sommer der NYSE-Schluss und im
    Winter eine Stunde zu spaet.

    Rueckgabe: aware datetime, oder None wenn heute nicht
    gehandelt wird (Wochenende, Feiertag). None heisst "kein
    Schluss heute", nicht "nicht berechenbar".
    """
    b = BOERSEN.get(boerse)
    if not b:
        return None
    try:
        tz = pytz.timezone(b["tz"]) if pytz else None
    except Exception:
        tz = None
    if jetzt is None:
        now = datetime.now(tz) if tz else datetime.now()
    elif getattr(jetzt, "tzinfo", None) is not None:
        now = jetzt.astimezone(tz) if tz else jetzt
    else:
        # naiver Zeitstempel: als Lokalzeit der Boerse lesen
        now = (tz.localize(jetzt) if tz and hasattr(tz, "localize")
               else jetzt)
    if now.weekday() >= 5:
        return None
    zu = b.get("zu")
    if not zu:
        return None
    try:
        from feiertage import markt_geschlossen
        markt = b.get("markt")
        if markt and markt_geschlossen(markt, now.date())[0]:
            return None
    except Exception:
        pass
    return now.replace(hour=zu[0], minute=zu[1], second=0, microsecond=0)


def status_mit_next_open():
    """Liefert pro Boerse: offen? + naechste Oeffnung (falls zu)."""
    out = []
    for b in BOERSEN:
        o = ist_offen(b)
        no, lbl = (None, '') if o else next_open(b)
        out.append({
            "boerse": b,
            "label": BOERSEN[b]["label"],
            "offen": o,
            "next_open": no.strftime("%a %d.%m. %H:%M") if no else "-",
        })
    return out


def ticker_offen(ticker):
    """True, wenn die Heimatbörse des Tickers gerade offen hat."""
    return ist_offen(boerse_fuer_ticker(ticker))


def filter_offene_ticker(tickers):
    """Filtert Ticker auf die, deren Börse gerade offen hat."""
    return [t for t in tickers if ticker_offen(t)]


def status_text():
    """Kompakte Statuszeile für Logs."""
    offen = offene_boersen()
    if not offen:
        return "🔕 Alle Börsen geschlossen"
    return "🟢 Offen: " + ", ".join(BOERSEN[b]["label"] for b in offen)


def markt_regime(benchmark="SPY", markt="US"):
    """Phase 2.5 (§9): Marktregime-Klassifikation — PRO MARKT SEPARAT.

    US: SPY (S&P 500 ETF)
    DE: DAX (über .DE-Suffix, z.B. DAX-Symbol)
    JP: Nikkei (über .T-Suffix)

    Bull:   Kurs > 200-Tage-Linie & 50d > 200d (Aufwärtstrend)
    Bear:   Kurs < 200-Tage-Linie & 50d < 200d (Abwärtstrend)
    Seitwärts: sonst (wenig Trend)

    Liefert eines von 'bull'/'bear'/'seitwaerts' oder 'unbekannt' bei Fehler.
    """
    # Benchmark pro Markt (§5/§9: nicht gleichsetzen)
    benchmark_map = {
        "US": "SPY",
        "DE": "DAX.DE",   # Xetra DAX ETF
        "JP": "1321.T",   # Nikkei 225 ETF (Japan)
    }
    sym = benchmark if benchmark != "SPY" else benchmark_map.get(markt, "SPY")
    try:
        import yfinance as yf
        t = yf.Ticker(sym)
        hist = t.history(period="1y", interval="1d")
        if hist is None or len(hist) < 200:
            return "unbekannt"
        close = hist["Close"].dropna()
        if len(close) < 200:
            return "unbekannt"
        kurs = float(close.iloc[-1])
        sma200 = float(close.tail(200).mean())
        sma50 = float(close.tail(50).mean())
        if kurs > sma200 and sma50 > sma200:
            return "bull"
        if kurs < sma200 and sma50 < sma200:
            return "bear"
        return "seitwaerts"
    except Exception:
        return "unbekannt"


def regime_pro_markt():
    """Phase 2.5 (§9): Regime für alle 3 Märkte separat berechnen.
    Return: {markt: regime}"""
    return {
        "US": markt_regime(markt="US"),
        "DE": markt_regime(markt="DE"),
        "JP": markt_regime(markt="JP"),
    }


def regime_label(regime):
    return {"bull": "🟢 Bull", "bear": "🔴 Bear", "seitwaerts": "🟡 Seitwärts",
            "unbekannt": "❓ Unbekannt"}.get(regime, regime)


if __name__ == "__main__":
    print(status_text())
    for b in BOERSEN:
        print(f"  {b:8s} → {'🟢 offen' if ist_offen(b) else '🔴 zu'}")
    print("Regime (SPY):", markt_regime())
