# MARKETSNAPSHOT — Phase 2

> Phase 2: MarketSnapshot-Objekt + Marktdatenpersistenz. Stand: 2026-08-12.

## Status

| Komponente | Status | Evidence |
|---|---|---|
| `market_snapshot.py` (MarketSnapshot) | VORHANDEN + erweitert | `snapshot_id`, `ticker`, `timestamp`, `kurs`, `rsi`, `sma20`, `sma50`, `tenant_id`, `workspace_id` |
| `marktdaten.py` (hole_kurs) | VORHANDEN | 4-Tier-Fallback (yfinance/finnhub/twelvedata/alphavantage) |
| `market_data_provider.py` (MarketDataProvider) | VORHANDEN | Provider-Abstraktion + `to_dict()` |
| `markt_daten` Tabelle (SQLite) | PERSISTENT | Phase 1: Scheduler füllt sie (P0-Blocker behoben) |

## Änderungen Phase 2

1. `MarketSnapshot.__init__` akzeptiert `tenant_id` (Default 1) + `workspace_id`
   → tenant-scope vorbereitet für späteres Live-System (Phase 7).
2. **Bug-Fix:** `kontext()` crashte bei Tickern ohne Daten (`KeyError`).
   Robust: `if t in self.daten`.

## Mindestfelder (Auftrag §Phase 2) — Abdeckung

| Feld | Vorhanden? | Quelle |
|---|---|---|
| snapshot_id | ✅ | md5-Hash der Kursdaten |
| tenant_id | ✅ (Phase 2) | MarketSnapshot-Param |
| workspace_id | ✅ (Phase 2) | MarketSnapshot-Param |
| ticker | ✅ | Schlüssel |
| timestamp | ✅ | `zeit` |
| provider | ⚠️ indirekt | `marktdaten.hole_kurs` (4-Tier, aber nicht im Snapshot gespeichert) |
| provider_chain | ❌ | nicht im Snapshot (später bei Provider-Rotation erfassen) |
| source_quality | ❌ | nicht im Snapshot |
| source_latency | ❌ | nicht im Snapshot |
| price | ✅ | `kurs` |
| currency | ⚠️ | USD implizit (US-Börse), nicht explizit Feld |
| sma20/sma50 | ✅ | aus markt_daten |

> **Hinweis:** `provider`/`provider_chain`/`source_quality`/`source_latency`/`currency`
> sind im Snapshot nicht als Felder — das ist für Phase 3 (News) / Phase 7 (Live) nachzureichen,
> wenn Provider-Rotation explizit getrackt wird. Aktuell reicht es für Paper-System.

## Nächste Phase

**Phase 3 — News-Quellen + Ingestion:** `news_monitor.py` härten (Fehlerklassen aus
NEWS-SOURCE-MATRIX §2 abfangen), `markt_daten_fuellen` läuft bereits im Scheduler.
