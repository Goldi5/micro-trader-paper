# OPS-STATUS-DATENMODELL — Phase 1

> Phase 1: Datenmodell für den Betriebsstatus (zentrales Aggregat).
> Stand: v2.58.0+. Neues Modul `ops_status.py`. PAPER_ONLY (nur lesend).

## Änderung

- `ops_status.py` (NEU): `build_system_status()` aggregiert:
  - SystemStatus (health, paper_only, safe_stop, timestamps, active_release)
  - ProviderStatus (News-Feeds, Market-Data, KI, Simulator, **Live=NOT_AVAILABLE**)
  - ReleaseStatus (live_releases Tabelle)
  - PortfolioStatus (depot_*.json)
  - ReconciliationStatus (sim_broker_fills)
- Health-Logik: SAFE_STOP wenn Kill-Switch, WARNING bei altem Snapshot.

## Verifikation (ad-hoc, PASS)

```bash
python -c "from ops_status import build_system_status as b; s=b();
print(s['health'], s['paper_only'], len(s['providers']), len(s['portfolios']))"
# -> SAFE_STOP True 12 25  (Live-Broker NOT_AVAILABLE)
```

## Nächste Phase

**Phase 2 — Operations-Navigation** (Backend `operations.*` Rechte + Route-Schutz).
