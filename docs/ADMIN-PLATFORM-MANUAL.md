# Admin-Platform-Manual (§19-Punkt 15)

**Version:** 2.49.0 (2026-08-10) · **Phase:** 15 · **Status:** fertig

## Admin-Bereich (`/admin`)

Der Admin-Bereich hat 8 Tabs (Mandanten-fähig, tenant-scoped):

| Tab | Route | Funktion |
|-----|-------|----------|
| **Übersicht** | `/admin` | Platform-Status, Modi, Freigaben |
| **System** | `/admin/system` | System-Status, Trading-Modi aller Tenants |
| **Benutzer** | `/admin/users` | Benutzerverwaltung (Status, Rollen, MFA) |
| **Sicherheit** | `/admin/security` | Rollen, Permissions, Vier-Augen-Regeln |
| **Logins** | `/admin/logins` | Login-Verlauf, Failed-Attempts, Rate-Limit |
| **Audit** | `/admin/audit` | Audit-Trail (security_audit.jsonl) |
| **Backups** | `/admin/backups` | Backup-Verwaltung |
| **Mandanten** | `/admin/tenant-config` | Risiko + Regeln pro Tenant |

## Tenant-Config (`/admin/tenant-config`)

- **Risiko:** moderate / aggressive → `POST /admin/tenant-config/risk`
- **Regeln:** Ticker-Regeln (BLOCK/ALLOW) → `POST /admin/tenant-config/rule`
- **Freigaben:** Portfolio-Freigabe (PENDING/IN_REVIEW/APPROVED/REJECTED) → `POST /admin/tenant-config/approval`
- **Quell-Tags:** tenant / global / default (via `.src`-CSS-Klassen)

## Live-Anträge (`/api/live-requests`)

Tenant-Admin beantragt LIVE-Modus:
- `POST /api/live-requests` — Antrag erstellen
- `GET /api/live-requests` — Anträge listen
- `POST /api/live-requests/<id>/approve` — Genehmigen
- `POST /api/live-requests/<id>/reject` — Ablehnen

Siehe `LIVE-ANTRAGSPROZESS.md` für Details.

## Provider/Connections (`/api/providers`)

- `GET /api/providers` — Provider-Connections listen
- `POST /api/providers/disable|enable|delete` — Connection verwalten
- `POST /api/providers/status/<id>` — Status setzen
- `POST /api/secrets/rotate` — Secret rotieren

Siehe `PROVIDER-MANAGEMENT.md` + `SECRET-CONNECTION-MANAGEMENT.md`.

## Berechtigungen

Alle Admin-Routen erfordern `ROUTE_ACCESS`-Eintrag:
- `ADMIN` (systemweit) oder `TENANT_ADMIN` (tenant-scoped)
- Kritische Aktionen: `require_recent_mfa` + Vier-Augen (`four_eyes_required`)

## Tests

Alle Admin-Routen in `test_server_security.py` (ROUTE_ACCESS-Sektion) verifiziert.
**Ergebnis:** 313 OK, 0 FAIL (v2.49.0)
