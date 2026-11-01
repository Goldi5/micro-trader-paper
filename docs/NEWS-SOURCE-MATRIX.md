# NEWS-SOURCE-MATRIX — Phase 0

> Quellenmatrix für die News-Plattform. Grundlage für Phase 3 (Ingestion) und Phase 4
> (Filter, Deduplizierung, Ticker-Mapping). Stand: 2026-08-12 · v2.57.1.

## 1. Aktive Quellen (aus Code extrahiert)

| ID | Quelle | URL | Typ | Aktuell genutzt von | P0/P1 |
|---|---|---|---|---|---|
| S1 | Bloomberg Markets | `https://feeds.bloomberg.com/markets/news.rss` | RSS | news_monitor, ki_news | P0 |
| S2 | Dow Jones / MarketWatch | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | RSS | news_monitor, ki_news | P0 |
| S3 | Yahoo Finance | `https://finance.yahoo.com/news/rssindex` | RSS | news_monitor, ki_news | P1 |
| S4 | NYT Economy | `https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml` | RSS | news_monitor, ki_news | P1 |
| S5 | Investopedia | `https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headlines` | RSS | news_monitor, ki_news | P2 |

## 2. Fehlerklassen je Quelle (Auftrag §Fehlerklassen "News")

- Feedfehler (HTTP/Parse)
- Rate-Limit (429)
- fehlender API-Key
- Duplikate (gleiche Meldung in S1+S2)
- falsches Mapping (Firma≠Ticker)
- widersprüchliche Quellen
- KI-Ausfall bei Bewertung
- P0-Trigger (breaking news)
- P1-Priorisierung
- Lizenzstatus (siehe NEWS-LICENSE-REVIEW)

## 3. Ticker-Mapping (Status: FEHLT)

> Auftrag fordert explizites Ticker-Mapping (Firma → Ticker). Aktuell KEINE zentrale
> Mapping-Tabelle vorhanden. `news_evaluator.py` nutzt implizite/veraltete Logik.

**Vorgeschlagene Struktur (Phase 4 zu implementieren):**

```json
{
  "firmenname_map": {
    "NVIDIA": "NVDA",
    "Apple": "AAPL",
    "Tesla": "TSLA",
    "Bloomberg": null,
    "Federal Reserve": null
  }
}
```

- Nicht-börsennotierte Emittenten (Bloomberg, Fed) → `null` (kein Ticker, nur Kontext).
- Mapping wird in Phase 4 aus `spec_depots/*.json` + Aktien-Depots abgeleitet + manuell ergänzt.

## 4. Deduplizierung (Phase 4)

- Hash über Titel + ersten 200 Zeichen.
- Cross-Feed-Dedup: gleiche Meldung in S1+S2 → einmal speichern, Quellen aggregieren.
- Zeitfenster: 24h.

## 5. Priorisierung (Phase 3/4)

| Priorität | Auslöser | Aktion |
|---|---|---|
| P0 | "breaking", "crash", "halt", Kursbewegung >X% | sofortige KI-Bewertung + Trading-Kontext |
| P1 | Ticker in Depot/Benachrichtigungsliste | Bewertung in nächster Welle |
| P2 | Allgemein/Markt | Batch-Bewertung |

## 6. Qualitäts-/Latenz-Metriken (Phase 3 zu erfassen)

- `source_quality` (0–1)
- `source_latency` (Sekunden bis Ingestion)
- `provider_chain` (bei Rotation)

## 7. Nächste Schritte

- Phase 3: Ingestion härten (Fehlerklassen aus §2 abfangen).
- Phase 4: Dedup + Mapping (§3/§4) implementieren.
- NEWS-LICENSE-REVIEW: Lizenzstatus je Quelle klären (kommerzielle Nutzung?).
