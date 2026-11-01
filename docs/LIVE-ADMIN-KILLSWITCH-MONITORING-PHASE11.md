# LIVE-ADMIN-KILLSWITCH-MONITORING — Phase 11

> Phase 11: Live-Admin, Kill-Switch, Monitoring. Stand: 2026-08-12.

## Änderungen

- `dashboard.py`:
  - `POST /api/live_kill_switch`: manueller Kill-Switch (ADMIN-only).
    Body `{aktion:'on'|'off', grund}`. Ruft `LiveSystem.kill_switch_aktivieren/freigeben`.
  - `GET /api/live_status`: Monitoring-Schicht (AUTHENTICATED). `LiveSystem.status()`.
- `live_system.py` (Phase 7): `kill_switch_aktivieren/freigeben` + `ist_gestoppt`.

## Verifikation (ad-hoc, PASS)

```bash
# Routen liefern 401 ohne Login (Auth-Guard OK)
GET /api/live_status       -> HTTP 401
POST /api/live_kill_switch -> HTTP 401
```

PAPER_ONLY: Kill-Switch ist Struktur, keine echte Order-Unterbrechung
(da keine echten Orders existieren). Bei Phase 14 aktiv: BrokerSimulator
+ echter Adapter prüfen `LiveSystem.ist_gestoppt` vor jeder Order.

## Nächste Phase

**Phase 12 — Live-Readiness-Tests.**
