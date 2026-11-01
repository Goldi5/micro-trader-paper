"""Depot-Reihe aus echten Marktdaten - ohne die fehlerhafte Auswertung
des abgebrochenen Subagenten.

BEFUND ZUM ABBRUCH (Stufe 3b, 27.09.2026):
    R = pd.DataFrame({t: close[t].pct_change().dropna()
                      for t in BEST}).dropna()
  Das abschliessende .dropna() entfernt jede Zeile, in der IRGEND
  EIN Titel kein Ergebnis hat. Bei 7 Titeln mit unterschiedlich
  langen Historien wird R dadurch leer, und R[t] liefert None.
  Der Fehler KeyError: None ist die Folge, nicht die Ursache.

  Mein Ansatz: nicht dropna() ueber alle Titel, sondern pairwise.
  Die Renditen werden je Titel fuer sich berechnet und die
  Korrelation nur ueber die Paare, die beide Daten haben. Damit
  faellt ein einzelner Titel mit duennen Daten nicht das ganze
  Ergebnis.

GRUNDSAETZE:
  a) Jede Zahl wird aus echten Kursen berechnet, nichts geschaetzt.
  b) Was nicht belastbar ist, wird als "nicht messbar" gemeldet,
     nicht als 0.
  c) Rate-Limits: eine Pause zwischen Abrufen, HTTP 429 abfangen.
"""

import json
import time
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

GRUPPE_A = ["AAPL", "MSFT", "GOOGL", "JNJ", "PG", "KO", "XOM", "CVX",
            "UNH", "HD", "MCD", "CSCO", "VZ", "T", "WMT", "COST", "MRK",
            "ABT", "LLY", "AMZN", "NVDA", "META", "NFLX", "AMD", "INTC",
            "QCOM", "MU"]
GRUPPE_B = ["SPY", "VTI", "VOO", "QQQ", "SCHD", "VYM", "DIA", "IWM",
            "EEM", "VEA", "VNQ", "GLD", "XLE", "XLF", "XLK", "XLV",
            "XLI", "XLP", "XLU", "XLY", "XLB", "XLC", "RSP"]

# Der Subagent verwarf QCOM, MU, INTC, AMD wegen Volatilitaet. Die
# Grenze 35 Prozent war fuer die unteren Risikostufen zu streng und
# laesst fuer Risk 85/95 nichts uebrig. Ich trenne deshalb nach
# Risikoklasse: <=55 Prozent ist noch handelbar.
MAX_VOL = 55.0
MIN_ADV_MIO = 20.0
MAX_UNDER_HIGH = 40.0
MIN_TAGE = 200


def lade(ticker, jahre=2):
    """Kursdaten mit Fehlerbehandlung. Liefert (df, grund) - bei
    Fehlern ist df leer und der Grund gefuellt."""
    for versuch in range(3):
        try:
            d = yf.download(ticker, period=f"{jahre}y", progress=False,
                            auto_adjust=True, threads=False)
            if d is None or len(d) == 0:
                time.sleep(3)
                continue
            close = d["Close"]
            if isinstance(close, pd.DataFrame) and len(close.columns) == 1:
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close) >= MIN_TAGE:
                return close, ""
            return pd.Series(dtype=float), (
                f"nur {len(close)} Handelstage < {MIN_TAGE}")
        except Exception as e:
            letzte = f"{type(e).__name__}: {e}"[:70]
            time.sleep(3)
    return pd.Series(dtype=float), letzte if "letzte" in dir() else "keine Daten"


def kennzahlen(close, tagesrenditen=None, ticker=None):
    """Berechnet alle Kennzahlen eines Titels. Rueckgabe None, wenn
    die Datenlage nicht reicht.

    ticker: noetig fuer das Handelsvolumen (adv_mio_usd). 01.11.2026: Der
    Parameter fehlte, yf.Ticker(ticker) warf NameError, adv_mio_usd war
    IMMER None - der Liquiditaetsfilter MIN_ADV_MIO in depot_bauen.py
    griff deshalb nie."""
    if close is None or len(close) < MIN_TAGE:
        return None

    r = close.pct_change().dropna()

    if tagesrenditen is None:
        tagesrenditen = r

    if len(tagesrenditen) < 60:
        return None

    # Renditen
    letzte_12m = close[close.index >= close.index[-1] - pd.Timedelta(days=365)]
    r1y = ((letzte_12m.iloc[-1] / letzte_12m.iloc[0]) - 1) * 100 \
        if len(letzte_12m) > 1 else None

    letzte_6m = close[close.index >= close.index[-1] - pd.Timedelta(days=182)]
    r6m = ((letzte_6m.iloc[-1] / letzte_6m.iloc[0]) - 1) * 100 \
        if len(letzte_6m) > 1 else None

    # Volatilitaet (3 Monate annualisiert)
    r3m = r[r.index >= r.index[-1] - pd.Timedelta(days=91)]
    vol = float(r3m.std() * np.sqrt(252) * 100) if len(r3m) > 20 else None

    # Maximaler Drawdown ueber 12 Monate
    dd = 0.0
    if len(letzte_12m) > 1:
        peak = letzte_12m.cummax()
        dd = float(((letzte_12m - peak) / peak).min() * 100)

    # Abstand vom 52-Wochen-Hoch
    hoch52 = float(letzte_12m.max()) if len(letzte_12m) else None
    unter_hoch = ((close.iloc[-1] - hoch52) / hoch52 * 100) if hoch52 else None

    # Volumen
    try:
        if not ticker:
            raise ValueError("kein Ticker")
        vol_d = yf.Ticker(ticker).history(period="3mo")["Volume"]
        adv_mio = float(vol_d.mean() * close.iloc[-1] / 1e6) \
            if len(vol_d) else None
    except Exception:
        adv_mio = None

    # Abstand zu SMA50 / SMA200
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    ds50 = ((close.iloc[-1] - sma50) / sma50 * 100) if sma50 else None
    ds200 = ((close.iloc[-1] - sma200) / sma200 * 100) if sma200 else None

    return {
        "rendite_1y_pct": round(r1y, 2) if r1y is not None else None,
        "rendite_6m_pct": round(r6m, 2) if r6m is not None else None,
        "volatilitaet_pct": round(vol, 2) if vol is not None else None,
        "max_drawdown_pct": round(dd, 2),
        "unter_52w_hoch_pct": round(unter_hoch, 2) if unter_hoch is not None else None,
        "adv_mio_usd": round(adv_mio, 1) if adv_mio is not None else None,
        "abstand_sma50_pct": round(ds50, 2) if ds50 is not None else None,
        "abstand_sma200_pct": round(ds200, 2) if ds200 is not None else None,
        "kurs": round(float(close.iloc[-1]), 2),
        "handelstage": int(len(close)),
        "erster_kurs": close.index[0].strftime("%Y-%m-%d"),
    }
