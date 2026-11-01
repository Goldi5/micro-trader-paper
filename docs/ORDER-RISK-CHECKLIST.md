# ORDER-RISK-CHECKLIST

> Micro-Trader · Phase 13 (v2.36.0) · Teil des Hermes-Arbeitsauftrags (§11)
> Jede Order MUSS diese Checkliste durchlaufen, BEVOR sie ausgeführt wird —
> auch Paper-Orders. Implementiert in `security.py` (`validate_order_intent`)
> und erzwungen im Trading-Pfad (`batch_trader.py`, `PaperBrokerAdapter.place_order`).

## 1. Die 15 Checks vor jeder Order

| # | Check | Implementierung | Blockiert bei Verstoß? |
|---|-------|-----------------|------------------------|
| 1 | Modus ist LIVE_ACTIVE (oder PAPER erlaubt) | `validate_order_intent` Modus-Gate | ✅ LIVE/SUSPENDED/REVOKED blockiert |
| 2 | PAPER_ONLY-Hartgrenze | Modus-Gate: `mode.startswith("LIVE")` → block | ✅ |
| 3 | Brokerverbindung aktiv | `BrokerProvider.health_check()` | (Adapter-Ebene) |
| 4 | Verbindung gehört zum richtigen Tenant | Tenant-scoped Queries (paper_orders.tenant_id) | ✅ |
| 5 | Verbindung gehört zum richtigen Portfolio | `portfolio_id` im Intent | ✅ |
| 6 | API-Key besitzt erforderliche Rechte | Secret-Store-Permissions (Phase 8) | (bei Live-Adapter) |
| 7 | Risikolimit wird eingehalten | `enforce_risk_limits` (Position/Drawdown) | ✅ |
| 8 | Ordergröße ist erlaubt | `enforce_risk_limits` position_size | ✅ |
| 9 | Tagesverlustlimit wird eingehalten | `enforce_risk_limits` drawdown | ✅ |
| 10 | Maximalzahl Positionen (Default 20) | `validate_order_intent` position_count | ✅ |
| 11 | Ticker ist erlaubt | `enforce_rules` (BLOCK/MAX_KAUF/REGEX) | ✅ |
| 12 | Markt ist geöffnet | `market_open`-Parameter | ✅ |
| 13 | Keine Trading-Pause | Modus-Gate (PAUSED blockiert) | ✅ |
| 14 | Keine Sicherheitswarnung / veraltete Marktdaten | `get_quote` Preis>0-Check (batch_trader Verkaufsschutz) | ✅ |
| 15 | Order nicht doppelt erstellt | UUID `order_intent_id` pro Intent | ✅ |

## 2. Order-Intent-Pflichtfelder (Auftrag §11)

```text
order_intent_id   → UUID hex[:16] (create_order_intent)
tenant_id         → aus Session/Tenant-Kontext, NIE vom Client
user_id           → aus Session
portfolio_id      → Ziel-Portfolio
strategy_id       → Strategie (optional)
mode              → SHADOW | PAPER | LIVE_* | PAUSED | ...
ticker            → Symbol
side              → buy | sell
quantity          → > 0
order_type        → market (Default) | limit | stop
limit_price       → optional
stop_price        → optional
reason            → KI-Begründung
decision_id       → KI-Entscheidungs-ID
rule_version      → aktiver Regelstand
risk_check_status → pending → passed | blocked
created_at        → ISO-Zeitstempel
```

## 3. Ablauf im Trading-Pfad

```text
KI-Entscheidung (kaufen/verkaufen)
        ↓
create_order_intent(...)          ← Intent-Objekt entsteht IMMER zuerst
        ↓
validate_order_intent(...)        ← 15-Check-Liste (Tabelle oben)
        ↓  allowed
PaperBrokerAdapter.place_order()  ← Simulator: paper_orders + paper_positions
        ↓
Order-Status "filled" / "blocked"
```

- `blocked`-Orders werden NICHT ins Order-Buch geschrieben.
- Ein fehlgeschlagener Intent-Check ist NIE fatal (try/except, PAPER_ONLY-Prinzip) —
  die Order wird dann aber auch nicht ausgeführt.
- Kein Live-Adapter existiert; `LIVE_*`-Modi werden hart blockiert.

## 4. Verifikation

```bash
python test_server_security.py   # Sektion 7l: 20 Tests (Intent + Broker + Vier-Augen)
```

Tests decken ab: alle 17 Pflichtfelder, valid→passed, LIVE→block, PAUSED→block,
Menge 0→block, Markt zu→block, >20 Positionen→block, BrokerProvider-Abstraktion,
PaperBroker connect/health/account/place/status/Position, Vier-Augen-Regel.
