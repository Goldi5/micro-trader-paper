# Provider-Connection-Architektur (PHASE 7, v2.31.0)

> PHASE 7 des Mandanten-Ausbauauftrags (Sektion 10). Trennung von Marktdaten/KI/Broker.
> Secrets niemals als Klartext - nur als Referenz (vault://...).

## Prinzip (OWASP API-Key-Management)
- Jede Verbindung gehoert zu einem Tenant (tenant-scoped).
- Secrets werden NICHT in JSON/HTML/Logs/Klartext gespeichert.
- API-Schluessel pro Tenant/Benutzer getrennt.
- Multi-Tenant-Trennung nie nur ueber Browser-Tenant-ID.

## Datenmodell: provider_connections
id, tenant_id, workspace_id, user_id, provider_type, provider_name,
environment (DEMO/PAPER/SANDBOX/LIVE), status, permissions,
secret_reference (vault://...), created_by, created_at, updated_at,
last_test_at, last_error, rate_limit

## API
- GET  /api/providers            -> eigene Verbindungen (Secret maskiert ••••)
- POST /api/providers/add        -> Verbindung anlegen (TENANT_ADMIN)
- POST /api/providers/test/<id>  -> Verbindung testen (TENANT_ADMIN)

## Sicherheit
PAPER_ONLY: keine echten API-Calls im Test-Modus. Secret nie im Response
(vollstaendig maskiert). Fremd-Tenant-Verbindungen nicht sichtbar (tenant_id-Filter).
