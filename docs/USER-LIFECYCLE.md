# User-Lifecycle (§19-Punkt 6, erweitert)

**Version:** 2.49.0 (2026-08-10) · **Phase:** User-Verwaltung · **Status:** fertig

## Benutzer-Status

| Status | Bedeutung | Übergang |
|--------|-----------|----------|
| `INVITED` | Eingeladen, noch nicht aktiv | → ACTIVE (nach erstem Login) |
| `ACTIVE` | Aktiv, kann handeln | → SUSPENDED / DISABLED |
| `MFA_REQUIRED` | MFA-Pflicht (admin/superadmin) | → ACTIVE (nach MFA-Setup) |
| `RESTRICTED` | Eingeschränkt (z.B. nur Lesen) | → ACTIVE / SUSPENDED |
| `SUSPENDED` | Gesperrt (temporär) | → ACTIVE / DISABLED |
| `DISABLED` | Deaktiviert (dauerhaft) | → ACTIVE (durch Admin) |
| `DELETED` | Gelöscht (soft-delete) | — |

## Lifecycle-Events

- **Passwort-Änderung** → widerruft ALLE Sessions (Akzeptanzkriterium §6)
- **MFA-Änderung** → invalidiert Sessions + Audit (mfa_enable/mfa_disable)
- **MFA-Pflicht** → kritische Routen erfordern MFA (Redirect /setup_mfa)
- **Recovery-Codes** → 8 einmalige Codes bei MFA-Aktivierung
- **Self-Privilegierung** → set_role verweigert Promote auf sich selbst (Audit role_change_denied)
- **Superadmin-Schutz** → superadmin-Rolle nur durch superadmin vergeben/entzogen

## Redaction

`get_user` / `list_users` liefern nie:
- `password_hash`
- `mfa_secret`
- `recovery_codes`

## API

| Route | Berechtigung | Beschreibung |
|-------|--------------|--------------|
| `POST /api/users` | ADMIN | Benutzer anlegen (email, display_name, created_by) |
| `POST /api/users/<id>/deactivate` | ADMIN | Deaktivieren (sec.deactivate_user) |
| `POST /api/users/<id>/role` | ADMIN + require_recent_mfa | Rolle ändern |
| `POST /api/users/<id>/mfa-setup` | USER (self) | MFA aktivieren |

## Tests

`test_server_security.py` Sektion 7n (Benutzerverwaltung): 18 Tests.
**Ergebnis:** 313 OK, 0 FAIL (v2.49.0)
