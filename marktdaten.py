"""
marktdaten.py — Super-Mix Datenquelle (v2.16.8)

Löst das yfinance-Rate-Limit-Problem (Kurs = 0 → Crash-Risiko):
Live-Kurs wird über 4 Tiers bezogen, bis einer einen gültigen Preis liefert:

  Tier 1: yfinance  (kostenlos, aber instabil bei Rate-Limit)
  Tier 2: Finnhub  /quote        (60 calls/min — verlässlich)
  Tier 3: TwelveData /quote       (800 calls/day — Reserve)
  Tier 4: AlphaVantage GLOBAL_QUOTE (25 calls/day — tiefe Reserve)

Scan (663 Ticker, Historie/RSI/MACD) bleibt yfinance (einzige Free-Quelle,
die Bulk schafft). Bei yfinance-Exception: TwelveData time_series als Fallback.
"""
import os
import time
import json
import requests

BASE = os.path.dirname(os.path.abspath(__file__))

# ── Keys aus .env (via os.environ gesetzt durch ki_decisions/engine) ──
FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "")
ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_KEY", "")

# ── Cache (pro Prozess-Lauf) ──
_kurs_cache = {}
_scan_fallback_cache = {}

# Rate-Limit-Schutz: pro Tier einen "drossel bis" Timestamp merken
_drossel = {}


def _gedrosselt(tier, sekunden):
    """Gibt True zurück, wenn Tier noch im Cooldown ist."""
    bis = _drossel.get(tier, 0)
    if time.time() < bis:
        return True
    return False


def _setze_drossel(tier, sekunden):
    _drossel[tier] = time.time() + sekunden


def _yfinance_kurs(ticker):
    """Tier 1: yfinance (Original-Logik)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if len(hist) > 0 and "Close" in hist:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def _finnhub_kurs(ticker):
    """Tier 2: Finnhub /quote (60/min)."""
    if not FINNHUB_KEY or _gedrosselt("finnhub", 0):
        return 0.0
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": FINNHUB_KEY},
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            c = d.get("c", 0)
            if isinstance(c, (int, float)) and c > 0:
                return float(c)
        elif r.status_code == 429:  # Rate-Limit
            _setze_drossel("finnhub", 60)
    except Exception:
        pass
    return 0.0


def _twelvedata_kurs(ticker):
    """Tier 3: TwelveData /quote (800/day)."""
    if not TWELVEDATA_KEY or _gedrosselt("twelvedata", 0):
        return 0.0
    try:
        r = requests.get(
            "https://api.twelvedata.com/quote",
            params={"symbol": ticker, "apikey": TWELVEDATA_KEY},
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            if d.get("status") != "error":
                c = d.get("close", 0)
                if isinstance(c, (int, float)) and c > 0:
                    return float(c)
        elif r.status_code == 429:
            _setze_drossel("twelvedata", 3600)  # 1h
    except Exception:
        pass
    return 0.0


def _alphavantage_kurs(ticker):
    """Tier 4: AlphaVantage GLOBAL_QUOTE (25/day)."""
    if not ALPHAVANTAGE_KEY or _gedrosselt("alphavantage", 0):
        return 0.0
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": ALPHAVANTAGE_KEY},
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            q = d.get("Global Quote", {})
            p = q.get("05. price", "0")
            if p and float(p) > 0:
                return float(p)
        elif r.status_code == 429:
            _setze_drossel("alphavantage", 86400)  # 1 Tag
    except Exception:
        pass
    return 0.0


def hole_kurs(ticker):
    """
    Live-Kurs mit 4-Tier-Fallback.
    Liefert float > 0 bei Erfolg, sonst 0.0 (alter Verhalten erhalten).
    """
    if not ticker:
        return 0.0
    ticker = ticker.upper().strip()
    # Cache (5 Min gültig)
    if ticker in _kurs_cache:
        ts, preis = _kurs_cache[ticker]
        if time.time() - ts < 300:
            return preis
    preis = 0.0
    for tier_fn in (_yfinance_kurs, _finnhub_kurs, _twelvedata_kurs, _alphavantage_kurs):
        preis = tier_fn(ticker)
        if preis > 0:
            break
    _kurs_cache[ticker] = (time.time(), preis)
    return preis


def scan_fallback_yfinance(tickers, cache):
    """
    Fallback für scan_markt(): Wenn yfinance komplett ausfällt,
    hole Historie (close/high/low/volume) via TwelveData time_series.
    Achtung: 800 credits/day — nur bei yfinance-Totalausfall nutzen!
    """
    if not TWELVEDATA_KEY:
        return cache
    fehlen = [t for t in tickers if t not in cache]
    if not fehlen:
        return cache
    # Nur eine Batch-Anfrage pro Ticker (teuer) — begrenzt auf 50/Run als Schutz
    fehlen = fehlen[:50]
    for ticker in fehlen:
        try:
            r = requests.get(
                "https://api.twelvedata.com/time_series",
                params={"symbol": ticker, "interval": "1day", "outputsize": 60, "apikey": TWELVEDATA_KEY},
                timeout=20,
            )
            if r.status_code == 200:
                d = r.json()
                vals = d.get("values", [])
                if vals:
                    closes = [float(v["close"]) for v in vals]
                    highs = [float(v["high"]) for v in vals]
                    lows = [float(v["low"]) for v in vals]
                    vols = [float(v["volume"]) for v in vals]
                    aktuell = closes[0]
                    sma50 = sum(closes[:50]) / min(len(closes), 50)
                    sma20 = sum(closes[:20]) / min(len(closes), 20)
                    # RSI (14)
                    deltas = [closes[i] - closes[i + 1] for i in range(len(closes) - 1)]
                    gains = [max(d, 0) for d in deltas[:14]]
                    losses = [max(-d, 0) for d in deltas[:14]]
                    rs = (sum(gains) / 14) / (sum(losses) / 14) if sum(losses) > 0 else 100
                    rsi = 100 - (100 / (1 + rs)) if rs != 100 else 100
                    cache[ticker] = {
                        "aktuell": aktuell,
                        "sma50": sma50,
                        "sma20": sma20,
                        "rsi": round(rsi, 1),
                        "macd_bullish": 1 if closes[0] > sma20 else 0,
                        "bb_pos": 0.5,
                        "atr_pct": 0,
                        "vol_ratio": 1,
                        "uptrend": 1 if aktuell > sma50 else 0,
                        "datetime": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
        except Exception:
            continue
    return cache


# ── Kompatibilitäts-Aliase ──
def hole_kurs_fuer(ticker):
    """Alias für ki_decisions.py (import hole_kurs_fuer)."""
    return hole_kurs(ticker)
