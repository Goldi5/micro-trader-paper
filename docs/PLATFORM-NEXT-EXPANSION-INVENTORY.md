# PLATFORM-NEXT-EXPANSION-INVENTORY.md

> **Phase 0 — Bestandsaufnahme und Verifikation** (Auftrag §23, Stand: 2026-08-09)
> Basis: Handoff-PDF v2.38.0 (151 Tests) — geprüft gegen echten Code; Stand nach Fixes: **v2.38.1, 165 Tests OK**.
> Keine funktionalen Änderungen in dieser Phase.

---

## 1. Geprüfte Dateien

| Datei | Geprüft | Befund |
|---|---|---|
| `version.json` | ✅ | v2.38.1 (nach Bugfix-Release, vorher 2.38.0) |
| `security.py` | ✅ | ~1700 Zeilen; Identity/Tenant/Approval/Broker/Order-Intent |
| `db.py` | ✅ | 66 MTDB-Methoden; 20 Tabellen; Tenant-Scoping vorhanden |
| `dashboard.py` | ✅ | 69 Routen; Auth/ROUTE_ACCESS; bindet nur 127.0.0.1:5300 |
| `batch_trader.py` | ✅ | Risk-/Rule-/Intent-Enforcement integriert (Z368–404); **Risk-70-Filter im Code bereits gefixt** (Z118) |
| `engine.py` | ✅ | Depot-Klasse, bewerte/signal_aktion/ausführen; `Depot.laden()` leer (bekannt) |
| `ki_decisions.py` | ✅ | entscheide_ticker/batch; max_tokens=1024 |
| `ki_learning.py` | ✅ | 39 Funktionen; Regellernen + Konfidenz-Kalibrierung |
| `learned_rules.py` | ✅ | Lebenszyklus, freigabe_pruefen, is_live_allowed, lade_live_regeln |
| `freigabe.py` | ✅ | lade_profil, pre_flight_check, activate |
| `ki_provider.py` | ✅ | Provider-Rotation: zen → zen-nemotron → nous-step → nous-hy3 → openrouter |
| `marktdaten.py` | ✅ | 4-Tier-Fallback (yfinance/Finnhub/TwelveData/AlphaVantage) |
| `etf_trader.py` / `spec_trader.py` | ✅ | 20 ETF- + 49 Spec-Depots (JSON-basiert) |
| `ki_news.py` / `news_monitor.py` / `news_evaluator.py` | ✅ | RSS + Klassifikation |
| `backup.py` | ✅ | before/after/list/restore/rollback |
| `micro_trader_scheduler.py` | ✅ | Cron, run_once, Börsen-Check |
| `test_server_security.py` | ✅ | **165 OK / 0 FAIL** |

## 2. Geprüfte Tabellen (DB `micro_trader.db`, 20 Tabellen)

| Tabelle | Zeilen | Status |
|---|---|---|
| `tenants` | 1 | nur Tenant id=1 (`default`, SHADOW) — **zweiter Tenant fehlt** |
| `tenant_memberships` | 7 | admin (superadmin) + 6 Test-User (`__t1__`, `__flow__`, `__rolle2__`, `__rolle_b__`, `__hermes_v27b__`, `__hv27bb__`) |
| `workspaces` | 0 | leer — Phase 1+ |
| `trades` | 1.783 | Produktionsdaten |
| `ki_decisions` | 922 | Produktionsdaten |
| `depot_snapshot` | 17.533 | Produktionsdaten |
| `markt_daten` | 0 | **leer — wird nicht persistiert** (Handoff §12 bestätigt) |
| `paper_portfolios` / `paper_positions` / `paper_orders` | 0 | Adapter bereit, noch ungenutzt |
| `provider_connections` | 0 | Manager bereit, keine Verbindungen angelegt |
| `secret_store` | 1 | `OPENAI_API_KEY` (Len 10 — Testwert) |
| `tenant_approvals` | 0 | Vier-Augen-Tabelle leer (Freigaben ungenutzt) |
| `tenant_rules` | 0 | Tenant-Regeln leer (nur globale learned_rules.json aktiv) |
| `tenant_risk_limits` | 0 | leer — Defaults aus settings.json |
| `trading_mode_transitions` | 1 | PAPER→SHADOW (2026-08-09) |
| `depots` / `etf_depots` / `spec_depots` | 0 | Register leer (Depots liegen als JSON-Dateien) |

