# ROLE-PERMISSION-MATRIX

Stand: v2.40.0 (2026-08-09) · Phase 2 (§7 des Hermes-Arbeitsauftrags) · getestet: 231 OK

## Rollen

| Rolle | Ebene | Bedeutung |
|---|---|---|
| `visitor` | PUBLIC | Nicht eingeloggt / keine Rechte |
| `user` | AUTHENTICATED | Eigenes Profil, eigene Sessions, Dashboard, Portfolio-Lesen |
| `analyst` | ANALYST | + Reports, Analysen, KI-Log, Regeln vorschlagen |
| `operator` | OPERATOR | + Trading-Pause/Resume, Paper-Trading |
| `admin` | ADMIN | + Benutzer/Rollen/Regeln/Provider/Broker/Backups, Live-Antrag/-Review |
| `superadmin` | SUPERADMIN | alle feinen Permissions inkl. Live-Freigabe, Emergency |

## Feine Permissions (§7-Katalog)

Pro Rolle **deny-by-default** — nur was explizit in `ROLE_FINE_PERMISSIONS` steht, ist erlaubt.
Superadmin = alle. Zusätzlich löst `role_has_permission` grobe Katalog-Namen über
`PERMISSION_ALIASES` auf (z. B. `users` → `users.read/create/disable`), damit bestehende
Checks kompatibel bleiben.

| Permission | user | analyst | operator | admin | superadmin |
|---|---|---|---|---|---|
| profile.read / profile.edit | ✅ | ✅ | ✅ | ✅ | ✅ |
| sessions.read / sessions.revoke | ✅ | ✅ | ✅ | ✅ | ✅ |
| dashboard.read | ✅ | ✅ | ✅ | ✅ | ✅ |
| portfolio.read | ✅ | ✅ | ✅ | ✅ | ✅ |
| portfolio.edit | — | — | — | ✅ | ✅ |
| reports.read | — | ✅ | ✅ | ✅ | ✅ |
| analysis.read | — | ✅ | ✅ | ✅ | ✅ |
| strategy.read | — | ✅ | ✅ | ✅ | ✅ |
| strategy.edit | — | — | — | ✅ | ✅ |
| rules.read / rules.propose | — | ✅ | ✅ | ✅ | ✅ |
| rules.review / rules.approve / rules.rollback | — | — | — | ✅ | ✅ |
| trading.pause / trading.resume | — | — | ✅ | ✅ | ✅ |
| paper.trade | — | — | ✅ | ✅ | ✅ |
| live.request / live.review | — | — | — | ✅ | ✅ |
| live.approve / live.revoke | — | — | — | — | ✅ |
| provider.read / create / test / rotate / disable | — | — | — | ✅ | ✅ |
| broker.read / connect / disconnect | — | — | — | ✅ | ✅ |
| order.intent.create / order.intent.approve | — | — | — | ✅ | ✅ |
| order.execute | — | — | — | — | ✅ |
| users.read / users.create / users.disable | — | — | — | ✅ | ✅ |
| roles.manage | — | — | — | ✅ | ✅ |
| audit.read | — | — | — | ✅ | ✅ |
| settings.read / settings.edit | — | — | — | ✅ | ✅ |
| backup.restore | — | — | — | ✅ | ✅ |

## Alias-Auflösung (`PERMISSION_ALIASES`)

| Grober Katalog-Name | Implizierte feine Permissions |
|---|---|
| `dashboard` | dashboard.read, portfolio.read |
| `reports` | reports.read |
| `analysis` | analysis.read |
| `rules` | rules.read, rules.propose, rules.review, rules.approve, rules.rollback |
| `users` | users.read, users.create, users.disable |
| `settings` | settings.read, settings.edit |
| `audit` | audit.read |
| `backups` | backup.restore |
| `pause_trading` / `resume_trading` | trading.pause / trading.resume |
| `tenant_manage` | users.manage, roles.manage |
| `tenant_members` | users.read |

## Vorgaben-Umsetzung (§7)

| Vorgabe | Umsetzung |
|---|---|
| Rechte immer serverseitig prüfen | `before_request` → `route_class()` (ROUTE_ACCESS) + Decorators `require_role` / `require_tenant_role` / `require_permission` |
| Deny-by-default | `ROLE_FINE_PERMISSIONS` (leere Liste = nichts); unbekannte Rollen/Permissions → False |
| Kein Recht aus Frontend ableiten | Frontend-Ausblendung ist keine Berechtigung; jede Route prüft serverseitig |
| Tenant-Grenzen bei jeder Ressource | `effective_role` (Membership gewinnt vor globaler Rolle) + `set_current_tenant` aus Session, nie aus Client-Input |
| Kein Benutzer darf sich selbst privilegieren | `set_role`: Selbst-Promote (höhere Rolle auf sich selbst) → abgelehnt + Audit `role_change_denied` |
| Antragsteller darf kritische Freigaben nicht selbst genehmigen | `four_eyes_required` (Phase 13); `live.approve` nur superadmin |
| Superadmin-Schutz | superadmin-Rolle nur durch superadmin vergeben/entzogen (auch Downgrade) |

## API

- `GET /api/roles` — Rollenkatalog + Permissions (requires `roles.manage`, ADMIN-Ebene, MFA)
- `GET /api/me/permissions` — effektive Rolle + Permissions im aktuellen Tenant (eingeloggt)
- `GET /api/users` — Benutzerliste (requires `users.read` via ADMIN, MFA)

## Testabdeckung (Sektion 7o, v2.40.0)

- 35 Permissions-Checks Rolle × Permission (inkl. Negativfälle: visitor/user/analyst ohne kritische Rechte)
- Deny-by-default für unbekannte Rollen
- Selbst-Privilegierung blockiert (Rolle unverändert, Audit-Eintrag)
- Selbst-Downgrade erlaubt
- superadmin-Vergabe/-Entzug nur durch superadmin
- `/api/roles` serverseitig gesperrt für operator (403)
- `effective_permissions` enthält feine + grobe Permissions (Alias sichtbar)
