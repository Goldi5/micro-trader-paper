# OPS-STAGING-FLOW — Phase 11

> Phase 11: End-to-End Staging-Durchlauf. Stand: v2.58.0+. `ops_staging.py`.
> PAPER_ONLY, Test-Tenant 99, Simulator.

## Änderung

- `ops_staging.py` (NEU): `run_staging()` testet alle 15 Phasen der Kette:
  news_fetch → filter → dedup → ki → snapshot → trading_ki → release_check
  → risk_gates → order_intent → paper_order → order_sync → portfolio_update
  → reconciliation → dashboard_update → audit_check.
- Test-Tenant (99), Simulator (cash 100). Kill-Switch im Staging temporär
  freigegeben (nur Test-Tenant), damit Sim-Orders laufen. Keine echten Orders.

## Verifikation (ad-hoc, PASS)

```bash
python -c "from ops_staging import run_staging; r=run_staging(); print(r['status'], r['phases_done'])"
# -> COMPLETED 15/15, alle Phasen OK/FILLED, Reconciliation MATCH
```

## Nächste Phase

**Phase 12 — Monitoring/Alerts** (ops_alerts Modell).
