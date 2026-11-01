# BROKER-SIMULATOR — Phase 9

> Phase 9: Broker-Simulator + Sandbox-Adapter. Stand: 2026-08-12.

## Änderung

- **`broker_simulator.py` (NEU):**
  - `BrokerAdapter` (ABC): Interface für echte Broker (Phase 14+, hier nur Definition).
  - `BrokerSimulator(BrokerAdapter)`: simuliert Orders ohne echte API-Calls.
    - BUY/SELL mit Cash-Check, Position-Tracking.
    - **Kill-Switch-Respekt:** `submit_order` rejectet wenn `LiveSystem.ist_gestoppt`.
    - Fills in `sim_broker_fills.json` (isoliert).
  - **PAPER_ONLY:** keine echten Netzwerk-Calls, keine echten Keys.

## Verifikation (ad-hoc, PASS)

```bash
python -c "from broker_simulator import BrokerSimulator; s=BrokerSimulator(200);
print(s.submit_order({'ticker':'AAPL','side':'buy','qty':2,'price':10})['status'])"
# -> FILLED, Cash 191.0, Pos {AAPL:1}
```

## Nächste Phase

**Phase 10 — Order-Sync + Reconciliation** (Simulator-Fills mit Depot abgleichen).
