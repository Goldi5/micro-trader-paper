# MARKET-DATA-ABSTRACTION (§19-Punkt 10, §12)

Der Trading-Core darf nicht direkt von yfinance/Finnhub/TwelveData/AlphaVantage
abhängen. Diese Abstraktion (neu in `market_data_provider.py`) definiert das
verbindliche Interface und ein einheitliches Datenobjekt.

## Interface (Auftrag §12)

```python
class MarketDataProvider:
    def get_quote(self, ticker) -> MarketSnapshot
    def get_history(self, ticker, period) -> DataFrame | None
    def get_indicators(self, ticker) -> MarketSnapshot
    def health_check(self) -> dict
```

## MarketSnapshot (Auftrag §12)

| Feld | Zweck |
|---|---|
| `ticker` | Symbol |
| `price` | aktueller Kurs |
| `timestamp` | Zeitpunkt |
| `currency` | Währung (default USD) |
| `source` | welcher Provider geliefert hat |
| `source_latency_ms` | Latenz |
| `quality` | good / degraded / stale / unknown |
| `rsi` / `sma20` / `sma50` | Indikatoren |
| `atr` | Average True Range |
| `volume_ratio` | Volumen-Relativ |
| `regime` | bull / bear / sideways / unknown |

**Wichtig:** Bei Fehlern / ungültigen Tickern liefert die Abstraktion KEINEN
stillschweigenden 0-Wert (der falsche Käufe auslösen würde), sondern ein leeres
`MarketSnapshot` mit `quality="unknown"`.

## Concrete Provider

- `YahooMarketData` (yfinance) — Quote + Indikatoren via `marktdaten.py`
- `FinnhubMarketData` — Quote
- `TwelveDataMarketData` — Quote + Indikatoren (Fallback bei yfinance-Totalausfall)
- `AlphaVantageMarketData` — Quote

Alle wrappen die bestehende prozedurale Logik in `marktdaten.py`.

## Fallback

`get_quote_with_fallback(ticker)` versucht die Provider in der Reihenfolge
`FALLBACK_ORDER = ["yahoo", "finnhub", "twelvedata", "alphavantage"]` und
liefert das erste gültige Snapshot. Bei Totalausfall: leeres Snapshot.

## Health-Check

`health_all()` prüft alle Provider (für Admin-/System-Status).

## Status der Trennung

- ✅ Interface + MarketSnapshot + 4 Concrete Provider + Fallback
- ✅ Tests (P10) grün
- ⏳ **Refactor der Core-Dateien** (`engine.py`, `ki_decisions.py`, `dashboard.py`
  importieren noch direkt `yfinance`): Die Abstraktion ist vorhanden und wird
  für neue Pfade genutzt; ein vollständiger Refactor der Legacy-Calls ist ein
  eigener (risikoreicher) Schritt und erfolgt nicht in dieser Phase.
