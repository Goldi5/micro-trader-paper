# NEWS-FILTER-DEDUP-MAPPING — Phase 4

> Phase 4: News-Filter, Deduplizierung, Ticker-Mapping. Stand: 2026-08-12.

## Änderungen

1. **`news_ticker_map.py` (NEU):** Zentrale Firma→Ticker Mapping-Tabelle.
   - `FIRMENNAME_MAP`: Firma (lowercase) → Ticker. Nicht-börsennotierte Emittenten
     (Fed, Bloomberg, Citadel, SEC) → `None` (nur Kontext, kein Ticker).
   - `BEKANNTE_TICKER`: explizite Ticker-Liste (Depots + Spec).
   - `find_tickers(text)`: erkennt explizite Ticker (`AAPL`, `$TSLA`) + Firmennamen.
2. **`news_monitor.update_news()`:** Ticker-Suche über `find_tickers` (statt
   hartcodierter Liste). Deduplizierung: gleiche Headline (normalized) wird einmal
   behalten, Duplikate übersprungen.

## Verifikation (ad-hoc, PASS)

```bash
python -c "from news_ticker_map import find_tickers; print(find_tickers('Tesla rallies'))"
# -> ['TSLA']
python -c "import news_monitor as nm; nm.update_news()"
# -> 55 Headlines, 43 relevant, Ticker-Mapping in news_cache.json
```

## Offen (Phase 5)

- `news_evaluator.py` nutzt veralteten API-Key (`OPENCODE_GO_API_KEY`) → muss auf
  `ki_provider.call_ki` umstellen (P0-Blocker).
- P0/P1-Priorisierung nach Kursbewegung/Auslöser noch nicht implementiert.

## Nächste Phase

**Phase 5 — News-KI + Trading-KI-Kontext.**