## 3. Vorhandene Funktionen / APIs

### Sicherheit (`security.py`)
- User: `create_user`, `verify_password`, `change_password`, `set_role`, `deactivate_user`, `list_users` (JSON-Datei `security_users.json`)
- MFA: `generate_mfa_secret`, `verify_mfa`, `enable_mfa`, `disable_mfa`, `mfa_provisioning_uri` (TOTP, eigenständig implementiert)
- Sessions: `create_session`, `session_valid`, `touch_session`, `rotate_session`, `revoke_session`, `revoke_all_sessions`, `mfa_recently_verified`
- Login-Rate-Limit: `login_blocked`, `register_login_fail/ok` (Datei `login_rate.json`)
- CSRF: `generate_csrf_token`, `verify_csrf_token`
- Audit: `audit_log`, `read_audit` (JSONL, 1.722 Einträge)
- Rollen: `TENANT_ROLE_PERMISSIONS` (5 Rollen ohne visitor), `ROLE_PERMISSIONS`/`PERMISSIONS` (6 Rollen), `has_permission`, `require_permission`, `require_role`, `require_tenant_role`, `require_recent_mfa`
- Trading-Modus: `get/set_trading_mode`, `trading_mode_history`, `paper_eligibility`, `enter_paper`, `mode_is_valid`, `mode_can_transition`
- Rules: `rule_add/list/set_status`, `enforce_rules` (BLOCK:/MAX_KAUF:/REGEX: + KI-Muster mit Ticker)
- Risk: `risk_set/get/list`, `enforce_risk_limits`
- Approval: `approval_set/get/list`, `enforce_approval` (deny-by-default), `enforce_approval_trade` (unreguliert erlaubt), `four_eyes_required`
- Order-Intent: `create_order_intent` (17 Felder), `validate_order_intent` (18 Checks inkl. Freigabe seit v2.38.1)
- Broker: `BrokerProvider` (Interface), `PaperBrokerAdapter` (place_order/get_account/get_positions/…)

### DB (`db.py`, 66 Methoden)
- Tenant: `tenant_create/list/get`, `tenant_ensure_default`, `tenant_membership_add/role/…`, `tenant_scope_where`
- Workspace: `workspace_create/list`
- Provider: `provider_connection_add/list/test/ensure_columns`
- Paper: `paper_portfolio_create/list`, `paper_order_insert/list`, `paper_position_apply`
- Secrets: `secret_set/get/list_keys`
- Sync: `sync`, `_sync_trades/ki/snapshots`, `match_trades_ki`, `query_*`, `analyse_karten`
- Schema: `_migrate_schema`, `_spalte_existiert`

### API-Routen (`dashboard.py`, 69)
- PUBLIC: `/`, `/landing`, `/api/version`, `/login`
- AUTHENTICATED: `/dashboard`, `/data`, `/depot_json`, `/api/me*`, `/reports/*`
- ANALYST: `/api/analysis`, `/api/db_karten`, `/api/ki_log`, `/api/profile`
- OPERATOR: `/api/pause_trading`, `/api/clear_cache`
- TENANT_ADMIN: `/api/trading_mode*`, `/api/providers*`, `/api/secrets*`, `/api/risk*`, `/api/rules*`, `/api/approval*`, `/api/paper/*`
- ADMIN: `/api/users*`, `/api/tenants*`, `/admin/*`

## 4. Bereits implementierte Features

