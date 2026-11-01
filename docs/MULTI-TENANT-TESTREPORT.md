# Multi-Tenant-Testreport (§19-Punkt 17)

**Version:** 2.49.0 (2026-08-10) · **Phase:** 17 · **Status:** fertig

## Zweiter Production-Tenant

Die Plattform unterstützt mehrere Tenants (Mandanten). Jeder Tenant hat:
- Isolierte Depot-Dateien (`_tenant_scoped_depot_files`)
- Isolierte Portfolio-Daten (`/data` cache tenant-keyed)
- Isolierte Regeln/Risiko-Limits (`tenant_rules`, `tenant_risk_limits`)
- Tenant-scoped Live-Anträge (`live_requests.tenant_id`)

## Smoke-Test (ad-hoc Verifikation)

**Test-Tenant T2:** Isolate Daten von T1 (Production-Tenant)

| Check | Ergebnis |
|-------|----------|
| T2 hat eigene Depot-Dateien | ✅ |
| T2 sieht nicht T1-Daten (`/data` cache) | ✅ |
| T2 kann nur eigene tid verwalten (tid-Guard) | ✅ |
| T2 Live-Antrag isoliert von T1 | ✅ |
| T2 Risk-Limits separat | ✅ |

## Tenant-Isolation (verify)

- `security.py`: `require_tenant_role` prüft effektive Rolle + tid-Guard
- `db.py`: `_tenant_scoped_*`-Funktionen filtern nach `tenant_id`
- `/data`: Cache tenant-keyed (`_cache_tid`)
- `live_requests`: `tenant_id` in allen Queries (tenant-scoped)

## Tests

`test_server_security.py` Sektion 7p (Tenant-Isolation):
- Non-superadmin sieht nur eigenen Tenant
- Cross-Tenant-Zugriff blockiert (403)
- Tenant anlegen nur superadmin
- Depot-Dateien tenant-scoped

**Ergebnis:** 313 OK, 0 FAIL (v2.49.0)

## Limitation

Zweiter Production-Tenant ist in Tests validiert (T2), aber nicht als separater
Production-Account (mit eigenem Login) eingerichtet. Das ist ein Operations-Schritt
(neuer Tenant + User + MFA), nicht Code.

## Verwandte Dokumente

- `TENANT-ISOLATION-VERIFICATION.md` (§17) — vollständige Isolation-Analyse
- `USER-AND-TENANT-INVENTORY.md` — Tenant/Benutzer-Bestand
- `ROLE-PERMISSION-MATRIX.md` — Rollen pro Tenant
