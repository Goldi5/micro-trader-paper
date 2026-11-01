# LIVE-READINESS-TESTS — Phase 12

> Phase 12: Live-Readiness-Tests. Stand: 2026-08-12.

## Änderung

- **`test_live_readiness.py` (NEU):** Praktischer Check aller Live-Komponenten
  (Phase 7-11) ohne echten Broker. PAPER_ONLY. 12 Checks.
- `live_system.ReleaseRegistry` nutzt eigene `live_releases`-Tabelle
  (statt `live_requests` mit UNIQUE(tenant_id,status) Constraint).
- `LiveSystem.release_erlaubt` prüft `live_releases` (nicht mehr `live_requests`).

## Verifikation (ad-hoc, PASS)

```bash
python test_live_readiness.py
# -> ALLE TESTS PASS (12/12)
```

Checks: PAPER_ONLY-Default, safe_stop-Default, Kill-Switch an/aus,
Release PENDING→APPROVED, release_erlaubt, BrokerSim BUY/SELL/Reject,
Kill-Switch blockiert Order, Reconciliation match.

## Nächste Phase

**Phase 13 — Micro-Live-Vorbereitung** (1 Portfolio, harte Limits).
