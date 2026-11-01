# Live-Antragsprozess (§19-Punkt 8)

**Version:** 2.49.0 (2026-08-10) · **Phase:** 14 · **Status:** fertig

## Zweck

Mandanten (Tenants) beantragen den Wechsel von **PAPER** (Papierhandel) zu **LIVE**
(Echtgeldhandel) über einen strukturierten, tenant-scoped Antragsworkflow. Ein Antrag
muss reviewt und genehmigt werden, bevor `set_trading_mode` den Modus auf LIVE setzen
darf.

## Status-Maschine

```
PENDING ──review──> IN_REVIEW ──approve──> APPROVED ──activate──> ACTIVATED
   │                    │                     │
   └────reject──────────┴─────────────────────┴──> REJECTED
```

- **PENDING**: Antrag erstellt (vom Tenant-Admin)
- **IN_REVIEW**: Reviewt (von einem Reviewer)
- **APPROVED**: Genehmigt (von einem Approver)
- **ACTIVATED**: Live-Modus aktiviert (nach Genehmigung)
- **REJECTED**: Abgelehnt (vor oder nach Review)

## Tabellenstruktur (`live_requests`)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | INTEGER PK | Auto-Increment |
| `tenant_id` | INTEGER | Mandant (tenant-scoped) |
| `requested_by` | INTEGER | User-ID des Antragstellers |
| `status` | TEXT | PENDING / IN_REVIEW / APPROVED / REJECTED / ACTIVATED |
| `broker_connection_id` | INTEGER | Referenz auf `provider_connections` |
| `risk_assessment` | TEXT | Risiko-Bewertung (optional) |
| `requested_at` | TEXT | Erstellungszeitpunkt |
| `reviewed_by` / `reviewed_at` | INTEGER / TEXT | Reviewer + Zeitpunkt |
| `activated_at` | TEXT | Aktivierungszeitpunkt |
| `note` | TEXT | Notiz / Begründung |

**Constraint:** `UNIQUE(tenant_id, status)` — verhindert parallele offene Anträge
(PENDING/IN_REVIEW/APPROVED/ACTIVATED) pro Tenant.

## API-Endpunkte

| Methode | Pfad | Berechtigung | Beschreibung |
|---------|------|--------------|--------------|
| POST | `/api/live-requests` | TENANT_ADMIN | Antrag erstellen |
| GET  | `/api/live-requests` | TENANT_ADMIN | Anträge des Tenants listen |
| POST | `/api/live-requests/<id>/approve` | TENANT_ADMIN | Genehmigen (nach Review) |
| POST | `/api/live-requests/<id>/reject` | TENANT_ADMIN | Ablehnen |

## Sicherheitsregeln

1. **Approve ohne Review blockiert** — `live_request_approve` erfordert Status `IN_REVIEW`
2. **Cross-Tenant-Zugriff blockiert** — alle Methoden prüfen `tenant_id` (tenant-scoped)
3. **Doppelter Antrag blockiert** — `live_request_create` schlägt fehl, wenn ein offener
   Antrag (PENDING/IN_REVIEW/APPROVED/ACTIVATED) existiert
4. **Antragsteller ≠ Approver** — implizit durch Vier-Augen-Regel (§3.2)

## Integration mit `set_trading_mode`

`PAPER -> LIVE_REQUESTED` ist nur erlaubt, wenn ein **genehmigter** (APPROVED/ACTIVATED)
Antrag existiert. Sonst blockiert der Mode-Gate.

## Tests

`test_server_security.py` Sektion 14 (8 Tests, isolierte Tenants 50/51):
- Live-Antrag erstellt (PENDING)
- Approve ohne Review blockiert
- Review PENDING→IN_REVIEW
- Approve IN_REVIEW→APPROVED
- Activate APPROVED→ACTIVATED
- Doppelter Antrag blockiert
- Cross-Tenant Review blockiert
- Reject IN_REVIEW→REJECTED

**Ergebnis:** 313 OK, 0 FAIL (v2.49.0)

## Verwandte Dokumente

- `TRADING-MODE-STATE-MACHINE.md` (§14) — Modus-Wechsel PAPER↔LIVE
- `SECURITY-GATES.md` (§13) — Vier-Augen + MFA bei LIVE
- `TENANT-ISOLATION-VERIFICATION.md` (§17) — tenant-scoped Daten
