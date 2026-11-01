# NEWS-INGESTION — Phase 3

> Phase 3: News-Quellen + Ingestion härten. Stand: 2026-08-12.

## Änderungen

1. `news_monitor.fetch_rss(url)` gibt jetzt `(items, fehler)` zurück.
   `fehler`: None | `'ratelimit'` (429) | `'http'` | `'timeout'` | `'parse'` | `'other'`.
   → Fehlerklassen aus NEWS-SOURCE-MATRIX §2 werden unterschieden (nicht mehr blind `[]`).
2. `news_monitor.update_news()` loggt Feed-Status pro Quelle + schreibt `feed_status`
   in `news_cache.json` (für Monitoring/Phase 11).
3. `socket` import ergänzt (für `socket.timeout`).

## Verifikation (ad-hoc, PASS)

```bash
python -c "import news_monitor as nm; nm.update_news()"
# -> 55 Headlines, 42 relevant
# -> feed_status: {dowjones:[10,None], yahoo:[50,None], investopedia:[0,'http'],
#                   bloomberg:[20,None], nyt:[20,None]}
```

Investopedia liefert `http`-Fehler (403/404) — Quelle ist instabil, aber andere 4
feeds funktionieren. Kein Abbruch des Gesamt-Laufs.

## Offen (Phase 4)

- Ticker-Mapping: `update_news` nutzt hartcodierte Ticker-Liste (AAPL, TSLA, …).
  Auftrag fordert zentrale Mapping-Tabelle (Firma→Ticker). Phase 4.
- Deduplizierung: aktuell keine Cross-Feed-Dedup. Phase 4.
- P0/P1-Priorisierung: noch nicht nach Kursbewegung/Auslöser. Phase 4.

## Nächste Phase

**Phase 4 — News-Filter, Deduplizierung, Ticker-Mapping.**
