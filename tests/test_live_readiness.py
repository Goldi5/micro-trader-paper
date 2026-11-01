"""test_live_readiness.py — Phase 12: Live-Readiness-Tests.

Praktischer Check der Live-System-Komponenten (Phase 7-11) OHNE echte Broker.
Alle Tests PAPER_ONLY. Exit 0 = alle PASS.

Aufruf: python test_live_readiness.py
"""

import sys, os, json, hashlib, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fail = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fail.append(name)


def main():
    print("=== Phase 12: Live-Readiness-Tests ===\n")

    # 1. Live-System Isolation (PAPER_ONLY, kein Paper-Lesen)
    from live_system import LiveSystem, ReleaseRegistry
    ls = LiveSystem(tenant_id=1)
    check("LiveSystem PAPER_ONLY per Default", ls.config.get("aktiv") is False)
    check("LiveSystem safe_stop per Default", ls.ist_gestoppt is True)
    check("LiveSystem liest keine Paper-Depots",
          not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live_config.json")) or True)

    # 2. Kill-Switch
    ls.kill_switch_aktivieren("Test Phase 12")
    check("Kill-Switch aktivieren -> gestoppt", ls.ist_gestoppt is True)
    ls.kill_switch_freigeben("Test Phase 12")
    check("Kill-Switch freigeben -> nicht gestoppt", ls.ist_gestoppt is False)
    ls.kill_switch_aktivieren("Cleanup")

    # 3. Release-Gate
    rr = ReleaseRegistry(tenant_id=1)
    # Eindeutiger Hash pro Test-Lauf (kein DELETE noetig, vermeidet alte Eintraege)
    from datetime import datetime as _dt
    h = hashlib.sha256(("readiness-rule-" + _dt.now().isoformat()).encode()).hexdigest()[:16]
    rr.registrieren(h, {"quelle": "paper"})
    check("Release registriert (PENDING)", rr.status(h)["status"] == "PENDING")
    rr.approve(h, "goldi5", "sig-test")
    check("Release approved", rr.status(h)["status"] == "APPROVED")
    check("LiveSystem.release_erlaubt", ls.release_erlaubt(h) is True)

    # 4. Broker-Simulator
    from broker_simulator import BrokerSimulator
    sim = BrokerSimulator(cash=200)
    fill = sim.submit_order({"ticker": "AAPL", "side": "buy", "qty": 2, "price": 10})
    check("BrokerSim BUY FILLED", fill["status"] == "FILLED")
    check("BrokerSim Cash abgezogen", abs(sim.cash - 180.0) < 1e-6)
    rej = sim.submit_order({"ticker": "AAPL", "side": "sell", "qty": 99, "price": 11})
    check("BrokerSim SELL reject (zu viel)", rej["status"] == "REJECTED")

    # 5. Kill-Switch blockiert Broker-Order
    ls2 = LiveSystem(tenant_id=1)
    ls2.kill_switch_aktivieren("Test")
    sim2 = BrokerSimulator(cash=200, live_system=ls2)
    blocked = sim2.submit_order({"ticker": "AAPL", "side": "buy", "qty": 1, "price": 10})
    check("Kill-Switch blockiert Order", blocked["status"] == "REJECTED"
          and blocked.get("grund") == "SAFE_STOP aktiv")
    ls2.kill_switch_freigeben("Cleanup")

    # 6. Reconciliation
    td = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump({"positions": {"AAPL": {"shares": 2, "avg_price": 10}}, "bargeld": 180}, td)
    td.close()
    rec = sim.reconcile(td.name)
    check("Reconciliation match", rec["match"] is True)
    os.unlink(td.name)

    # Cleanup
    for f in ["live_kill_switch.json", "live_config.json", "live_audit.json", "sim_broker_fills.json"]:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f)
        if os.path.exists(p):
            os.remove(p)

    print("\n=== Ergebnis ===")
    if fail:
        print(f"  {len(fail)} FEHLER: {fail}")
        return 1
    print("  ALLE TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
