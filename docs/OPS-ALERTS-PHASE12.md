# OPS-ALERTS — Phase 12

> Phase 12: Monitoring und Alerts. Stand: v2.58.0+. `ops_alerts.py` + Route.
> PAPER_ONLY.

## Änderung

- `ops_alerts.py` (NEU): `evaluate_alerts()` prüft SystemStatus + erzeugt Alerts bei:
  System DEGRADED/BLOCKED/SAFE_STOP, Providerfehler, News-Ausfall, Datenalter,
  P0-News, Reconciliationfehler, abgelaufenem Release. `list_alerts/ack_alert/resolve_alert`.
  Alerts in `ops_alerts.json` (isoliert, keine Secrets).
- `dashboard.py`: `GET /api/ops_alerts` (auth-guarded).
- `dashboard.html`: Alerts-Panel + `renderOpsAlerts()` (severity-gefärbt).

## Verifikation

Backend compile OK, JS node --check OK, Route 401 ohne Auth. Dashboard neu gestartet.

## Nächste Phase

**Phase 13 — Tests** (test_ops_center.py).
