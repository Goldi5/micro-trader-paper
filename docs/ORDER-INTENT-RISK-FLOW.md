# Order-Intent & Risk-Flow (§19-Punkt 12)

**Version:** 2.48.0 (2026-08-10) · **Phase:** 12 · **Status:** fertig

## Zweck

Jede Trading-Order entsteht als **Order-Intent** (validiert) VOR der Ausführung.
Ein 18-Punkte-Checklist (§13) prüft, ob die Order erlaubt ist. Risk-Limits werden
durchgesetzt (`enforce_risk_limits`).

## Flow

```
KI-Entscheidung (decision)
  ↓
create_order_intent(ticker, side, qty, limit_price, tenant_id, user_id)
  ↓
validate_order_intent(intent)  ← 18-Punkte-Checkliste
  ├─ Modus (PAPER_ONLY / LIVE)
  ├─ Menge/Ticker valid
  ├─ Markt-Regeln (BLOCK/ALLOW)
  ├─ Max-Positionen
  ├─ Risiko-Limit (drawdown)
  ├─ Vier-Augen (bei LIVE)
  ├─ Tenant-Isolation
  ├─ User darf handeln
  ├─ Portfolio aktiv
  ├─ Broker-Env (SANDBOX/PAPER)
  ├─ Daten aktuell
  ├─ Preis > 0
  ├─ Tages/Total/Drawdown-Limit
  ├─ Pause/Suspend
  ├─ Doppel-Order
  └─ Freigabe-Status
  ↓ (bei Verstoss: INTENT_BLOCK)
execute_order_intent(intent)  ← nur bei ok=True
  ↓
Broker-Adapter (SandboxBrokerAdapter im PAPER/SANDBOX)
```

## Komponenten

| Funktion | Datei | Beschreibung |
|----------|-------|--------------|
| `create_order_intent` | security.py | Erstellt Intent (17 Pflichtfelder + UUID) |
| `validate_order_intent` | security.py | 18-Punkte-Checkliste, return `{"ok": bool, "checks": [...]}` |
| `enforce_risk_limits` | security.py | Drawdown/Tages/Total-Limits prüfen |
| `execute_order_intent` | security.py | Führt Intent aus (Broker-Adapter) |
| `four_eyes_required` | security.py | Vier-Augen bei LIVE-Aktionen |
| `SandboxBrokerAdapter` | security.py | Simuliert Order im `paper_orders`-Buch |

## PAPER_ONLY

`PAPER_ONLY = TRUE` — keine echten Orders. `validate_order_intent` blockt LIVE-Modus
(außer nach Freigabe + Vier-Augen + MFA). Der Broker-Adapter läuft immer im
SANDBOX/PAPER-Modus.

## Tests

`test_server_security.py` Sektion 12 (Order-Intent + Risk):
- Intent erstellt (Pflichtfelder)
- Validation blockiert bei PAPER_ONLY+LIVE
- Validation blockiert bei BLOCK-Regel
- Validation blockiert bei Risk-Limit-Überschreitung
- Vier-Augen erfordert bei LIVE

**Ergebnis:** 306 OK, 0 FAIL (v2.48.0)

## Verwandte Dokumente

- `TRADING-MODE-STATE-MACHINE.md` (§14) — Modus-Wechsel
- `SECURITY-GATES.md` (§13) — Vier-Augen + MFA
- `LIVE-ANTRAGSPROZESS.md` (§19-P14) — Live-Antragsworkflow
- `BROKER-CONNECTOR-SPECIFICATION.md` — Broker-Adapter-Interface
