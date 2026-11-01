# Trading-Modi-Zustandsmaschine (PHASE 5, v2.29.0)

> PHASE 5 des Mandanten-Ausbauauftrags (Sektion 8). Implementiert die 8 Zustaende
> als explizite State Machine mit erzwungenen Transitionen + Audit-Log.

## Zustaende

| Modus | Bedeutung |
|-------|-----------|
| SHADOW | Entscheidungen beobachten, keine Order, Lern/Audit |
| PAPER | Virtuelle Orders, eigenes virtuelles Portfolio |
| LIVE_REQUESTED | Benutzer beantragt Live, Pruefungen laufen |
| LIVE_APPROVED | Antrag genehmigt, Broker darf vorbereitet werden |
| LIVE_ACTIVE | Echte Orders technisch moeglich (nach allen Checks) |
| PAUSED | Keine neuen Orders, offene Positionen sichtbar |
| SUSPENDED | Auto/manuell wegen Risiko, Adminpruefung noetig |
| REVOKED | Live-Freigabe entzogen, Broker deaktivieren |

## Erlaubte Transitionen (MODE_TRANSITIONS)

```
SHADOW        -> PAPER, SUSPENDED
PAPER         -> SHADOW, LIVE_REQUESTED, PAUSED, SUSPENDED
LIVE_REQUESTED-> LIVE_APPROVED, PAPER, SHADOW, REVOKED, SUSPENDED
LIVE_APPROVED -> LIVE_ACTIVE, REVOKED, SUSPENDED
LIVE_ACTIVE   -> PAUSED, SUSPENDED, REVOKED
PAUSED        -> SHADOW, PAPER, LIVE_ACTIVE, SUSPENDED, REVOKED
SUSPENDED     -> SHADOW, PAPER, REVOKED
REVOKED       -> SHADOW, PAPER
```

Jeder nicht erlaubte Wechsel wird mit `ValueError` abgelehnt (serverseitig erzwungen).

## Audit (Sektion 8 Pflichtfelder)

Tabelle `trading_mode_transitions`:
`id, tenant_id, user_id, portfolio_id, strategy_id, old_mode, new_mode, reason,
requested_by, approved_by, timestamp, mfa_confirmed, risk_review_status,
broker_connection_status, audit_event_id`

Jeder Wechsel schreibt einen Eintrag (via `security.set_trading_mode`).

## API

- `GET /api/trading_mode` → aktueller Modus des Tenants
- `POST /api/trading_mode/set` (TENANT_ADMIN) → Moduswechsel (erzwingt Transition)
- `GET /api/trading_mode/history` → Audit-Verlauf

## Sicherheit

PAPER_ONLY bleibt aktiv: kein Uebergang zu LIVE_* ohne vier-Augen/Manuell-Freigabe
(Phase 11/12 folgt). Aktuell ist LIVE_* nur als Zustand modelliert, nicht ausfuehrbar.
