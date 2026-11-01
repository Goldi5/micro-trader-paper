# PAPER-SYSTEM-BASELINE — Phase 0 Bestandsaufnahme

> Baseline des bestehenden Paper-/Shadow-Systems vor Live-Vorbereitung.
> Stand: 2026-08-12 · v2.57.1 · Commit `b61f480` · gemessen gegen echten Code + Laufzeit.

## 1. System-Identifikation

| Feld | Wert | Evidence |
|---|---|---|
| System-Version | v2.57.1 | `version.json` (build 2026-08-12_1130) |
| Letzter Commit | `b61f480` | `git log` |
| PAPER_ONLY | TRUE (hart) | `dashboard.py` / Security-Gates |
| Dashboard | Flask, Port 5300, 127.0.0.1-only | `app.run(host="127.0.0.1", port=5300)` |
| Python | venv `C:/Users/goldi/AppData/Local/hermes/hermes-agent/venv` | psutil-Prozessliste |

## 2. Depots (Bestand)

| Kategorie | Dateien | Anzahl | Evidence |
|---|---|---|---|
| Aktien | `depot_*.json` | (gemessen zur Laufzeit) | glob `depot_*.json` |
| ETF | `etf_*.json` | (gemessen zur Laufzeit) | glob `etf_*.json` |
| Spekulation | `spec_depots/*.json` | 13 (BB, BBAI, CRSP, FNGU, MRNA, NRGU, PLTR, QS, SOUN, TNA, …) | `spec_depots/` |

> **NEU in v2.57.0:** Eindeutige `depot_uid` — mehrere Depots pro Risiko-Stufe möglich
> (`aktien:100`, `aktien:100:1`, `aktien:100:2`). Vorher: Kollision "Depot existiert schon".

## 3. Datenbank (21 Tabellen, sqlite `micro_trader.db`)

```text
trades, ki_decisions, depot_snapshot, markt_daten, tenants, tenant_memberships,
workspaces, depots, etf_depots, spec_depots, trading_mode_transitions,
paper_portfolios, paper_positions, provider_connections, secret_store,
paper_orders, tenant_risk_limits, tenant_rules, tenant_approvals, live_requests
```

| Tabelle | Status | Bemerkung |
|---|---|---|
| `markt_daten` | **LEER** | P0-Blocker Phase 2 (Persistenz fehlt) |
| `live_requests` | vorhanden | Struktur für späteres Live-Gate |
| `tenants` | 1 Tenant (id=1) | Production: 1 Tenant |
| `provider_connections` | vorhanden | Provider-Rotation (v2.51 repariert) |

## 4. Trading-Engine

| Komponente | Datei | Status |
|---|---|---|
| Batch-Trader | `batch_trader.py` | aktiv, scannt `depot_*.json` (Glob) |
| Engine | `engine.py` | vorhanden |
| KI-Entscheidungen | `ki_decisions.py` | nutzt `ki_provider.call_ki` (Rotation) |
| Lernsystem | `ki_learning.py` / `learned_rules.py` | aktiv, Regel-Decay |
| Risk | `risk_profile.py` / `enforce_risk_limits` | RISK_STUFEN 0–95 |
| Scheduler | `micro_trader_scheduler.py` | Mo–Fr, boersen-gesteuert (±15min) |

## 5. Security

| Bereich | Status | Evidence |
|---|---|---|
| Benutzer | 3 (admin, __diag__, goldi5) | `security_users.json` |
| Rollen | 41 feine Permissions, deny-by-default | `security.py` |
| MFA | für Admin konfiguriert | Security-Sektionen |
| Tenant-Isolation | tenant-keyed Cache + tid-Guard | verifiziert (Test-Tenant) |
| Audit | `audit/micro_trader_audit_*.json` | vorhanden |

## 6. News (Bestand)

- 5 RSS-Feeds (Bloomberg, DowJones, Yahoo, NYT, Investopedia) — siehe `LIVE-NEWS-INVENTORY.md`.
- `news_cache.json` befüllt (headlines).
- `news_evaluator.py` veraltet (alter API-Key) — P0-Blocker Phase 5.

## 7. Laufende Prozesse (zum Zeitpunkt Phase 0)

- Dashboard: `pythonw.exe dashboard.py 5300` (PID 9616) + `python.exe dashboard.py 5300` (PID 996).
  > **HINWEIS:** Zwei Instanzen auf Port 5300 detektiert. Single-Instance-Guard
  > (Listener-Check, v2.57.1) sollte doppeltes Starten verhindern — hier vermutlich
  > Hintergrund-Start aus älterer Session. Nach Phase 0 bereinigen (Kill + Restart).

## 8. Bekannte offene Punkte (übernommen aus Auftrag Phase 1)

- [ ] `markt_daten` persistieren (P0).
- [ ] CSRF vollständig verdrahten.
- [ ] MFA für alle Admins aktivieren.
- [ ] Zweiter Tenant-Isolationstest.
- [ ] Risk-70-Budgetlogik prüfen (doppelte Budgetfilterung = Designschwäche).
- [ ] Singleton-Guard erneut testen.
- [ ] Audit-/Log-Stabilität, Backup/Restore, Restart-Tests.

## 9. Tests

- Security-Suite `test_server_security.py` muss grün bleiben (Auftrag §Tests).
- 273 bestehende Tests (HANDOFF-V3, v2.43) — Wiederholung in Phase 1 empfohlen.

## 10. Fazit

Paper-System ist funktionsfähig und PAPER_ONLY hart gesperrt. Live-Übergang blockiert
aktuell durch: leere `markt_daten`, veralteten News-Evaluator, fehlendes Ticker-Mapping,
fehlenden Kill-Switch. Diese werden in Phase 1–11 adressiert.