- ✅ Tenant- und Workspace-Struktur (Tabellen + Scoping-Helfer)
- ✅ Rollen + serverseitige Permission-Prüfung (`has_permission`, ROUTE_ACCESS)
- ✅ MFA (TOTP) + Login-Rate-Limit + CSRF + Session-Rotation
- ✅ Shadow/Paper-Zustandsmodell + Übergangs-Log (`trading_mode_transitions`)
- ✅ Secret-Store (tenant-scoped, nur Maskierung geplant)
- ✅ Provider-Connections (CRUD + Test, tabelle bereit)
- ✅ Paper-Order-Buch + PaperPortfolio (Adapter)
- ✅ Order-Intent (17 Felder) + 18-Check-Validierung **inkl. Vier-Augen-Freigabe (v2.38.1)**
- ✅ Vier-Augen-Freigaben (`four_eyes_required`, approval_set/get/list)
- ✅ Admin-Bereich (users/tenants/system/rules/security/logins/audit/settings/backups/tenant-config)
- ✅ Audit-Logging (JSONL)
- ✅ BLOCK-Regel-Ticker-Fix + KI-Regeln wirksam (v2.38.1)
- ✅ Risk-70-Budgetfilter bereits gefixt (Z118, `bargeld * position_size * 1.5`)

## 5. Fehlende Features (Lücken zum Auftrag)

| # | Lücke | Phase |
|---|---|---|
| 1 | Benutzer-Lebenszyklus: Status `INVITED/MFA_REQUIRED/RESTRICTED/SUSPENDED/DELETED` fehlt (nur `active` bool) | 1 |
| 2 | Sessions: kein Ablauf/GC (422 Sessions für admin), kein Gerät/User-Agent, Widerruf-UI fehlt | 1 |
| 3 | MFA-Pflicht für Admin/Superadmin (aktuell deaktiviert), Recovery-Codes, Verlustprozess | 1 |
| 4 | Feingranulare Permissions (38 laut Auftrag vs. ~30 heute, teils grob) | 2 |
| 5 | Rollen-Tests je Rolle × kritische Aktion (nur Stichproben heute) | 2 |
| 6 | Vollständige Modus-Zustandsmaschine (LIVE_REQUESTED/…/REVOKED fehlen) | 3 |
| 7 | Shadow→Paper-Freigabe mit Voraussetzungen (Mindestanzahl, Audit-Trail) | 4 |
| 8 | Paper→Live-Antragsprozess (Antragsobjekt, Auto-Ablehnung) | 5 |
| 9 | Provider-Datenmodell: status `UNCONFIGURED…EXPIRED`, Fallback tenant-bewusst | 6 |
| 10 | Datenprovider-Abstraktion (`MarketSnapshot`, Interfaces) — heute direkte yfinance-Aufrufe | 7 |
| 11 | Broker-Connector-Architektur: nur PaperBrokerAdapter, kein Simulator/Sandbox-Adapter | 8 |
| 12 | Freigabe-Objekte (approval_id/expires/revoked) teilweise; `expires_at` fehlt | 9 |
| 13 | Admin: Live-Freigabe-Review, Provider-Test/Rotation-UI fehlt | 10 |
| 14 | Audit: Moduswechsel/Provideränderung/Rotation z.T. fehlt; **Achtung: keine Secrets loggen** | 11 |
| 15 | Zweiter Isolationstest-Tenant fehlt (nur Test-User im Tenant 1) | 12 |
| 16 | Tailscale-Funnel nur konzeptionell (Tailscale gestoppt, kein Reverse-Proxy aktiv) | — |

## 6. Risiken

