# Secret-Store-Architektur (PHASE 8, v2.32.0)

> PHASE 8 des Mandanten-Ausbauauftrags (Sektion 11). Tenant-isolierte Secrets.
> Kein globaler .env-Key mehr - jeder Tenant verwaltet eigene Secrets.

## Prinzip (OWASP)
- Secrets werden NICHT im globalen .env gespeichert (tenant-uebergreifend).
- Jede Secret ist an tenant_id gebunden (Unique(tenant_id, secret_key)).
- Auslesen NUR serverseitig fuer den eigenen Tenant.
- API liefert NUR Schluessel, NIEMALS Werte (kein Leak ueber JSON/HTML).

## Datenmodell: secret_store
id, tenant_id, secret_key, secret_value, created_at, updated_at
UNIQUE(tenant_id, secret_key)

## API
- GET  /api/secrets       -> eigene Schluessel (Werte maskiert/nicht enthalten)
- POST /api/secrets/set   -> Secret tenant-scoped speichern (TENANT_ADMIN)

## Sicherheit
Tenant-Isolation: secret_get(1, key) != secret_get(5, key).
Kein fremder Tenant kann Secret anderer Tenants lesen (tenant_id-Filter).
PAPER_ONLY: Secrets werden nicht fuer echte Live-API-Calls genutzt.
