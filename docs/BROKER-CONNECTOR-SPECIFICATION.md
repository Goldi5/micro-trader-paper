# BROKER-CONNECTOR-SPECIFICATION

> Micro-Trader · Phase 13 (v2.36.0) · Teil des Hermes-Arbeitsauftrags (§10)
> Ziel-Architektur: `Trading Strategy → Risk Engine → Order Intent → Broker Adapter → Broker API`
> Implementiert in `security.py` (Sektion „PHASE 13: Order-Intent + Broker-Connector-Schnittstelle").

## 1. Grundsätze

- **Keine** Brokerlogik in `ki_decisions.py`, `engine.py` oder `batch_trader.py`.
- Jede Order entsteht als **Order-Intent-Objekt** (siehe `ORDER-RISK-CHECKLIST.md`).
- **PAPER_ONLY**: Es gibt keinen Live-Adapter. Implementiert sind nur:
  1. ✅ Simulator-/Paper-Adapter (`PaperBrokerAdapter`)
  2. ⏳ Sandbox-/Demo-Adapter (nicht implementiert — kein Broker festgelegt)
  3. ⛔ Live-Adapter (bewusst NICHT, erst nach Sandbox-Brokerintegration)
- Kein Echtgeldanbieter wird eigenmächtig ausgewählt (Auftrag §10, letzter Absatz).

## 2. Verbindliche Schnittstelle (`BrokerProvider`)

```python
class BrokerProvider:
    def connect(self)                    # → {"ok", "broker"}
    def disconnect(self)                 # → {"ok"}
    def health_check(self)               # → {"ok", "broker"}
    def get_account(self, tenant_id=None)      # → {"tenant_id", "portfolios", "wert", "broker", "mode"}
    def get_positions(self, tenant_id=None)    # → [{"ticker", "shares"}]
    def get_quote(self, ticker)                # → {"ticker", "price"}
    def place_order(self, intent)              # → {"ok", "order_id", "status"} | {"ok": False, "error", "status": "blocked"}
    def cancel_order(self, order_id, tenant_id=None)
    def get_order_status(self, order_id, tenant_id=None)
    def get_open_orders(self, tenant_id=None)
```

Alle Methoden sind **tenant-scoped** (`tenant_id` in jeder Query).
Alle Methoden außer `get_quote` werden in `PaperBrokerAdapter` implementiert.

## 3. PaperBrokerAdapter (Simulator, aktiv)

| Methode | Verhalten |
|---------|-----------|
| `connect()` | setzt `_connected=True`, liefert `{"ok": True, "broker": "paper-simulator"}` |
| `disconnect()` | setzt `_connected=False` |
| `health_check()` | `{"ok": _connected, "broker": "paper-simulator"}` |
| `get_account()` | liest `paper_portfolios` (Anzahl + Summe `virtual_cash`), `mode: "PAPER"` |
| `get_positions()` | aggregiert `paper_orders` nach Ticker (Shares) |
| `get_quote()` | `marktdaten.hole_kurs_fuer(ticker)` (einzige externe Datenquelle) |
| `place_order()` | validiert Intent (15-Check-Liste) → `paper_order_insert` + `paper_position_apply` |
| `cancel_order()` | setzt Status `cancelled` (tenant-scoped) |
| `get_order_status()` | liest Status aus `paper_orders` |
| `get_open_orders()` | offene/gefillte Orders des Tenants |

`place_order` blockt: LIVE-Modi (PAPER_ONLY), PAUSED/SUSPENDED/REVOKED,
fehlende Ticker, Menge ≤ 0, geschlossenen Markt, >20 Positionen,
Risiko-Limit-Verstoß, Regel-Verstoß.

## 4. DB-Anbindung

| Tabelle | Verwendung |
|---------|------------|
| `paper_orders` | Order-Buch (tenant_id, portfolio_id, ticker, side, quantity, price, status, order_type) |
| `paper_positions` | Positionen (portfolio_id, ticker, shares, avg_price) |
| `paper_portfolios` | virtuelle Depots (virtual_cash, status) |

`side` wird als `BUY`/`SELL` gespeichert (db.py-Konvention).

## 5. Umgebungen (Auftrag §5)

```text
DEMO    → nicht verwendet
PAPER   → PaperBrokerAdapter (aktiv, einzig implementiert)
SANDBOX → offen für späteren Sandbox-Adapter (kein Broker gewählt)
LIVE    → gesperrt (PAPER_ONLY-Hartgrenze; Intent-Validierung blockt LIVE_*)
```

Eine LIVE-Verbindung darf nie automatisch in PAPER verwendet werden und umgekehrt —
aktuell irrelevant, da kein Live-Adapter existiert. Der Gate-Mechanismus
(`validate_order_intent` Modus-Check) ist aber bereits aktiv.

## 6. Nächste Schritte (bewusst offen)

1. Sandbox-/Demo-Adapter eines ausgewählten Brokers (erfordert Broker-Auswahl durch den Betreiber)
2. `secret_reference`-Anbindung des Adapters an den Secret-Store (Phase 8)
3. Live-Adapter NUR nach: Sandbox-Test bestanden + Live-Freigabeprozess (Vier-Augen) + MFA
4. `broker_connections`-Tabellen-Einbindung in `place_order` (Umgebungs-Pflichtcheck)