1. **422 Sessions** für `admin` unbegrenzt gespeichert (kein Expiry) → Session-Datei wächst, Sicherheitsfläche.
2. **MFA deaktiviert** für superadmin (mfa_enabled=False, kein mfa_secret) → Admin-Konto nur Passwort-geschützt.
3. **Test-User-Müll** (6 `__…__`-Memberships) im Produktions-Tenant 1 → Isolationstests verschmutzen Produktionsdaten.
4. `tenant_approvals`, `tenant_rules`, `tenant_risk_limits`, `provider_connections` leer → Vier-Augen-/Regel-/Provider-Features ungenutzt im Produktivbetrieb (Paper-Käufe laufen trotzdem).
5. `markt_daten` leer → Marktdaten werden ad-hoc gescanned, nicht persistiert (Handoff §12 bestätigt).
6. Audit-JSONL-Datei: kein Rollover/Retention, 1.722 Einträge.
7. `login_rate.json` enthält Test-IPs (203.0.113.7/198.51.100.23) + `__v23__` mit 5 Fehlversuchen (blocked_until abgelaufen) — Reste aus Tests.
8. `Depot.laden()` in engine.py leer — Workaround in batch_trader (bekannt, Handoff §19.1).
9. Risk-70-Fix im Code (Z118) ist **nicht durch einen expliziten Test abgesichert** und der Handoff behauptet noch „nicht gefixt" → Doku-Update + Regressionstest nötig.
10. `_budget_debug.txt`-TEMP-DEBUG (batch_trader Z120–130) schreibt bei Risk 80/90 Log-Datei → aufräumen.

## 7. Abweichungen zur Dokumentation

| Handoff-Behauptung | Code-Befund |
|---|---|
| „151 erfolgreiche Tests" (v2.38.0) | 165 Tests OK (v2.38.1, nach +14 Bugfix-Tests) |
| „Risk 70 NICHT gefixt (Budget-Filter Z117 zu eng)" | **Gefixt** seit v2.20.2: Z118 `kauf_budget = bargeld * position_size * 1.5`; Handoff-§6.1 veraltet |
| „enforce_rules BLOCK-Bug (Z291)" | **Behoben** in v2.38.1 (ticker-spezifisches Matching, Sektion 7m) |
| „4 Tabellen" (§12) | **20 Tabellen** (Multi-Tenant-Ausbau seit v2.35) |
| „Multi-Tenant-Isolation mit Test-Tenant verifiziert" | Tabelle `tenants` enthält nur 1 Tenant; Isolation nur über Test-User im selben Tenant getestet |
| „48 globale Regeln unbestätigt + ohne Prefix → Enforcement greift nicht" | Behoben in v2.38.1: freigegebene (18) wirken; meta_conf_cap/Kategorie-Regeln steuern KI-Prompt statt hart zu blocken |

## 8. Empfohlene Reihenfolge (aus Auftrag §19 übernommen, mit Befund-Abgleich)

```text
1.  Bestandsaufnahme (diese Datei) ✅
2.  Bekannte Fehler/Root-Causes: Risk-70-Regressionstest + _budget_debug aufräumen; Handoff-Doku korrigieren
3.  Benutzerverwaltung (Lebenszyklus, Sessions-GC, MFA-Pflicht)
4.  Rollen + Berechtigungen (38 Permissions, Rollen-Matrix-Tests)
5.  Tenant-Isolation (2. Test-Tenant, Test-User-Müll entfernen)
6.  Shadow/Paper/Live-Zustandsmaschine (8 Modi)
7.  Shadow→Paper-Freigabe
8.  Provider-Datenmodell (Status, Fallback tenant-bewusst)
9.  Secret-/Connection-Manager (Maskierung, Rotation, Audit)
10. Datenprovider-Abstraktion (MarketSnapshot)
11. Paper-/Simulator-Broker (Simulator-Adapter)
12. Order-Intent- + Risk-Integration (vollständig)
13. Vier-Augen-Freigabe (expires_at, Revoke)
14. Live-Antragsprozess
15. Admin-Oberfläche (Freigaben/Provider/Rotation)
16. Audit-Erweiterung (Moduswechsel etc., JSONL-Rollover)
17. Zweiter Tenant-Test (echter 2. Tenant + Leak-Tests)
18. Sicherheits-/Regressionstests
19. Sandbox-Brokerintegration
20. Dokumentation (Handoff-Abweichungen korrigieren)
```

**Nächster Schritt:** Phase 2 (bekannte Fehler + Root-Causes) gemäß Auftrag — beginnt mit Risk-70-Regressionstest und `_budget_debug.txt`-Bereinigung.
