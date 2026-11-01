# LIVE-NEWS-INVENTORY — Phase 0 Bestandsaufnahme

> Phase 0 des Arbeitsauftrags "Getrenntes Live-System, News-Plattform, Notfallsteuerung".
> Stand: 2026-08-12 · System v2.57.1 · Commit `b61f480`
> Erfasst gegen echten Code (keine funktionalen Änderungen in Phase 0).

## 1. News-Komponenten im Bestand

| Datei | Zweck | Status | Evidence |
|---|---|---|---|
| `news_monitor.py` | RSS-Ingestion (5 Feeds), Schreibt `news_cache.json` | VORHANDEN | 5 Feed-URLs im Code |
| `ki_news.py` | KI-Bewertung von News, Ticker-Mapping | VORHANDEN | 5 Feed-URLs (gleiche Quellen) |
| `news_evaluator.py` | News → Trading-Kontext (nutzt alten API-Key `OPENCODE_GO_API_KEY`) | VORHANDEN, TEILWEISE VERALTET | kein URL-Fund; KI-Rotation fehlt |
| `news_cache.json` | Persistierter News-Cache (Headlines) | VORHANDEN | Datei existiert, `headlines[]` befüllt |
| `spec_watch.json` / `spec_log.json` | Spekulations-Watchlist + Log | VORHANDEN | im Repo |

## 2. Aktive News-Quellen (RSS-Feeds, identisch in news_monitor + ki_news)

| # | Quelle | URL | Lizenzstatus | Priorität |
|---|---|---|---|---|
| 1 | Bloomberg Markets | `https://feeds.bloomberg.com/markets/news.rss` | UNGEPRÜFT (siehe NEWS-LICENSE-REVIEW) | P0-Kandidat |
| 2 | Dow Jones / MarketWatch | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | UNGEPRÜFT | P0-Kandidat |
| 3 | Yahoo Finance | `https://finance.yahoo.com/news/rssindex` | UNGEPRÜFT | P1 |
| 4 | NYT Economy | `https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml` | UNGEPRÜFT | P1 |
| 5 | Investopedia | `https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headlines` | UNGEPRÜFT | P2 |

> **Befund:** Keine Ticker-Mapping-Tabelle vorhanden. `news_evaluator.py` nutzt veralteten
> Key-Pfad (`OPENCODE_GO_API_KEY`) statt `ki_provider.call_ki` (siehe Memory: "news_evaluator.py
> nutzt alten OPENCODE_GO_API_KEY → ki_provider.call_ki"). Das ist ein P0-Blocker für Phase 5.

## 3. News-Datenfluss (aktuell, Paper-System)

```text
RSS-Feeds (5) ──▶ news_monitor.py ──▶ news_cache.json (headlines[])
                                    │
                                    └──▶ ki_news.py (Bewertung, gleiche Feeds)
                                                │
                                                └──▶ Trading-Kontext (ki_decisions)
```

## 4. Fehlende Komponenten für Live-News-Plattform

- [ ] Strukturiertes Ticker-Mapping (Firma → Ticker) — aktuell implizit/fehlend.
- [ ] Deduplizierung über Feed-Grenzen hinweg (Phase 4).
- [ ] P0/P1-Priorisierung bei Marktbewegung (Phase 3/4).
- [ ] Lizenzstatus je Quelle geprüft (NEWS-LICENSE-REVIEW).
- [ ] News-Feedfehler-Handling (Rate-Limit, Duplikate) — siehe Auftrag §Fehlerklassen.

## 5. Abhängigkeiten

- `ki_provider.py` (Free-Tier-Rotation) — in v2.51 repariert, läuft stabil.
- `markt_daten`-Tabelle (DB) — **leer** (blockiert Shadow→Paper-Persistenz, Auftrag Phase 2).
- `boersen.py` — steuert Cron-Zeitfenster (US-Börse ±15min, keine starren Schedules).

## 6. Nächste Schritte (Phase 3–5)

Inventory ist Basis für Phase 3 (Ingestion härten), Phase 4 (Filter/Dedup/Mapping),
Phase 5 (News-KI + Trading-Kontext). Keine Code-Änderung in Phase 0.
