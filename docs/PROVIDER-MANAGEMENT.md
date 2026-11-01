# PROVIDER-MANAGEMENT (§19-Punkt 9, §11)

Plattform-weite Verwaltung von Daten-/KI-/Broker-Provider-Verbindungen, strikt
tenant-scoped. Jede Verbindung ist eine Zeile in `provider_connections`
(Tabelle in `db.py`).

## Datenmodell (`provider_connections`)

| Feld | Zweck |
|---|---|
| `id` | PK |
| `tenant_id` | Mandant (Isolation) |
| `workspace_id` | optionaler Workspace-Kontext |
| `user_id` | anlegender User |
| `provider_type` | MARKETDATA / KI / BROKER / EXECUTION |
| `provider_name` | z.B. Yahoo, Finnhub, Nous, OpenRouter |
| `environment` | DEMO / PAPER / SANDBOX / LIVE |
| `status` | s. Status-Maschine |
| `permissions` | z.B. "read" |
| `secret_reference` | Referenz auf `secret_store` (NICHT Klartext) |
| `created_by` / `created_at` / `updated_at` | Audit |
| `last_test_at` / `last_error` / `rate_limit` | Health |

## Status-Maschine

Zustände: `UNCONFIGURED, CONFIGURED, TESTING, HEALTHY, DEGRADED, FAILED,
DISABLED, EXPIRED` (Legacy `aktiv`/`fehler` werden gemapped).

Erlaubte Transitionen (Guard in `provider_connection_set_status`):

```
UNCONFIGURED -> CONFIGURED, DISABLED
CONFIGURED   -> TESTING, DISABLED, EXPIRED
TESTING      -> HEALTHY, DEGRADED, FAILED, DISABLED
HEALTHY      -> TESTING, DEGRADED, FAILED, DISABLED, EXPIRED
DEGRADED     -> TESTING, HEALTHY, FAILED, DISABLED, EXPIRED
FAILED       -> TESTING, DISABLED, CONFIGURED, EXPIRED
DISABLED     -> CONFIGURED, UNCONFIGURED, aktiv
EXPIRED      -> CONFIGURED, DISABLED
```

Illegale Sprünge (z.B. DISABLED -> HEALTHY) werden mit
`{"ok": False, "reason": "Transition X -> Y nicht erlaubt"}` abgelehnt.

## APIs (alle TENANT_ADMIN, in `ROUTE_ACCESS` registriert)

| Route | Methode | Funktion |
|---|---|---|
| `/api/providers` | GET | Liste (tenant-scoped) |
| `/api/providers/add` | POST | anlegen |
| `/api/providers/test/<id>` | POST | Verbindung testen |
| `/api/providers/disable/<id>` | POST | -> DISABLED |
| `/api/providers/enable/<id>` | POST | -> CONFIGURED |
| `/api/providers/delete/<id>` | POST | löschen (tenant-scoped) |
| `/api/providers/status/<id>` | POST | beliebige erlaubte Transition |

Alle Operationen sind tenant-scoped: Ein Zugriff mit falscher `tenant_id`
liefert `{"ok": False, "reason": "Verbindung nicht gefunden (tenant-scoped)"}`.
Cross-Tenant-Zugriff ist somit nicht möglich.

## Secret-Regeln

- Vollständige Keys nie im Klartext (nur `secret_reference` in der Connection)
- `secret_store` ist tenant-isoliert
- Rotation via `/api/secrets/rotate` (s. SECRET-CONNECTION-MANAGEMENT.md)
- Secrets nie in Logs/Audit (nur Aktion + Key-Name)
