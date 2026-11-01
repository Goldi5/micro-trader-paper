# TENANT-ISOLATION-VERIFICATION

Stand: v2.41.0 (2026-08-09) · Phase 3 (§2.3 / §17 / §18 des Hermes-Arbeitsauftrags) · getestet: 242 OK

## Auftragsforderung (§2.3)

> Die folgenden Daten dürfen nicht global zwischen Tenants oder Benutzern geteilt werden:
> Depots, Paper-Orders, Provider-Keys, Broker-Verbindungen, Regelstände, Strategien,
> Risiko-Limits, Auditdaten, Portfoliozustände, Sessions. Jeder Zugriff muss
> tenant-scoped und, wenn erforderlich, user-/workspace-scoped erfolgen.

## Verifikationsmatrix

| Datenkategorie | Mechanismus | Status |
|---|---|---|
| Depot-Dateien (Aktien/ETF/Spec) | `_tenant_scoped_depot_files(tid)` filtert nach `tenant_id`-Feld im JSON (Default 1); **neu:** alle Depot-Speicher schreiben `tenant_id` | ✅ v2.41.0 |
| `/data`-Aggregat (Portfoliozustand) | Cache ist **tenant-keyed** (`_cache_tid`) — kein Cross-Tenant-Cache-Leak mehr | ✅ v2.41.0 |
| Paper-Orders | `paper_orders`-Tabelle: `WHERE tenant_id = ?` | ✅ (Phase 4-Architektur) |
| Provider-Keys | `secret_store`-Tabelle: `WHERE tenant_id = ? AND secret_key = ?` | ✅ |
| Broker-Verbindungen | `provider_connections`-Tabelle: `WHERE tenant_id = ?` | ✅ |
| Regelstände | `tenant_rules`-Tabelle: `WHERE tenant_id = ?` | ✅ |
| Risiko-Limits | `tenant_risk_limits`-Tabelle: `WHERE tenant_id = ?` | ✅ |
| Auditdaten | Audit-Log mit `tenant_id`-Kontext in Aktionen; JSONL | ✅ |
| Sessions | Session pro User, keine Tenant-Fremdzuordnung möglich | ✅ |
| Tenant-API-Zugriff | `require_tenant_role` (effektive Rolle) + `tid`-Guard | ✅ v2.41.0 |

## In Phase 3 behobene Lücken

1. **`/data`-Cache war tenant-blind** — ein Request von Tenant B konnte im 60s-Fenster
   die gecachten Portfolio-Daten von Tenant A erhalten. Fix: `_cache_tid` wird beim
   Cache-Write gesetzt und beim Cache-Hit abgeglichen; `clear_cache`/Invalidierung
   räumen das Feld mit ab.
2. **Tenant-Routen nutzten die globale Rolle** (`require_role("admin")`) statt der
   effektiven Membership-Rolle. Fix: `require_tenant_role("admin")` + ROUTE_ACCESS
   `TENANT_ADMIN` (before_request setzt dabei den Tenant-Kontext aus der Session).
3. **`tid` aus der URL wurde blind vertraut** — ein Admin konnte
   `/api/tenants/<fremde_tid>/members` abrufen. Fix: `tid`-Guard — non-superadmin
   darf nur seinen eigenen Tenant lesen/verwalten (403 sonst).
4. **Depot-Speicher ohne `tenant_id`** — ein Tenant-2-Depot wäre beim Lesen auf
   Tenant 1 zurückgefallen. Fix: `engine.py`, `spec_trader.py`, `etf_trader.py`,
   `trader.py`, `paper_trader.py` schreiben `tenant_id` (Default 1).
5. **Tenant-Anlage ungeschützt** — nur superadmin darf neue Tenants anlegen (403).

## Testabdeckung (Sektion 7p, v2.41.0)

- Depot-`speichern()` schreibt `tenant_id`; Default 1 bleibt für Alt-Depots
- `_tenant_scoped_depot_files`: Tenant 7 sieht nur sein Depot, Tenant 1 sieht es nicht
- `/data`-Cache: Tenant 7 bekommt nicht den Tenant-1-Cache
- Fremder Tenant → 403, eigener Tenant → 200 (Login als Tenant-1-Admin)
- Tenant-Liste non-superadmin: nur eigener Tenant
- Tenant anlegen non-superadmin → 403

## Bekannte Restrisiken

- `resolve_tenant_for_user` nutzt die **erste** Membership eines Users (kein
  Tenant-Switcher im UI) — für den Ein-Tenant-Produktivbetrieb unkritisch; ein
  Tenant-Umschalter ist Teil der Admin-UI-Phase.
- Depots werden weiterhin als JSON-Dateien geführt (nicht in der DB) — die
  `tenant_id`-Markierung verhindert Fehlzuordnungen; Migration in die DB bleibt
  optionale spätere Phase.
