# Rollen- & Berechtigungsmodell (PHASE 2)

**Version:** v2.27.0 · **Stand:** 2026-08-08 · **Status:** Implementiert + getestet

## Ziel
Tenant-bezogene Rollen: Ein User kann in Tenant A **Admin** sein, in Tenant B
nur **User**. Berechtigungen wirken im Kontext des aktiven Mandanten (OWASP:
Tenant-ID nie aus Client-Input, immer aus Session abgeleitet).

## Architektur

### 1. Rollen (global + effektiv)
```python
ROLES = ["visitor", "user", "analyst", "operator", "admin", "superadmin"]
```
- **Globale Rolle** (`security_users.json` → `role`): Fallback, wenn keine
  Membership im aktiven Tenant existiert.
- **Effektive Rolle**: `effective_role(user, tenant_id)` liefert die
  Membership-Rolle im Tenant (gewichtet) ODER die globale Rolle (Fallback).

### 2. Permission-Maps
- `ROLE_PERMISSIONS` — globale Permissions (Phase 6, Basis).
- `TENANT_ROLE_PERMISSIONS` — **PHASE 2**, erweitert um Tenant-Rechte:
  - `tenant_view` — Mandant einsehen
  - `tenant_manage` — Mandant konfigurieren (Admin)
  - `tenant_trade_control` — Handel pausieren/fortsetzen (Operator)
  - `tenant_members` — Mitglieder verwalten (Admin)
  - `tenant_delete` — Mandant löschen (**nur Superadmin**)

### 3. Prüf-Funktionen (security.py)
| Funktion | Zweck |
|----------|-------|
| `effective_role(user, tid)` | Membership-Rolle > globale Rolle |
| `effective_permissions(user, tid)` | Permissions der effektiven Rolle |
| `has_permission(user, perm, tid)` | Permission-Check im Tenant-Kontext |
| `has_permission_in(role, perm)` | Statischer Check (ohne User) |

### 4. Decorators
- `@require_role("admin")` — prüft **globale** Rolle (systemweite Routen)
- `@require_tenant_role("admin")` — prüft **effektive** Rolle im Tenant
- `@require_permission("tenant_manage")` — prüft Permission im Tenant

### 5. Route-Klassen (ROUTE_ACCESS)
- `ADMIN` — systemweite Admin-Routen (globale Rolle, z.B. `/api/tenants`)
- `TENANT_ADMIN` — tenant-bezogene Admin-Routen (effektive Rolle, z.B. `/api/roles`)

**before_request** erkennt `TENANT_`-Präfix und prüft gegen die effektive Rolle
statt der globalen.

## API

### `GET /api/roles` (TENANT_ADMIN)
Rollenkatalog + Permissions:
```json
{
  "roles": [
    {"role": "admin", "level": "ADMIN",
     "permissions": ["dashboard", "tenant_manage", "tenant_members", ...]},
    ...
  ],
  "all_permissions": ["landingpage", "dashboard", ..., "tenant_delete"]
}
```

### `GET /api/me/permissions` (AUTHENTICATED)
Effektive Permissions im aktiven Tenant:
```json
{
  "username": "admin",
  "tenant_id": 1,
  "effective_role": "superadmin",
  "permissions": ["landingpage", "dashboard", ..., "tenant_delete"]
}
```

### `GET /api/me` (erweitert)
Neu: `"effective_role"` + `"tenant_permissions"`.

## UI
Mein-Konto zeigt: Globale Rolle + (falls abweichend) effektive Rolle im Mandant
als Badge (`im Mandant: <rolle>`).

## Sicherheit (OWASP Multi-Tenant)
- Tenant-ID kommt **nie** aus Client-Header/Params → `resolve_tenant_for_user()`
  aus Session/Membership.
- deny-by-default: Unbekannte Route → `ADMIN` (restriktiv).
- Superadmin hat immer alle Permissions (Explizit-Override).
- Membership-Status `inaktiv` → Rolle wird nicht angewendet.

## Tests
Sektion 7c in `test_server_security.py` (10 Tests):
- Effektive Rolle gewinnt (Membership > global)
- Andere Tenant → globale Rolle
- tenant_manage/tenant_trade_control/tenant_delete
- API: superadmin, Tenant-Admin (200), Operator (403)
- **Gesamt-Suite: 69 OK, 0 FAIL**

## Nächste Schritte (Phase 3+)
- UI: Rollen-Verwaltung pro Tenant (Mitglieder-Rolle ändern im Frontend)
- Audit-Log für Rollenwechsel
- Feingranulare Permissions (z.B. `trade_execute`, `report_export`)
