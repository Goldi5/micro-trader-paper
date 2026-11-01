# SECRET-CONNECTION-MANAGEMENT (§19-Punkt 9, §11)

Tenant-isolierte Verwaltung von Secrets (API-Keys, Tokens) mit Rotation und
Redaction. Niemals Klartext in API-Responses, Logs oder Audit.

## Speicher (`secret_store`, Tabelle in `db.py`)

| Feld | Zweck |
|---|---|
| `id` | PK |
| `tenant_id` | Mandant (UNIQUE mit `secret_key`) |
| `secret_key` | logischer Name, z.B. `API_YAHOO` |
| `secret_value` | Klartext (nur in DB, nie ausgegeben) |
| `created_at` / `updated_at` | Audit |

## Funktionen (`db.py` + `security.py`)

- `secret_set(tenant_id, key, value)` — anlegen/überschreiben
- `secret_get(tenant_id, key)` — lesen (nur intern)
- `secret_list_keys(tenant_id)` — nur Key-Namen (für UI)
- `secret_rotate(tenant_id, key, new_value)` — Rotation (Audit-fähig)
- `secret_last4(tenant_id, key)` — nur `"****" + last4` (Anzeige)

## Rotation (`/api/secrets/rotate`, TENANT_ADMIN)

Request:
```json
{ "key": "API_YAHOO", "value": "neuer-geheimer-key-1234" }
```

Response (KEIN Klartext):
```json
{ "ok": true, "rotated": "API_YAHOO", "last4": "1234" }
```

Die Rotation ist audit-logged (`sec.audit_log("secret_rotate", ...)`), aber der
neue Wert erscheint **nicht** im Log.

## Redaction-Regeln (hart)

1. Vollständige Keys niemals anzeigen → nur `last4`
2. Secrets nicht in Logs schreiben
3. Secrets nicht in HTML ausgeben
4. Secrets nicht in Git speichern (`.gitignore` + Laufzeit-Daten)
5. Secret-Referenzen statt Klartext in normalen Datensätzen (z.B.
   `provider_connections.secret_reference = "sec:yahoo_1"`)
6. Änderung und Rotation auditieren

## Tenant-Isolation

Alle `secret_*`-Funktionen erwarten `tenant_id` und grenzen strikt ab. Ein
Zugriff mit fremder `tenant_id` liefert `None` / leere Liste.
