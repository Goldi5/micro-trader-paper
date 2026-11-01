# ORDER-SYNC-RECONCILIATION — Phase 10

> Phase 10: Order-Sync + Reconciliation. Stand: 2026-08-12.

## Änderung

- `broker_simulator.BrokerSimulator.reconcile(depot_json_pfad)` (NEU):
  gleicht Sim-Positionen mit Depot-Datei ab. Returns `match` + `unterschiede`.
  Unterstützt Format A (Spec top-level shares) + Format B (positions-dict).

## Verifikation (ad-hoc, PASS)

```bash
python -c "from broker_simulator import BrokerSimulator; s=BrokerSimulator(200);
s.submit_order({'ticker':'AAPL','side':'buy','qty':2,'price':10});
import json; json.dump({'positions':{'AAPL':{'shares':2}},'bargeld':180}, open('t.json','w'));
print(s.reconcile('t.json')['match'])"   # -> True
```

PAPER_ONLY gewahrt (nur Simulation, keine echten Orders).

## Nächste Phase

**Phase 11 — Live-Admin, Kill-Switch, Monitoring.**
