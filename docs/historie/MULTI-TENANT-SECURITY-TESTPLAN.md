# Mandantentrennung (PHASE 4, v2.28.0)

> PHASE 4 des Mandanten-Ausbauauftrags (§16 Schritt 4). OWASP Multi-Tenant:
> Daten niemals anhand einer vom Browser gelieferten Tenant-ID trennen.

## Prinzip

Jeder Datentraeger (Depot) traegt ein `tenant_id` (Default 1 = Haupt-Tenant).
Alle Lese-Zugriffe filtern serverseitig auf den **aus der Session abgeleiteten**
Tenant (``security.get_current_tenant()``), nie auf Client-Input.

## Umsetzung

### SQLite (db.py)
- Neue Tabellen ``depots``, ``etf_depots``, ``spec_depots`` (tenant_id-Spalte).
- ``depot_register(table, tenant_id, ...)`` / ``depot_list_tenant(table, tid)``.
- ``query_trades(..., tenant_id=1)`` / ``query_ki(..., tenant_id=1)`` — jede
  Query erzwingt Tenant-Scope (schliesst PHASE-0-Luecke in ``/api/db_query``).

### Dashboard (dashboard.py)
- ``_tenant_scoped_depot_files(tid)`` — scannt alle ``depot_*.json`` /
  ``etf_*.json`` / ``spec_depots/*.json`` undfiltert auf ``d["tenant_id"] == tid``.
- ``data()`` laedt nur noch Tenant-Dateien (kein globaler Lese-Mix mehr).
- ``/api/ki_log`` — nur KI-Log-Eintraege mit ``tenant_id == aktiver Tenant``.
- ``/depot_json`` — 403 wenn Depot nicht zum Tenant gehoert.
- ``/api/db_query`` — ueberschreibt jeden Client-``tenant_id``-Parameter mit dem
  Session-Tenant (Server-Autorisierung).

### Depot-JSONs
Bestehende Depots bleiben lesbar: fehlt ``tenant_id``, gilt Default 1.
Neue Depots tragen ``tenant_id`` explizit.

## Tests (Sektion 7d, 5 neu -> 74 OK, 0 FAIL)
- Tenant 1 sieht Tenant-5-Depot NICHT (Scope-Isolation).
- Tenant 5 sieht eigenes Depot.
- ``depot_list_tenant(5)`` isoliert, ``depot_list_tenant(1)`` sieht T5 nicht.
- ``query_trades(tenant=999)`` leer (kein Datenleck).

## Naechste Phasen (§16)
- PHASE 5: Trading-Modi-Zustandsmaschine (SHADOW/PAPER/LIVE_*).
- PHASE 6: Shadow→Paper-Workflow.
- PHASE 7: Provider-Abstraktion.
- PHASE 8: Secret-/Connection-Manager.
- PHASE 9: Paper-/Simulator-Broker.
- PHASE 10: Broker-Connector-Schnittstelle.
