# TENANT-DATA-MODEL.md

> **Datenmodell für Benutzer und Tenants** · Micro-Trader · v2.26.0 · 2026-08-08
> Phase 1 des Mandanten-Ausbauauftrags.

---

## 1. Grundbegriffe

| Begriff | Bedeutung |
|---------|-----------|
| **User** | Natürliche Person mit Login, Rollen, MFA (`security_users.json`). |
| **Tenant** | Isolierter Arbeitsbereich (persönlicher Account, Familie, Firma, Team). Eigene Benutzer, Portfolios, Regeln, Verbindungen. |
| **Workspace** | Optionaler Unterbereich eines Tenants (eigene Strategie, eigenes Paper-Konto, eigene Verbindungen). |

**Zielbeziehung:**
```
Tenant
 ├── Users (tenant_memberships)
 ├── Workspaces
 ├── Portfolios (geplant Phase 3+)
 ├── Strategies (geplant)
 ├── Provider/Broker Connections (geplant Phase 5-6)
 ├── Rule Sets (geplant)
 └── Audit Events (geplant Phase 9)
```

---

## 2. Implementierte Tabellen (SQLite `micro_trader.db`)

### 2.1 `tenants`

| Spalte | Typ | Default | Zweck |
|--------|-----|---------|-------|
| `id` | INTEGER PK | auto | Tenant-ID |
| `tenant_key` | TEXT UNIQUE | – | Schlüssel (z.B. `default`, `testfirma`) — 2-32 Zeichen a-z0-9_- |
| `name` | TEXT | – | Anzeigename |
| `status` | TEXT | `aktiv` | aktiv/inaktiv |
| `plan_or_type` | TEXT | `personal` | personal/firma/team… |
| `default_trading_mode` | TEXT | `SHADOW` | SHADOW/PAPER (Live erst Phase 3-4) |
| `risk_policy_id` | TEXT | `default` | Risikoprofil-Referenz |
| `created_at` / `updated_at` | TEXT | now | Zeitstempel |

### 2.2 `tenant_memberships`

| Spalte | Typ | Zweck |
|--------|-----|-------|
| `id` | INTEGER PK | – |
| `tenant_id` | INTEGER NOT NULL | FK → tenants |
| `user_id` | TEXT NOT NULL | FK → security_users (username) |
| `role` | TEXT | Rolle IM Tenant (user/analyst/operator/admin…) |
| `status` | TEXT | aktiv/inaktiv |
| `created_at` | TEXT | – |
| `UNIQUE(tenant_id, user_id)` | – | Keine Doppel-Memberships |

### 2.3 `workspaces`

| Spalte | Typ | Zweck |
|--------|-----|-------|
| `id` | INTEGER PK | – |
| `tenant_id` | INTEGER NOT NULL | FK → tenants |
| `workspace_key` | TEXT NOT NULL | Schlüssel im Tenant |
| `name` | TEXT | Anzeigename |
| `trading_mode` | TEXT | SHADOW/PAPER (Live später) |
| `status` | TEXT | aktiv |
| `created_at` | TEXT | – |
| `UNIQUE(tenant_id, workspace_key)` | – | Eindeutig pro Tenant |

### 2.4 Bestandstabellen erweitert

| Tabelle | Neue Spalten | Default |
|---------|--------------|---------|
| `trades` | `tenant_id`, `user_id` | 1 (= Default-Tenant) |
| `ki_decisions` | `tenant_id`, `user_id` | 1 |
| `depot_snapshot` | `tenant_id`, `user_id` | 1 |
| `markt_daten` | `tenant_id` | 1 |

Migration idempotent in `db.py::_migrate_schema` (ALTER TABLE nur wenn Spalte fehlt).

---

## 3. Tenant-Kontext (Sicherheit)

**Regel (OWASP Multi-Tenant Cheat Sheet):** Der Tenant wird **IMMER aus der
authentifizierten Session abgeleitet** — niemals aus Client-Headern/-Parametern.

```python
# security.py — PHASE 1
from contextvars import ContextVar
_current_tenant = ContextVar("current_tenant", default=None)

def set_current_tenant(tenant_id): ...   # pro Request gesetzt
def get_current_tenant(): ...            # aktueller Kontext (thread-lokal)

def resolve_tenant_for_user(user):
    """tenant_id aus tenant_memberships ableiten (Fallback: Default-Tenant 1)."""
```

**Ablauf:**
1. `before_request` (dashboard.py) → Auth-Check
2. Bei erfolgreicher Auth: `sec.set_current_tenant(sec.resolve_tenant_for_user(u))`
3. Jede Route/Query liest `sec.get_current_tenant()` für Filter

**Verboten:** `X-Tenant-ID`-Header oder `?tenant_id=`-Parameter vertrauen
(Tenant-Context-Injection).

---

## 4. API-Routen (Phase 1)

| Route | Methode | Zugriff | Funktion |
|-------|---------|---------|----------|
| `/api/tenants` | GET | ADMIN | Tenant-Liste |
| `/api/tenants/create` | POST | ADMIN | Tenant anlegen (Validierung tenant_key) |
| `/api/tenants/<id>/members` | GET | ADMIN | Mitglieder + Workspaces eines Tenants |
| `/api/tenants/<id>/members` | POST | ADMIN | User einem Tenant zuordnen |
| `/api/me` | GET | AUTHENTICATED | Eigenes Profil + `tenants` (current_tenant + memberships) |

Alle Admin-Routen auditen (`tenant_create`, `tenant_membership_add`).

---

## 5. db.py Helper (MTDB)

```python
tenant_ensure_default()          # Default-Tenant anlegen, gibt id (1)
tenant_create(key, name, ...)    # → (id, fehler)
tenant_list() / tenant_get(id)
tenant_membership_add(tid, user, role)
tenant_memberships_for_user(user)
tenant_membership_role(tid, user)
tenant_user_ids(tid)
workspace_create(tid, key, name, mode)
workspace_list(tid)
```

---

## 6. Testabdeckung (55 Tests, davon 10 Mandanten)

- Default-Tenant existiert (id=1, key=default)
- Tenant anlegen + Duplikat-409 + key-Validierung-400
- Membership hinzufügen + sichtbar
- Workspace anlegen
- API: ohne Auth 401, als admin 200, Nicht-Admin 403
- `/api/me` liefert tenant-Kontext

---

## 7. Nächste Schritte

- Phase 2: Rollen-/Berechtigungsmodell (tenant_bezogene Rollen aus memberships)
- Phase 3: Trading-Modi-Zustandsmaschine (default_trading_mode je Tenant)
- Phase 4: Shadow→Paper-Freigabe je Tenant
- Phase 5: Provider-Connections mit tenant_id
- Daten-Scoping: depot_*.json nach tenant_id filtern (noch global!)

**Harte Grenze:** PAPER_ONLY — kein Live-Code, keine echten Orders.
