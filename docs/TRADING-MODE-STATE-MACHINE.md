# TRADING-MODE-STATE-MACHINE

Stand: v2.42.0 (2026-08-09) · Phase 4 (§8 / §14 des Hermes-Arbeitsauftrags) · getestet: 259 OK

## Zustände (8)

| Zustand | Bedeutung |
|---|---|
| `SHADOW` | Nur simulierte Entscheidungen, keine Orders (Default) |
| `PAPER` | Paper-Trading mit simulierten Orders |
| `LIVE_REQUESTED` | Live-Antrag gestellt (Operator/Admin), wartet auf Freigabe |
| `LIVE_APPROVED` | Live-Freigabe erteilt (Vier-Augen + MFA), noch nicht aktiv |
| `LIVE_ACTIVE` | Live-Handel aktiv (nur mit Broker-Adapter; PAPER_ONLY sperrt) |
| `PAUSED` | Handel pausiert (manuell) |
| `SUSPENDED` | Handel ausgesetzt (System/Risiko) |
| `REVOKED` | Live-Status widerrufen — kein Handel |

## Erlaubte Transitionen (db.MTDB.MODE_TRANSITIONS)

```
SHADOW         -> PAPER, SUSPENDED
PAPER          -> SHADOW, LIVE_REQUESTED, PAUSED, SUSPENDED
LIVE_REQUESTED -> LIVE_APPROVED, PAPER, SHADOW, REVOKED, SUSPENDED
LIVE_APPROVED  -> LIVE_ACTIVE, REVOKED, SUSPENDED
LIVE_ACTIVE    -> PAUSED, SUSPENDED, REVOKED
PAUSED         -> SHADOW, PAPER, LIVE_ACTIVE, SUSPENDED, REVOKED
SUSPENDED      -> SHADOW, PAPER, REVOKED
REVOKED        -> SHADOW, PAPER
```

Kein Zustand kann in sich selbst übergehen; kein direkter Sprung
SHADOW → LIVE_* (Freigabeprozess zwingend).

## Phase-4-Verbesserungen (§8)

1. **Batch-Trader Mode-Gate** (`batch_trader.main()`):
   - `PAUSED`/`SUSPENDED`/`REVOKED`/`LIVE_*` → sofortiger Abbruch mit Log,
     **kein Markt-Scan, kein Handel**. Vorher tradete der Cron in gesperrten
     Zuständen weiter — kritische Lücke.
2. **Vier-Augen + MFA bei Live-Freigabe** (`security.set_trading_mode`):
   - `LIVE_APPROVED` und `LIVE_ACTIVE` erfordern:
     - `approved_by` gesetzt (Vier-Augen-Freigabe durch zweiten User)
     - `approved_by != requested_by` (Antragsteller darf nicht selbst genehmigen, §14)
     - `mfa_confirmed == 1` (MFA-Bestätigung)
   - Sonst `ValueError`, kein Moduswechsel, kein Audit-Eintrag.
3. **`allowed_transitions` in API:** GET `/api/trading_mode` liefert die
   erlaubten Folgezustände aus der State-Machine (Frontend rendert nur
   zulässige Aktionen).

## Audit

Jeder Wechsel schreibt `trading_mode_transitions` (Tabelle, Index auf
tenant_id): old_mode, new_mode, reason, requested_by, approved_by,
mfa_confirmed, risk_review_status, broker_connection_status,
audit_event_id — Pflichtfelder aus §8.

## Testabdeckung (Sektion 7q, v2.42.0)

- Vollständige Zustandsmenge (8 Modi)
- Kern-Transitionen: SHADOW→PAPER erlaubt, SHADOW→LIVE_ACTIVE verboten,
  PAPER→LIVE_REQUESTED, LIVE_REQUESTED→LIVE_APPROVED, LIVE_APPROVED→LIVE_ACTIVE,
  LIVE_ACTIVE→PAUSED/SUSPENDED/REVOKED, SUSPENDED→REVOKED, keine Selbst-Transitionen
- `set_trading_mode` wirft ValueError bei illegaler Transition
- Vier-Augen: ohne approved_by blockiert; Selbst-Genehmigen blockiert;
  fremder approved_by + MFA erlaubt; ohne MFA blockiert
- Batch-Gate: SUSPENDED → `main()` ruft `scan_markt` nicht auf

## Betriebshinweis

Produktiv steht der Tenant auf **SHADOW** (PAPER_ONLY = kein LIVE). Ein
Live-Antrag durchläuft zwingend LIVE_REQUESTED → (Vier-Augen+MFA)
→ LIVE_APPROVED → LIVE_ACTIVE; jede Stufe ist auditiert und jederzeit
über SUSPENDED/REVOKED beendbar.
