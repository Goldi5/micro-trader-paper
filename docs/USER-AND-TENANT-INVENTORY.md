# USER-AND-TENANT-INVENTORY.md

> **Phase 0 — Bestandsaufnahme** (2026-08-09, Stand v2.38.1)
> Benutzer, Rollen, Tenants, Sessions, MFA — geprüft gegen `security_users.json`, `security.py`, `db.py` (Tabelle `tenants`/`tenant_memberships`).

---

## 1. Benutzer (`security_users.json`)

| Feld | Wert |
|---|---|
| Username | `admin` |
| Rolle | `superadmin` |
| Aktiv | ✅ `active: true` |
| E-Mail | leer |
| MFA | ❌ `mfa_enabled: false`, kein `mfa_secret` |
| Letzter Login | `null` (nie als Login-Ereignis erfasst) |
| Sessions | **422** (alle lokal, letzte Aktivität 2026-08-09 09:55 UTC) |
| `last_security_action` | `null` |

**Befunde:**
- Nur **1 echter Benutzer** existiert (admin/superadmin).
- **422 Sessions** — kein Ablauf/GC; `session_valid` prüft vermutlich nur Existenz, nicht Expiry → Session-Datei wächst unbegrenzt.
- **MFA deaktiviert** für den Superadmin → Widerspruch zu Auftrag §6 („MFA verpflichtend für Admin/Superadmin").
- Kein `last_login_at`, kein `last_failed_login_at`, kein `mfa_verified_at`, kein `disabled_by/at` (Feld-Set unvollständig ggü. Auftrag §6).

## 2. Rollenmodell (`security.py`)

### Rollen (2 Sätze)
- `ROLE_PERMISSIONS` / `PERMISSIONS` (6 Rollen): visitor, user, analyst, operator, admin, superadmin
- `TENANT_ROLE_PERMISSIONS` (5 Rollen, **ohne visitor**): user, analyst, operator, admin, superadmin

### Berechtigungen (aktuelle Permission-Namen)
`landingpage, dashboard, own_data, tenant_view, reports, analysis, ki_log_view, systemstatus, pause_trading, resume_trading, tenant_trade_control, users, settings, rules, audit, backups, tenant_manage, tenant_members, recovery, security_config, mfa_emergency, tenant_delete`

### Lücken ggü. Auftrag §7 (38 geforderte Permissions)
| Gefordert | Vorhanden? |
|---|---|
| profile.read / profile.edit | teilweise (`/api/me*`) |
| sessions.read / sessions.revoke | ❌ fehlt granular |
| portfolio.read / portfolio.edit | ❌ fehlt (nur own_data) |
| rules.propose / rules.review / rules.approve / rules.rollback | ❌ nur pauschal `rules` |
| trading.pause / trading.resume | ✅ vorhanden |
| paper.trade | ❌ fehlt |
| live.request / live.review / live.approve / live.revoke | ❌ fehlt |
| provider.read/create/test/rotate/disable | ❌ nur pauschal `providers` |
| broker.read/connect/disconnect | ❌ fehlt |
| order.intent.create/approve/execute | ❌ fehlt (nur Code-Ebene) |
| users.read/create/disable | ✅ (pauschal `users`) |
| roles.manage | ❌ fehlt |
| audit.read | ✅ |
| settings.read/edit | ✅ (pauschal) |
| backup.restore | ❌ fehlt (nur `backups`) |

## 3. Tenants (DB-Tabelle `tenants`)

| id | key | name | status | plan | default_mode |
|---|---|---|---|---|---|
| 1 | `default` | Micro-Trader Hauptmandant | aktiv | personal | SHADOW |

**Nur 1 Tenant** — der geforderte zweite Isolationstest-Tenant (Auftrag §17) fehlt in der Tabelle.

### Mitgliedschaften (`tenant_memberships`, 7 Zeilen)
| id | tenant | user_id | role | status |
|---|---|---|---|---|
| 1 | 1 | `admin` | superadmin | aktiv |
| 3 | 1 | `__t1__` | user | aktiv |
| 4 | 1 | `__flow__` | admin | aktiv |
| 13 | 1 | `__rolle2__` | operator | aktiv |
| 17 | 1 | `__rolle_b__` | operator | aktiv |
| 27 | 1 | `__hermes_v27b__` | operator | aktiv |
| 31 | 1 | `__hv27bb__` | operator | aktiv |

**Befund:** 6 Test-User (`__…__`) aus früheren Tests verschmutzen den Produktions-Tenant → vor Isolationstests bereinigen (Auftrag §17).

## 4. Workspaces (`workspaces`-Tabelle)

- **0 Einträge** — Workspace-Konzept existiert (Spalten: tenant_id, workspace_key, name, trading_mode, status), aber ungenutzt.
- Auftrag §5 Zielarchitektur: Workspaces als Teil des Tenant-Layers → Phase 1+.

## 5. Sessions (`security_users.json` → `sessions`)

| Aspekt | Befund |
|---|---|
| Anzahl | 422 (admin) |
| Felder | created, last_seen, ip, rotated_at, mfa_verified_at |
| Rotation | `rotate_session` vorhanden (SID-Rotation) |
| Widerruf | `revoke_session`, `revoke_all_sessions` vorhanden (API: `/api/users/<name>/revoke`) |
| Ablauf | **kein expires_at / kein Session-GC** → Lücke |
| Gerät/Browser | ❌ nicht erfasst (kein User-Agent) |
| Auto-Invalidierung nach Passwort-/MFA-Änderung | `change_password` / MFA-Änderung → Session-Widerruf **zu prüfen** (nicht verifiziert) |

## 6. MFA

| Aspekt | Befund |
|---|---|
| TOTP-Implementierung | `generate_mfa_secret`, `_totp`, `verify_mfa`, `mfa_provisioning_uri` (Z946–1025) |
| Enable/Disable | `enable_mfa(username, code)`, `disable_mfa(username, by_admin)` |
| Pflicht für Admin/Superadmin | ❌ **nicht erzwungen** (admin: mfa_enabled=false) |
| Verifikations-Tracking | `mfa_recently_verified`, `mark_mfa_verified` vorhanden; `require_recent_mfa` existiert |
| Recovery-Codes | ❌ fehlt |
| Verlustprozess | ❌ fehlt (nur `mfa_emergency`-Permission existiert) |
| Reset mit Audit | `disable_mfa(by_admin)` ruft vermutlich audit_log — zu verifizieren |

## 7. Login-Rate-Limit (`login_rate.json`)

| Eintrag | fails | blocked_until | Status |
|---|---|---|---|
| `203.0.113.7` (TEST-NET) | 3 | 0 | Rest aus Tests |
| `198.51.100.23` (TEST-NET) | 2 | 0 | Rest aus Tests |
| `unknown` | 2 | 0 | Rest |
| `__v23__` | 5 | abgelaufen | Rest aus Tests |

**Befund:** Aktive Blockade keine; Einträge sind Test-Artefakte (TEST-NET-Ranges). Max-Attempts-Konfiguration nicht geprüft (BlockTime-Eskalation lt. Memory: 8→32→64→128 s).

## 8. Empfohlene Phasen-Reihenfolge (User/Tenant-Bezug)

```text
2.  Bekannte Fehler (Risk-70-Test, _budget_debug)
3.  Benutzerverwaltung: Status-Lebenszyklus, Sessions-GC, MFA-Pflicht, Recovery-Codes
4.  Rollen: 38 Permissions, Rollen-Matrix-Tests, tenant-scoped require_permission
5.  Tenant-Isolation: Test-User-Müll entfernen, 2. Tenant anlegen
17. Zweiter Tenant-Test: Leak-Tests (Depots/Provider/Regeln/Audit/Sessions/Orders)
```
