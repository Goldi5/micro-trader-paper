# OPERATIONS-CENTER-INVENTORY — Phase 0

> Bestandsaufnahme der für das Operations Center (Auftrag 2026-08-12) relevanten
> Komponenten. Stand: v2.58.0 (Commit 2cbaeb8). PAPER_ONLY aktiv.

## Backend-Module (vorhanden, Basis für Cockpits)

| Modul | Zweck | Status |
|---|---|---|
| `dashboard.py` | Flask-App, 91 Routen, Auth/Permissions | vorhanden |
| `live_system.py` | `LiveSystem` (isoliert) + `ReleaseRegistry` (live_releases Tabelle) | vorhanden (Phase 7/8) |
| `broker_simulator.py` | `BrokerAdapter` ABC + `BrokerSimulator` (keine echten Orders) | vorhanden (Phase 9) |
| `news_monitor.py` | RSS-Ingestion, Fehlerklassen, feed_status | vorhanden (Phase 3) |
| `news_evaluator.py` | KI-News-Bewertung via ki_provider, schreibt ki_log typ=news | vorhanden (Phase 5) |
| `news_ticker_map.py` | zentrale Firma→Ticker Mapping | vorhanden (Phase 4) |
| `market_snapshot.py` | `MarketSnapshot` (tenant_id, workspace_id) | vorhanden (Phase 2) |
| `markt_daten_fuellen.py` | persistiert markt_daten (Scheduler) | vorhanden (Phase 1) |
| `ki_decisions.py` | Trading-KI + news_fuer_ticker | vorhanden |
| `freigabe_checkliste.py` | Vier-Augen/MFA-Checkliste | vorhanden (Phase 14) |
| `backup.py` | Snapshots (create_snapshot/restore) | vorhanden |
| `test_live_readiness.py` | 12 Live-Readiness-Checks | vorhanden (Phase 12) |
| `test_server_security.py` | Security-Tests (Tenant/Rollen/MFA/CSRF) | vorhanden |

## Vorhandene API-Routen (Operations-relevant)

- Depot-Steuerung: `/api/depot_pause`, `/api/depot_verkaufen`, `/api/depot_schliessen`,
  `/api/depot_loeschen`, `/api/depot_neu` (POST) — alle auth-guarded (401).
- Live-System: `/api/live_status` (AUTH), `/api/live_kill_switch` (ADMIN).
- News: `news_cache.json` (feed_status, headlines, tickers).
- Provider/Market: `markt_daten` Tabelle, MarketSnapshot.
- Audit: `security_audit.jsonl` (1722 Einträge).
- Release: `live_releases` Tabelle (ReleaseRegistry).

## Datenbanktabellen (21, relevant für Cockpits)

markt_daten, ki_decisions, depot_snapshot, trades, live_requests, **live_releases** (neu),
security_audit, tenant_*, user_*, u.a.

## FEHLEND für Operations Center (Gap → siehe Gap-Analysis)

- Kein `SystemStatus`-Aggregat (zentraler Betriebsstatus).
- Keine Operations-Navigation im Dashboard (kein "Operations"-Tab).
- Keine Cockpit-Routen (`/api/ops_system`, `/api/ops_news`, `/ops_risk`, etc.).
- Kein Staging-Durchlauf-Endpunkt.
- Kein Alert-Modell (Phase 12).
- Dashboard-HTML hat keine Operations-Bereiche (nur bestehende Lern/Portfolio/System).

## Berechtigungen (vorhanden)

`sec.access_level_met(role, level)`: AUTHENTICATED / ADMIN / SUPERADMIN.
Operations-spezifische Rechte (`operations.*`) noch NICHT als feingranulare Flags
implementiert — aktuell nur Grobraster (AUTH/ADMIN).
