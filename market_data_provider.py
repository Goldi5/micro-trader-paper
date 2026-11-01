"""
MarketDataProvider-Abstraktion (Auftrag §12).

Definiert das verbindliche Interface `MarketDataProvider`, sodass der Trading-Core
NIEMT direkt von yfinance/Finnhub/TwelveData/AlphaVantage abhaengt. Alle
Konkreten Provider (YahooMarketData, FinnhubMarketData, ...) implementieren dasselbe
Interface und liefern ein einheitliches `MarketSnapshot`-Objekt zurueck.

Bestehende `marktdaten.py` (prozeduraler Fallback) wird als Backend weiterhin
genutzt — diese Klassen wrappen sie, um das §12-Interface zu erfuellen.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import time


# ── MarketSnapshot (einheitliches Datenobjekt, Auftrag §12) ─────────────
@dataclass
class MarketSnapshot:
    ticker: str
    price: float = 0.0
    timestamp: str = ""
    currency: str = "USD"
    source: str = ""
    source_latency_ms: int = 0
    quality: str = "unknown"   # good | degraded | stale | unknown
    rsi: Optional[float] = None
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    atr: Optional[float] = None
    volume_ratio: Optional[float] = None
    regime: str = "unknown"    # bull | bear | sideways | unknown

    def to_dict(self):
        return asdict(self)

    @classmethod
    def empty(cls, ticker, reason="no_data"):
        return cls(ticker=ticker, price=0.0, quality="unknown",
                   regime="unknown", source=reason)


# ── Interface ───────────────────────────────────────────────────────────
class MarketDataProvider:
    """Basis-Interface (Auftrag §12). Konkrete Provider muessen alle 4 Methoden
    implementieren und MarketSnapshot zurueckgeben."""

    name = "base"

    def get_quote(self, ticker):
        raise NotImplementedError

    def get_history(self, ticker, period="3mo"):
        raise NotImplementedError

    def get_indicators(self, ticker):
        raise NotImplementedError

    def health_check(self):
        raise NotImplementedError

    # ── Default-Implementierung: leeres Snapshot bei Fehler (kein stiller 0-Wert) ──
    def _safe_snapshot(self, ticker, fn):
        """Wrapper: fn() liefert MarketSnapshot oder wirft; bei Exception ->
        leeres Snapshot mit quality=unknown (kein falscher Kauf)."""
        try:
            snap = fn()
            if snap is None or (isinstance(snap, MarketSnapshot) and snap.price <= 0):
                return MarketSnapshot.empty(ticker, reason=f"{self.name}:no_quote")
            return snap
        except Exception:
            return MarketSnapshot.empty(ticker, reason=f"{self.name}:error")


# ── Concrete: Yahoo (yfinance) ─────────────────────────────────────────
class YahooMarketData(MarketDataProvider):
    name = "yahoo"

    def get_quote(self, ticker):
        def _fn():
            import marktdaten as md
            p = md.hole_kurs(ticker)
            return MarketSnapshot(
                ticker=ticker, price=p,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                source="yahoo", quality="good" if p > 0 else "unknown")
        return self._safe_snapshot(ticker, _fn)

    def get_history(self, ticker, period="3mo"):
        try:
            import yfinance as yf
            df = yf.Ticker(ticker).history(period=period)
            return df
        except Exception:
            return None

    def get_indicators(self, ticker):
        def _fn():
            import marktdaten as md
            cache = md.scan_fallback_yfinance([ticker], {})
            d = cache.get(ticker, {})
            return MarketSnapshot(
                ticker=ticker,
                price=d.get("aktuell", 0.0),
                timestamp=d.get("datetime", ""),
                source="yahoo",
                quality="good" if d else "unknown",
                rsi=d.get("rsi"), sma20=d.get("sma20"), sma50=d.get("sma50"),
                volume_ratio=d.get("vol_ratio"),
                regime=("bull" if d.get("uptrend") else "bear"))
        return self._safe_snapshot(ticker, _fn)

    def health_check(self):
        try:
            p = self.get_quote("AAPL")
            return {"provider": self.name, "ok": p.price > 0, "price": p.price}
        except Exception as e:
            return {"provider": self.name, "ok": False, "error": str(e)}


# ── Concrete: Finnhub ─────────────────────────────────────────────────
class FinnhubMarketData(MarketDataProvider):
    name = "finnhub"

    def get_quote(self, ticker):
        def _fn():
            import marktdaten as md
            p = md._finnhub_kurs(ticker)
            return MarketSnapshot(
                ticker=ticker, price=p,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                source="finnhub", quality="good" if p > 0 else "unknown")
        return self._safe_snapshot(ticker, _fn)

    def get_history(self, ticker, period="3mo"):
        return None  # nicht via Finnhub im PAPER_ONLY-Modus

    def get_indicators(self, ticker):
        return MarketSnapshot.empty(ticker, reason="finnhub:no_indicators")

    def health_check(self):
        try:
            p = self.get_quote("AAPL")
            return {"provider": self.name, "ok": p.price > 0, "price": p.price}
        except Exception as e:
            return {"provider": self.name, "ok": False, "error": str(e)}


# ── Concrete: TwelveData ───────────────────────────────────────────────
class TwelveDataMarketData(MarketDataProvider):
    name = "twelvedata"

    def get_quote(self, ticker):
        def _fn():
            import marktdaten as md
            p = md._twelvedata_kurs(ticker)
            return MarketSnapshot(
                ticker=ticker, price=p,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                source="twelvedata", quality="good" if p > 0 else "unknown")
        return self._safe_snapshot(ticker, _fn)

    def get_history(self, ticker, period="3mo"):
        return None

    def get_indicators(self, ticker):
        def _fn():
            import marktdaten as md
            cache = md.scan_fallback_yfinance([ticker], {})
            d = cache.get(ticker, {})
            return MarketSnapshot(
                ticker=ticker, price=d.get("aktuell", 0.0), source="twelvedata",
                quality="good" if d else "unknown",
                rsi=d.get("rsi"), sma20=d.get("sma20"), sma50=d.get("sma50"),
                volume_ratio=d.get("vol_ratio"),
                regime=("bull" if d.get("uptrend") else "bear"))
        return self._safe_snapshot(ticker, _fn)

    def health_check(self):
        try:
            p = self.get_quote("AAPL")
            return {"provider": self.name, "ok": p.price > 0, "price": p.price}
        except Exception as e:
            return {"provider": self.name, "ok": False, "error": str(e)}


# ── Concrete: AlphaVantage ─────────────────────────────────────────────
class AlphaVantageMarketData(MarketDataProvider):
    name = "alphavantage"

    def get_quote(self, ticker):
        def _fn():
            import marktdaten as md
            p = md._alphavantage_kurs(ticker)
            return MarketSnapshot(
                ticker=ticker, price=p,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                source="alphavantage", quality="good" if p > 0 else "unknown")
        return self._safe_snapshot(ticker, _fn)

    def get_history(self, ticker, period="3mo"):
        return None

    def get_indicators(self, ticker):
        return MarketSnapshot.empty(ticker, reason="alphavantage:no_indicators")

    def health_check(self):
        try:
            p = self.get_quote("AAPL")
            return {"provider": self.name, "ok": p.price > 0, "price": p.price}
        except Exception as e:
            return {"provider": self.name, "ok": False, "error": str(e)}


# ── Provider-Registry + Fallback ────────────────────────────────────────
PROVIDER_REGISTRY = {
    "yahoo": YahooMarketData,
    "finnhub": FinnhubMarketData,
    "twelvedata": TwelveDataMarketData,
    "alphavantage": AlphaVantageMarketData,
}

# Reihenfolge des Fallbacks (wie marktdaten.hole_kurs)
FALLBACK_ORDER = ["yahoo", "finnhub", "twelvedata", "alphavantage"]


def get_provider(name):
    """Liefert eine Provider-Instanz nach Name (None wenn unbekannt)."""
    cls = PROVIDER_REGISTRY.get(name)
    return cls() if cls else None


def get_quote_with_fallback(ticker, order=None):
    """Holt Quote ueber Fallback-Kette; liefert erstes gueltiges MarketSnapshot.
    Bei Totalausfall: leeres Snapshot (quality=unknown, kein stiller 0-Kauf)."""
    order = order or FALLBACK_ORDER
    last_err = None
    for name in order:
        prov = get_provider(name)
        if not prov:
            continue
        snap = prov.get_quote(ticker)
        if snap and snap.price > 0:
            return snap
        last_err = snap.source if snap else name
    return MarketSnapshot.empty(ticker, reason=f"fallback_exhausted:{last_err}")


def get_indicators_with_fallback(ticker, order=None):
    """Holt Indikatoren ueber Fallback-Kette."""
    order = order or FALLBACK_ORDER
    for name in order:
        prov = get_provider(name)
        if not prov:
            continue
        snap = prov.get_indicators(ticker)
        if snap and snap.price > 0 and snap.rsi is not None:
            return snap
    # Wenigstens Quote versuchen
    return get_quote_with_fallback(ticker, order)


def health_all():
    """Alle Provider checken (fuer /api/providers-status)."""
    out = {}
    for name in FALLBACK_ORDER:
        prov = get_provider(name)
        if prov:
            out[name] = prov.health_check()
    return out
